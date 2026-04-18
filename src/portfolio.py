"""資産管理・PnL計算

ファイルの役割: ポートフォリオ統計・未実現損益・取引履歴を管理
なぜ存在するか: 取引の成績追跡と利益計算のため
関連ファイル: bot.py（メインループ）, persistence.py（永続化）, fee.py（手数料計算）
"""

import math
import threading
from dataclasses import dataclass, field
from datetime import datetime

from src import persistence as persistence_module
from src.binance_client import BinanceClient
from utils.fee import calculate_net_profit
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
    # ── リスク指標 ─────────────────────────────────────────────────
    peak_balance: float = 0.0  # 過去最高残高（実現利益込み）
    max_drawdown: float = 0.0  # 最大ドローダウン（USD）
    max_drawdown_pct: float = 0.0  # 最大ドローダウン率（%）
    sharpe_ratio: float = 0.0  # シャープレシオ（年間・推定）
    # ── 月次/年次サマリー ───────────────────────────────────────────
    monthly_profit: dict[str, float] = field(default_factory=dict)  # {"YYYY-MM": profit}
    yearly_profit: dict[str, float] = field(default_factory=dict)  # {"YYYY": profit}
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

        # 残高を成功するまでリトライ（起動时必须）
        max_retries = 10
        for attempt in range(max_retries):
            if self._update_balance():
                break
            if attempt < max_retries - 1:
                import time as _time

                _time.sleep(2**attempt)  # 指数バックオフ
        else:
            raise RuntimeError(f"残高の取得に失敗しました（{max_retries}回リトライ後）")

        self.stats.initial_balance = self.stats.current_balance

        logger.info(
            f"ポートフォリオ初期化: 初期残高={self.stats.initial_balance:.2f} {quote_asset}"
        )

    # ── 残高 ─────────────────────────────────────────────────────────

    def _update_balance(self) -> bool:
        """残高を更新。失敗時はFalseを返す"""
        try:
            balances = self.client.get_account_balance()
            if self.quote_asset in balances:
                info = balances[self.quote_asset]
                new_balance = info["free"] + info["locked"]
                if new_balance >= 0:
                    self.stats.current_balance = new_balance
                    return True
                else:
                    logger.warning(f"異常な残高値を受信: {new_balance}。更新をスキップします。")
                    return False
            else:
                logger.warning(f"残高情報に {self.quote_asset} が含まれていません")
                return False
        except Exception as e:
            logger.error(f"残高取得失敗: {e}")
            return False

    # ── トレード記録 ─────────────────────────────────────────────────

    def restore_trades(self, trade_records: list[dict]):
        """DBから復元したトレード履歴を読み込み（上限適用済み）"""
        trades = [
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
        if len(trades) > self._max_trades:
            unmatched = [t for t in trades if t.side == "BUY" and not t.matched]
            evictable = [t for t in trades if t.side == "SELL" or t.matched]
            keep_count = self._max_trades - len(unmatched)
            matched_to_keep = evictable[-keep_count:] if keep_count > 0 else []
            self.trades = unmatched + matched_to_keep
        else:
            self.trades = trades
        logger.info(f"トレード履歴を復元: {len(self.trades)} 件 (DB内: {len(trade_records)} 件)")

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
        matched_buy_order_id: int | None = None

        with self._lock:
            self.trades.append(trade)
            self._evict_trades_if_needed()
            self.stats.total_trades += 1
            self.stats.last_update = datetime.now()

            if side == "SELL":
                result = self._settle_sell(trade, grid_level)
                if result is not None:
                    profit, matched_buy_order_id = result
                    # 月次/年次利益を更新
                    self._update_periodic_profit(profit, trade.timestamp)

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
            # SELL約定時に対応するBUYのmatchedもDBに反映
            if side == "SELL" and matched_buy_order_id is not None:
                persistence_module.update_trade_matched(matched_buy_order_id, True)
        except Exception as e:
            logger.error(f"トレード保存失敗: {e}")

        logger.info(f"取引記録追加: {side} {quantity} @ {price}")
        return profit

    def _settle_sell(self, trade: Trade, grid_level: int) -> tuple[float, int] | None:
        """売り決済処理（ロック内で呼ぶこと）。(profit, buy_order_id) を返すか None。"""
        # 同じグリッドの全未決済BUYを取得
        buy_trades = [
            t
            for t in self.trades
            if t.side == "BUY" and t.grid_level == grid_level and not t.matched
        ]
        if not buy_trades:
            return None

        # 最初の(最新の) buy_trade を代表として使用
        buy_trade = buy_trades[-1]

        # 同じグリッドの全ての未決済BUYをマッチ済みに設定（重複防止）
        for b in buy_trades:
            b.matched = True

        # 数量の合計（複数_BUY_がある場合の平均単価計算用）
        total_buy_qty = sum(t.quantity for t in buy_trades)
        # 加重平均買い価格を計算
        total_buy_cost = sum(t.price * t.quantity for t in buy_trades)
        avg_buy_price = total_buy_cost / total_buy_qty if total_buy_qty > 0 else buy_trade.price

        if self._fee_rate > 0:
            profit, buy_fee, sell_fee = calculate_net_profit(
                avg_buy_price, trade.price, trade.quantity, self._fee_rate
            )
            self.stats.total_fees += buy_fee + sell_fee
        else:
            profit = (trade.price - avg_buy_price) * trade.quantity

        trade.profit = profit
        trade.matched = True

        self._update_settled_stats(profit)

        logger.info(
            f"取引記録: グリッド {grid_level}, 利益={profit:.2f} "
            f"(買い数量合計={total_buy_qty}, 平均={avg_buy_price:.4f}, "
            f"売り数量={trade.quantity})"
        )
        return profit, buy_trade.order_id

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

    # ── リスク指標 ───────────────────────────────────────────────────

    def _update_periodic_profit(self, profit: float, timestamp: datetime):
        """月次/年次利益を更新"""
        year = timestamp.strftime("%Y")
        month = timestamp.strftime("%Y-%m")

        if year not in self.stats.yearly_profit:
            self.stats.yearly_profit[year] = 0.0
        self.stats.yearly_profit[year] += profit

        if month not in self.stats.monthly_profit:
            self.stats.monthly_profit[month] = 0.0
        self.stats.monthly_profit[month] += profit

    def _calculate_sharpe_ratio(self):
        """シャープレシオを計算（簡略版・年間推定）

        Sharpe = (年均回报 - 無リスク利率) / 年標準偏差
        無リスク利率は0%、標準偏差は直近利益の分散から推定。
        """
        if self.stats.initial_balance <= 0:
            return

        if not self.stats.start_time:
            return

        # 経過日数
        days = (datetime.now() - self.stats.start_time).days
        if days < 1:
            return

        # 年率リターン（%）
        annual_return = (self.stats.total_profit / self.stats.initial_balance) * (365 / days) * 100

        # 利益の標準偏差（%）
        if len(self.trades) < 2:
            self.stats.sharpe_ratio = 0.0
            return

        settled = [t for t in self.trades if t.profit is not None and t.matched]
        if len(settled) < 2:
            self.stats.sharpe_ratio = 0.0
            return

        profits = [t.profit for t in settled]
        avg = sum(profits) / len(profits)
        variance = sum((p - avg) ** 2 for p in profits) / len(profits)
        std = math.sqrt(variance)

        if std == 0:
            self.stats.sharpe_ratio = 0.0
            return

        # 年率標準偏差
        annual_std = std * math.sqrt(365 / days) if days > 0 else std

        self.stats.sharpe_ratio = annual_return / annual_std if annual_std > 0 else 0.0

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

            # ── リスク指標更新 ───────────────────────────────────────
            total_equity = self.stats.current_balance + unrealized

            # ピーク残高更新
            if total_equity > self.stats.peak_balance:
                self.stats.peak_balance = total_equity

            # 最大ドローダウン計算（絶対額と率を同期）
            if self.stats.peak_balance > 0:
                dd_abs = self.stats.peak_balance - total_equity
                if dd_abs > self.stats.max_drawdown:
                    self.stats.max_drawdown = dd_abs
                    self.stats.max_drawdown_pct = (dd_abs / self.stats.peak_balance) * 100

            # シャープレシオ計算（年間リターン/標準偏差、簡略版）
            self._calculate_sharpe_ratio()

    # ── レポート・統計 ───────────────────────────────────────────────

    def get_stats(self) -> PortfolioStats:
        return self.stats

    def refresh_stats(self) -> PortfolioStats:
        self._update_balance()
        return self.stats

    def get_trade_history(self, limit: int = 20) -> list[Trade]:
        return self.trades[-limit:]

    def generate_report(self) -> str:
        from src.report import generate_portfolio_report

        self._update_balance()
        return generate_portfolio_report(self)

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
