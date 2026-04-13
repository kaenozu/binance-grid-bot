"""
ファイルパス: src/backtest.py
概要: バックテスト機能
説明: 過去の価格データを使ってグリッド戦略をシミュレーション
関連ファイル: src/grid_strategy.py, src/portfolio.py, config/settings.py
"""

from datetime import datetime
from typing import Optional

import requests
from config.settings import Settings
from src.grid_strategy import GridStrategy
from src.portfolio import PortfolioStats
from utils.logger import setup_logger

logger = setup_logger("backtest")


class BacktestDataFetcher:
    """過去の価格データを取得するクラス"""

    BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"

    @classmethod
    def fetch_klines(
        cls, symbol: str, interval: str = "1h", limit: int = 500
    ) -> list[dict]:
        """K線データを取得

        Args:
            symbol: 取引ペア
            interval: 時間足 (1m, 5m, 15m, 1h, 4h, 1d)
            limit: 取得件数（最大1000）

        Returns:
            K線データのリスト
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000),
        }

        try:
            response = requests.get(cls.BINANCE_KLINE_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            klines = []
            for k in data:
                klines.append(
                    {
                        "open_time": datetime.fromtimestamp(k[0] / 1000),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                        "close_time": datetime.fromtimestamp(k[6] / 1000),
                    }
                )

            return klines

        except requests.exceptions.RequestException as e:
            logger.error(f"K線データ取得失敗: {e}")
            return []


class BacktestEngine:
    """バックテストエンジン"""

    # バックテスト用のデフォルト数量パラメータ
    DEFAULT_MIN_QTY = 0.00001
    DEFAULT_STEP_SIZE = 0.00001
    DEFAULT_MIN_NOTIONAL = 5.0  # USDT

    def __init__(
        self,
        symbol: str,
        investment_amount: float,
        grid_count: int,
        lower_price: Optional[float] = None,
        upper_price: Optional[float] = None,
        stop_loss_percent: float = 5.0,
        min_qty: float = DEFAULT_MIN_QTY,
        step_size: float = DEFAULT_STEP_SIZE,
        min_notional: float = DEFAULT_MIN_NOTIONAL,
    ):
        """
        Args:
            symbol: 取引ペア
            investment_amount: 投資額
            grid_count: グリッド数
            lower_price: グリッド下限（Noneで自動）
            upper_price: グリッド上限（Noneで自動）
            stop_loss_percent: 損切り割合（%）
            min_qty: 最小注文数量（LOT_SIZE filter）
            step_size: 数量の刻み幅（LOT_SIZE filter）
            min_notional: 最低注文金額（MIN_NOTIONAL filter）
        """
        self.symbol = symbol
        self.investment_amount = investment_amount
        self.grid_count = grid_count
        self.lower_price = lower_price
        self.upper_price = upper_price
        self.stop_loss_percent = stop_loss_percent
        self.min_qty = min_qty
        self.step_size = step_size
        self.min_notional = min_notional

        self.strategy: Optional[GridStrategy] = None
        self.stats = PortfolioStats(
            initial_balance=investment_amount,
            current_balance=investment_amount,
        )
        self.buy_orders: dict[int, float] = {}
        self.positions: dict[int, float] = {}

        self.total_trades = 0
        self.total_profit = 0.0
        self.max_drawdown = 0.0
        self.stop_loss_triggered = False

    def run(self, klines: list[dict]) -> dict:
        """バックテストを実行

        Args:
            klines: K線データのリスト

        Returns:
            テスト結果（空のdictはエラー）
        """
        if not klines:
            logger.error("K線データが空です")
            return {}

        initial_price = klines[0]["close"]

        range_factor = Settings.GRID_RANGE_FACTOR
        lower = self.lower_price if self.lower_price else initial_price * (1 - range_factor)
        upper = self.upper_price if self.upper_price else initial_price * (1 + range_factor)

        self.strategy = GridStrategy(
            symbol=self.symbol,
            current_price=initial_price,
            lower_price=lower,
            upper_price=upper,
            grid_count=self.grid_count,
            investment_amount=self.investment_amount,
        )

        self._place_initial_orders()

        peak_value = self.investment_amount

        for i, kline in enumerate(klines[1:], 1):
            current_price = kline["close"]
            self.strategy.update_current_price(current_price)

            # 損切り: lower_price を基準に（RiskManager と統一）
            stop_loss_price = lower * (1 - self.stop_loss_percent / 100)
            if current_price <= stop_loss_price:
                self.stop_loss_triggered = True
                logger.info(f"損切り発動: {i}番目のK線 @ {current_price:.2f}")
                break

            if not self.strategy.is_within_grid_range(current_price):
                continue

            self._check_fills(kline)

            current_value = self._calculate_portfolio_value(current_price)
            if current_value > peak_value:
                peak_value = current_value

            if peak_value > 0:
                drawdown = (peak_value - current_value) / peak_value * 100
                if drawdown > self.max_drawdown:
                    self.max_drawdown = drawdown

        return self._generate_report(klines)

    def _place_initial_orders(self):
        """初期買い注文を記録"""
        for grid in self.strategy.get_active_buy_grids():
            self.buy_orders[grid.level] = grid.buy_price

    def _check_fills(self, kline: dict):
        """K線のhigh/lowを使って約定をチェック

        注意: 同一K線内で買い→売りの連続約定を防止するため、
        売り約定済みのグリッドはそのK線内で再処理しない
        """
        high = kline["high"]
        low = kline["low"]
        filled_this_kline: set[int] = set()  # このK線で売り約定したグリッド

        for grid in self.strategy.grids:
            # 売り約定済みのグリッドはスキップ
            if grid.level in filled_this_kline:
                continue

            if grid.level in self.buy_orders and grid.level not in self.positions:
                if low <= grid.buy_price:
                    quantity = self.strategy.get_order_quantity(
                        grid.buy_price,
                        min_qty=self.min_qty,
                        step_size=self.step_size,
                        min_notional=self.min_notional,
                    )
                    self.positions[grid.level] = quantity
                    logger.debug(
                        f"買い約定: グリッド {grid.level} @ {grid.buy_price:.2f}"
                    )

            if grid.level in self.positions:
                buy_price = self.buy_orders.get(grid.level, grid.buy_price)
                if grid.sell_price and high >= grid.sell_price:
                    quantity = self.positions.pop(grid.level)
                    profit = (grid.sell_price - buy_price) * quantity
                    self.total_profit += profit
                    self.total_trades += 1

                    # グリッドをリセットして次の売買サイクルに備える
                    self.buy_orders[grid.level] = grid.buy_price
                    filled_this_kline.add(grid.level)

                    logger.debug(
                        f"売り約定: グリッド {grid.level} @ {grid.sell_price:.2f}, 利益={profit:.2f}"
                    )

    def _calculate_portfolio_value(self, current_price: float) -> float:
        """ポートフォリオ価値を計算

        現金残高 = 初期投資額 - 保有ポジションの購入費用合計
        資産評価額 = 保有数量 × 現在価格
        ポートフォリオ価値 = 現金残高 + 資産評価額 + 実現利益合計
        """
        total_cost = sum(
            self.buy_orders.get(level, 0) * qty
            for level, qty in self.positions.items()
        )
        cash = self.investment_amount - total_cost
        asset_value = sum(self.positions.values()) * current_price

        return cash + asset_value + self.total_profit

    def _generate_report(self, klines: list[dict]) -> dict:
        """レポートを生成"""
        start_price = klines[0]["close"]
        end_price = klines[-1]["close"]
        price_change = (end_price - start_price) / start_price * 100

        total_value = self.investment_amount + self.total_profit
        roi = (total_value - self.investment_amount) / self.investment_amount * 100

        return {
            "symbol": self.symbol,
            "period": f"{klines[0]['open_time']} ~ {klines[-1]['open_time']}",
            "kline_count": len(klines),
            "start_price": start_price,
            "end_price": end_price,
            "price_change_percent": price_change,
            "grid_count": self.grid_count,
            "grid_range": f"{self.strategy.lower_price:.2f} - {self.strategy.upper_price:.2f}",
            "total_trades": self.total_trades,
            "total_profit": self.total_profit,
            "roi_percent": roi,
            "max_drawdown_percent": self.max_drawdown,
            "stop_loss_triggered": self.stop_loss_triggered,
            "avg_profit_per_trade": self.total_profit / self.total_trades
            if self.total_trades > 0
            else 0,
        }
