"""
ファイルパス: src/portfolio.py
概要: 資産管理・PnL計算
説明: 取引履歴の追跡、損益計算、資産状況レポートを提供
関連ファイル: src/binance_client.py, src/risk_manager.py, src/bot.py
"""

from datetime import datetime
from dataclasses import dataclass
from typing import Optional

from src.binance_client import BinanceClient
from src import persistence as persistence_module
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
    start_time: Optional[datetime] = None
    last_update: Optional[datetime] = None


class Portfolio:
    """資産管理クラス"""

    def __init__(
        self, client: BinanceClient, symbol: str, quote_asset: str = "USDT", fee_rate: float = 0.0
    ):
        """
        Args:
            client: Binance API クライアント
            symbol: 取引ペア
            quote_asset: 証拠金資産（デフォルト: USDT）
            fee_rate: 取引手数料率
        """
        self.client = client
        self.symbol = symbol
        self.quote_asset = quote_asset
        self._fee_rate = fee_rate

        self.trades: list[Trade] = []
        self._max_trades = 10000
        self.stats = PortfolioStats()
        self.stats.start_time = datetime.now()
        self.stats.last_update = datetime.now()

        self._update_balance()
        self.stats.initial_balance = self.stats.current_balance

        logger.info(
            f"ポートフォリオ初期化: 初期残高={self.stats.initial_balance:.2f} {quote_asset}"
        )

    def _update_balance(self):
        """残高を更新"""
        try:
            balances = self.client.get_account_balance()
            if self.quote_asset in balances:
                info = balances[self.quote_asset]
                self.stats.current_balance = info["free"] + info["locked"]
        except Exception as e:
            logger.error(f"残高取得失敗: {e}")

    def restore_trades(self, trade_records: list[dict]):
        """DBから復元したトレード履歴を読み込み"""
        self.trades = []
        for r in trade_records:
            self.trades.append(
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
            )
        logger.info(f"トレード履歴を復元: {len(self.trades)} 件")

    def record_trade(
        self, side: str, price: float, quantity: float, order_id: int, grid_level: int
    ) -> Optional[float]:
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

        self.trades.append(trade)
        if len(self.trades) > self._max_trades:
            unmatched_buys = [t for t in self.trades if t.side == "BUY" and not t.matched]
            matched_trades = [t for t in self.trades if t.matched or t.side == "SELL"]
            matched_to_keep = matched_trades[-(self._max_trades - len(unmatched_buys)) :]
            self.trades = unmatched_buys + matched_to_keep
        self.stats.total_trades += 1
        self.stats.last_update = datetime.now()

        profit: Optional[float] = None

        if side == "SELL":
            buy_trade = self.find_matching_buy_trade(grid_level)
            if buy_trade:
                profit = (price - buy_trade.price) * quantity
                fee_rate = self._fee_rate
                if fee_rate > 0 and buy_trade:
                    buy_fee = buy_trade.price * quantity * fee_rate
                    sell_fee = price * quantity * fee_rate
                    profit = profit - buy_fee - sell_fee
                    self.stats.total_fees += buy_fee + sell_fee
                trade.profit = profit
                buy_trade.matched = True
                trade.matched = True
                self.stats.realized_profit += profit
                self.stats.settled_trades += 1
                self.stats.total_profit = self.stats.realized_profit + self.stats.unrealized_profit

                if profit > 0:
                    self.stats.winning_trades += 1
                else:
                    self.stats.losing_trades += 1

                if self.stats.settled_trades > 0:
                    self.stats.win_rate = (
                        self.stats.winning_trades / self.stats.settled_trades * 100
                    )
                self.stats.avg_profit_per_trade = (
                    self.stats.realized_profit / self.stats.settled_trades
                )

                logger.info(f"取引記録: グリッド {grid_level}, 利益={profit:.2f}")

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

    def find_matching_buy_trade(self, grid_level: int) -> Optional[Trade]:
        """対応する未マッチの買い注文を最新順に探す

        Args:
            grid_level: グリッドレベル

        Returns:
            対応する買い注文（ない場合はNone）
        """
        for trade in reversed(self.trades):
            if trade.side == "BUY" and trade.grid_level == grid_level and not trade.matched:
                return trade
        return None

    def calculate_unrealized_pnl(self, current_price: float):
        """未実現損益を計算（手数料反映）"""
        unrealized = 0.0
        fee_rate = self._fee_rate

        for trade in self.trades:
            if trade.side == "BUY" and not trade.matched:
                gross = (current_price - trade.price) * trade.quantity
                if fee_rate > 0:
                    gross -= trade.price * trade.quantity * fee_rate
                unrealized += gross

        self.stats.unrealized_profit = unrealized
        self.stats.total_profit = self.stats.realized_profit + unrealized

    def get_stats(self) -> PortfolioStats:
        """統計情報（キャッシュ）を返す"""
        return self.stats

    def refresh_stats(self) -> PortfolioStats:
        """統計情報を最新に更新"""
        self._update_balance()
        return self.stats

    def get_trade_history(self, limit: int = 20) -> list[Trade]:
        """取引履歴を返す"""
        return self.trades[-limit:]

    def generate_report(self) -> str:
        """レポートを生成"""
        self._update_balance()

        elapsed = datetime.now() - self.stats.start_time if self.stats.start_time else None
        hours = elapsed.total_seconds() / 3600 if elapsed else 0

        report = f"""
===== ポートフォリオレポート =====
実行時間: {hours:.2f} 時間
初期残高: {self.stats.initial_balance:.2f} {self.quote_asset}
現在残高: {self.stats.current_balance:.2f} {self.quote_asset}
--------------------------------
実現利益: {self.stats.realized_profit:+.2f} {self.quote_asset}
未実現利益: {self.stats.unrealized_profit:+.2f} {self.quote_asset}
総利益: {self.stats.total_profit:+.2f} {self.quote_asset}
--------------------------------
取引回数: {self.stats.total_trades}
勝率: {self.stats.win_rate:.1f}%
平均利益/取引: {self.stats.avg_profit_per_trade:+.2f} {self.quote_asset}
================================
"""
        return report.strip()
