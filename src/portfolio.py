"""資産管理・PnL計算"""

import threading
from dataclasses import dataclass
from datetime import datetime

from src import persistence as persistence_module
from src.binance_client import BinanceClient
from src.fee import calculate_net_profit
from utils.logger import setup_logger

logger = setup_logger("portfolio")


@dataclass
class Trade:
    """取引記録"""

    timestamp: datetime
    symbol: str
    side: str
    price: float
    quantity: float
    order_id: int
    grid_level: int
    profit: float = 0.0
    matched: bool = False


@dataclass
class PortfolioStats:
    """ポートフォリオ統計"""

    initial_balance: float = 0.0
    current_balance: float = 0.0
    total_profit: float = 0.0
    realized_profit: float = 0.0
    unrealized_profit: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    settled_trades: int = 0
    win_rate: float = 0.0
    avg_profit_per_trade: float = 0.0
    total_fees: float = 0.0
    start_time: datetime | None = None
    last_update: datetime | None = None


class Portfolio:
    """資産管理クラス"""

    def __init__(
        self, client: BinanceClient, symbol: str, quote_asset: str = "USDT", fee_rate: float = 0.0
    ):
        self.client = client
        self.symbol = symbol
        self.quote_asset = quote_asset
        self._fee_rate = fee_rate
        self._lock = threading.Lock()

        self.trades: list[Trade] = []
        self._max_trades = 10000
        self.stats = PortfolioStats()
        self.stats.start_time = datetime.now()
        self.stats.last_update = datetime.now()

        self._update_balance()
        if self.stats.current_balance > 0:
            self.stats.initial_balance = self.stats.current_balance
        else:
            logger.error("残高取得失敗: initial_balance を設定できませんでした")

        logger.info(
            f"ポートフォリオ初期化: 初期残高={self.stats.initial_balance:.2f} {quote_asset}"
        )

    # ── 残高 ─────────────────────────────────────────────────────────

    def _update_balance(self):
        """残高を更新"""
        try:
            balances = self.client.get_account_balance()
            if self.quote_asset in balances:
                info = balances[self.quote_asset]
                self.stats.current_balance = info["free"] + info["locked"]
        except Exception as e:
            logger.error(f"残高取得失敗: {e}")

    # ── トレード記録 ─────────────────────────────────────────────────

    def restore_trades(self, trade_records: list[dict]):
        """DBから復元したトレード履歴を読み込み"""
        self.trades = [
            Trade(
                timestamp=r["timestamp"],
                symbol=r["symbol"],
                side=r["side"],
                price=r["price"],
                quantity=r["quantity"],
                order_id=r["order_id"],
                grid_level=r["grid_level"],
                profit=r["profit"],
                matched=r["matched"],
            )
            for r in trade_records
        ]
        logger.info(f"トレード履歴を復元: {len(self.trades)} 件")

    def record_trade(
        self, side: str, price: float, quantity: float, order_id: int, grid_level: int
    ) -> float | None:
        """取引を記録

        Returns:
            SELL時の利益、BUY時はNone
        """
        trade = Trade(
            timestamp=datetime.now(),
            symbol=self.symbol,
            side=side,
            price=price,
            quantity=quantity,
            order_id=order_id,
            grid_level=grid_level,
        )

        profit: float | None = None

        with self._lock:
            self.trades.append(trade)
            self._evict_trades_if_needed()
            self.stats.total_trades += 1
            self.stats.last_update = datetime.now()

            if side == "SELL":
                profit = self._settle_sell(trade, grid_level)

        # ロック外で永続化（DB I/O はロック保持しない）
        try:
            persistence_module.save_trade(
                timestamp=trade.timestamp,
                symbol=trade.symbol,
                side=trade.side,
                price=trade.price,
                quantity=trade.quantity,
                order_id=trade.order_id,
                grid_level=trade.grid_level,
                profit=trade.profit,
                matched=trade.matched,
            )
        except Exception as e:
            logger.error(f"トレード保存失敗: {e}")

        logger.info(f"取引記録追加: {side} {quantity} @ {price}")
        return profit

    def _settle_sell(self, trade: Trade, grid_level: int) -> float | None:
        """売り決済処理（ロック内で呼ぶこと）。利益を返すか None。"""
        buy_trade = self._find_matching_buy_locked(grid_level)
        if not buy_trade:
            return None

        if self._fee_rate > 0:
            profit, buy_fee, sell_fee = calculate_net_profit(
                buy_trade.price, trade.price, trade.quantity, self._fee_rate
            )
            self.stats.total_fees += buy_fee + sell_fee
        else:
            profit = (trade.price - buy_trade.price) * trade.quantity

        trade.profit = profit
        buy_trade.matched = True
        trade.matched = True

        self._update_settled_stats(profit)

        logger.info(f"取引記録: グリッド {grid_level}, 利益={profit:.2f}")
        return profit

    def _update_settled_stats(self, profit: float):
        """決済統計を更新（ロック内で呼ぶこと）"""
        self.stats.realized_profit += profit
        self.stats.settled_trades += 1
        self.stats.total_profit = self.stats.realized_profit + self.stats.unrealized_profit

        if profit > 0:
            self.stats.winning_trades += 1
        else:
            self.stats.losing_trades += 1

        if self.stats.settled_trades > 0:
            self.stats.win_rate = self.stats.winning_trades / self.stats.settled_trades * 100
        self.stats.avg_profit_per_trade = self.stats.realized_profit / self.stats.settled_trades

    # ── トレード検索 ─────────────────────────────────────────────────

    def _find_matching_buy_locked(self, grid_level: int) -> Trade | None:
        """対応する未マッチの買い注文を最新順に探す（ロック内で呼ぶこと）"""
        for trade in reversed(self.trades):
            if trade.side == "BUY" and trade.grid_level == grid_level and not trade.matched:
                return trade
        return None

    def find_matching_buy_trade(self, grid_level: int) -> Trade | None:
        """対応する未マッチの買い注文を最新順に探す（スレッドセーフ）"""
        with self._lock:
            return self._find_matching_buy_locked(grid_level)

    # ── 未実現損益 ───────────────────────────────────────────────────

    def calculate_unrealized_pnl(self, current_price: float):
        with self._lock:
            unrealized = 0.0
            for trade in self.trades:
                if trade.side == "BUY" and not trade.matched:
                    gross = (current_price - trade.price) * trade.quantity
                    if self._fee_rate > 0:
                        gross -= trade.price * trade.quantity * self._fee_rate
                        gross -= current_price * trade.quantity * self._fee_rate
                    unrealized += gross
            self.stats.unrealized_profit = unrealized
            self.stats.total_profit = self.stats.realized_profit + unrealized

    # ── レポート・統計 ───────────────────────────────────────────────

    def get_stats(self) -> PortfolioStats:
        return self.stats

    def refresh_stats(self) -> PortfolioStats:
        self._update_balance()
        return self.stats

    def get_trade_history(self, limit: int = 20) -> list[Trade]:
        return self.trades[-limit:]

    def generate_report(self) -> str:
        self._update_balance()
        elapsed = datetime.now() - self.stats.start_time if self.stats.start_time else None
        hours = elapsed.total_seconds() / 3600 if elapsed else 0

        return (
            f"\n"
            f"===== ポートフォリオレポート =====\n"
            f"実行時間: {hours:.2f} 時間\n"
            f"初期残高: {self.stats.initial_balance:.2f} {self.quote_asset}\n"
            f"現在残高: {self.stats.current_balance:.2f} {self.quote_asset}\n"
            f"--------------------------------\n"
            f"実現利益: {self.stats.realized_profit:+.2f} {self.quote_asset}\n"
            f"未実現利益: {self.stats.unrealized_profit:+.2f} {self.quote_asset}\n"
            f"総利益: {self.stats.total_profit:+.2f} {self.quote_asset}\n"
            f"--------------------------------\n"
            f"取引回数: {self.stats.total_trades}\n"
            f"勝率: {self.stats.win_rate:.1f}%\n"
            f"平均利益/取引: {self.stats.avg_profit_per_trade:+.2f} {self.quote_asset}\n"
            f"================================"
        )

    # ── 内部ヘルパー ────────────────────────────────────────────────


def _evict_trades_if_needed(self):
    """トレードリストが上限を超えた場合、古いマッチ済み/売りトレードを削除（ロック内で呼ぶこと）"""
    if len(self.trades) <= self._max_trades:
        return
    unmatched_buys = [t for t in self.trades if t.side == "BUY" and not t.matched]
    evictable = [t for t in self.trades if t.side == "SELL" or t.matched]
    keep_count = self._max_trades - len(unmatched_buys)
    matched_to_keep = evictable[-keep_count:] if keep_count > 0 else []
    self.trades = unmatched_buys + matched_to_keep
