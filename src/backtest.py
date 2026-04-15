"""バックテスト機能

ファイルの役割:  과거価格データを使って取引戦略をシミュレーション
なぜ存在するか: 実資金リスクなく戦略の有効性を検証するため
関連ファイル: grid_strategy.py（戦略）, binance_client.py（価格取得）, exporter.py（結果出力）
"""

from datetime import datetime

import requests

from config.settings import Settings
from src.fee import calculate_net_profit
from src.grid_strategy import GridStrategy
from utils.logger import setup_logger

logger = setup_logger("backtest")


class BacktestDataFetcher:
    """過去の価格データを取得するクラス"""

    # 公開データのため常にMainnetを使用（TestnetはK線データが不十分なため）
    BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"

    @classmethod
    def fetch_klines(cls, symbol: str, interval: str = "1h", limit: int = 500) -> list[dict]:
        """K線データを取得"""
        params = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
        try:
            response = requests.get(cls.BINANCE_KLINE_URL, params=params, timeout=10)
            response.raise_for_status()
            return [
                {
                    "open_time": datetime.fromtimestamp(k[0] / 1000),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "close_time": datetime.fromtimestamp(k[6] / 1000),
                }
                for k in response.json()
            ]
        except requests.exceptions.RequestException as e:
            logger.error(f"K線データ取得失敗: {e}")
            return []


class BacktestEngine:
    """バックテストエンジン"""

    DEFAULT_MIN_QTY = 0.00001
    DEFAULT_STEP_SIZE = 0.00001
    DEFAULT_MIN_NOTIONAL = 5.0
    DEFAULT_FEE_RATE = 0.001

    def __init__(
        self,
        symbol: str,
        investment_amount: float,
        grid_count: int,
        lower_price: float | None = None,
        upper_price: float | None = None,
        stop_loss_percent: float = 5.0,
        min_qty: float = DEFAULT_MIN_QTY,
        step_size: float = DEFAULT_STEP_SIZE,
        min_notional: float = DEFAULT_MIN_NOTIONAL,
        fee_rate: float = DEFAULT_FEE_RATE,
    ):
        self.symbol = symbol
        self.investment_amount = investment_amount
        self.grid_count = grid_count
        self.lower_price = lower_price
        self.upper_price = upper_price
        self.stop_loss_percent = stop_loss_percent
        self.min_qty = min_qty
        self.step_size = step_size
        self.min_notional = min_notional
        self.fee_rate = fee_rate

        self.strategy: GridStrategy | None = None

        self.buy_orders: dict[int, float] = {}
        self.positions: dict[int, float] = {}
        self.total_trades = 0
        self.total_profit = 0.0
        self.max_drawdown = 0.0
        self.stop_loss_triggered = False

    def run(self, klines: list[dict]) -> dict:
        """バックテストを実行。空のdictはエラー。"""
        if not klines:
            logger.error("K線データが空です")
            return {}

        initial_price = klines[0]["close"]
        lower, upper = self._resolve_range(initial_price)

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
        stop_loss_price = lower * (1 - self.stop_loss_percent / 100)

        for i, kline in enumerate(klines[1:], 1):
            current_price = kline["close"]
            self.strategy.update_current_price(current_price)

            if current_price <= stop_loss_price:
                self.stop_loss_triggered = True
                logger.info(f"損切り発動: {i}番目のK線 @ {current_price:.2f}")
                break

            if not self.strategy.is_within_grid_range(current_price):
                continue

            self._check_fills(kline)
            peak_value = max(peak_value, self._calculate_portfolio_value(current_price))

            if peak_value > 0:
                drawdown = (peak_value - current_price) / peak_value * 100
                self.max_drawdown = max(self.max_drawdown, drawdown)

        return self._generate_report(klines)

    def _resolve_range(self, initial_price: float) -> tuple[float, float]:
        """グリッド範囲を解決"""
        factor = Settings.GRID_RANGE_FACTOR
        lower = self.lower_price if self.lower_price else initial_price * (1 - factor)
        upper = self.upper_price if self.upper_price else initial_price * (1 + factor)
        return lower, upper

    def _place_initial_orders(self):
        assert self.strategy is not None
        for grid in self.strategy.get_active_buy_grids():
            self.buy_orders[grid.level] = grid.buy_price

    def _check_fills(self, kline: dict):
        """K線のhigh/lowを使って約定をチェック

        同一K線内で買い→売りの連続約定を防止するため、
        売り約定済みのグリッドはそのK線内で再処理しない
        """
        high, low = kline["high"], kline["low"]
        filled_this_kline: set[int] = set()
        assert self.strategy is not None

        for grid in self.strategy.grids:
            if grid.level in filled_this_kline:
                continue

            # 買い約定チェック
            if grid.level in self.buy_orders and grid.level not in self.positions:
                if low <= grid.buy_price:
                    quantity = self.strategy.get_order_quantity(
                        grid.buy_price,
                        min_qty=self.min_qty,
                        step_size=self.step_size,
                        min_notional=self.min_notional,
                    )
                    self.positions[grid.level] = quantity
                    logger.debug(f"買い約定: グリッド {grid.level} @ {grid.buy_price:.2f}")

            # 売り約定チェック
            if grid.level in self.positions and grid.sell_price and high >= grid.sell_price:
                quantity = self.positions.pop(grid.level)
                buy_price = self.buy_orders.get(grid.level, grid.buy_price)
                profit, _, _ = calculate_net_profit(
                    buy_price, grid.sell_price, quantity, self.fee_rate
                )
                self.total_profit += profit
                self.total_trades += 1
                self.buy_orders[grid.level] = grid.buy_price
                filled_this_kline.add(grid.level)
                logger.debug(
                    f"売り約定: グリッド {grid.level} @ {grid.sell_price:.2f}, 利益={profit:.2f}"
                )

    def _calculate_portfolio_value(self, current_price: float) -> float:
        """ポートフォリオ価値 = 現金残高 + 資産評価額 - 手数料 + 実現利益"""
        positions = self.positions
        if not positions:
            return self.investment_amount + self.total_profit

        total_cost = sum(self.buy_orders.get(level, 0) * qty for level, qty in positions.items())
        buy_fees = sum(
            self.buy_orders.get(level, 0) * qty * self.fee_rate for level, qty in positions.items()
        )
        sell_fees = sum(qty * current_price * self.fee_rate for qty in positions.values())
        cash = self.investment_amount - total_cost
        asset_value = sum(positions.values()) * current_price - buy_fees - sell_fees
        return cash + asset_value + self.total_profit

    def _generate_report(self, klines: list[dict]) -> dict:
        start_price, end_price = klines[0]["close"], klines[-1]["close"]
        price_change = (end_price - start_price) / start_price * 100
        final_value = self._calculate_portfolio_value(end_price)
        roi = (final_value - self.investment_amount) / self.investment_amount * 100

        assert self.strategy is not None
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
            "avg_profit_per_trade": (
                self.total_profit / self.total_trades if self.total_trades > 0 else 0
            ),
        }
