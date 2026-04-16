"""グリッド取引戦略"""

import math
from dataclasses import dataclass

from config.settings import Settings
from utils.logger import setup_logger

logger = setup_logger("grid_strategy")


@dataclass
class GridLevel:
    """グリッドレベル（各注文の価格帯）"""

    level: int
    buy_price: float
    sell_price: float | None
    buy_order_id: int | None = None
    sell_order_id: int | None = None
    position_filled: bool = False
    filled_quantity: float | None = None


class GridStrategy:
    """グリッド取引戦略"""

    def __init__(
        self,
        symbol: str,
        current_price: float,
        lower_price: float | None = None,
        upper_price: float | None = None,
        grid_count: int | None = None,
        investment_amount: float | None = None,
    ):
        self.symbol = symbol
        self.current_price = current_price
        self.grid_count = grid_count or Settings.GRID_COUNT
        self.investment_amount = investment_amount or Settings.INVESTMENT_AMOUNT

        if lower_price is not None and upper_price is not None:
            self.lower_price = lower_price
            self.upper_price = upper_price
        else:
            factor = Settings.GRID_RANGE_FACTOR
            self.lower_price = current_price * (1 - factor)
            self.upper_price = current_price * (1 + factor)
            logger.info(f"価格帯を自動設定: {self.lower_price:.2f} - {self.upper_price:.2f}")

        if self.upper_price <= self.lower_price:
            raise ValueError(
                f"Invalid price range: lower={self.lower_price}, upper={self.upper_price}"
            )
        if self.lower_price <= 0:
            raise ValueError(f"Invalid lower_price: {self.lower_price}")

        self.grids: list[GridLevel] = []
        self._calculate_grids()

        logger.info(
            f"グリッド戦略初期化: {self.grid_count} グリッド, "
            f"範囲: {self.lower_price:.2f}-{self.upper_price:.2f}, "
            f"間隔: {self.grid_spacing:.2f}"
        )

    # ── プロパティ ──────────────────────────────────────────────────

    @property
    def grid_spacing(self) -> float:
        """グリッド間隔"""
        return (self.upper_price - self.lower_price) / self.grid_count

    @property
    def profit_per_grid_percent(self) -> float:
        """1グリッドあたりの利益率（%）"""
        return (self.grid_spacing / self.lower_price) * 100

    # ── グリッド計算 ────────────────────────────────────────────────

    def _calculate_grids(self):
        """グリッドレベルを計算"""
        spacing = self.grid_spacing
        self.grids = [
            GridLevel(
                level=i,
                buy_price=self.lower_price + spacing * i,
                sell_price=(
                    self.lower_price + spacing * (i + 1) if i < self.grid_count - 1 else None
                ),
            )
            for i in range(self.grid_count)
        ]
        logger.info(f"グリッド計算完了: {len(self.grids)} レベル")

    # ── 注文数量 ────────────────────────────────────────────────────

    def get_order_quantity(
        self,
        price: float,
        min_qty: float = 0,
        step_size: float = 0,
        min_notional: float = 0,
    ) -> float:
        """注文数量を計算（投資額を均等分配）"""
        amount_per_grid = self.investment_amount / self.grid_count
        raw_qty = amount_per_grid / price

        qty = math.floor(raw_qty / step_size) * step_size if step_size > 0 else raw_qty

        if min_qty > 0 and qty < min_qty:
            logger.warning(f"計算数量 {qty} が最小数量 {min_qty} を下回っています")
            qty = math.ceil(min_qty / step_size) * step_size if step_size > 0 else min_qty

        if min_notional > 0:
            notional_value = qty * price
            if notional_value < min_notional:
                logger.warning(
                    f"注文金額 {notional_value:.2f} USDT が最低注文金額 "
                    f"{min_notional:.2f} USDT を下回っています"
                )
                adjusted_qty = min_notional / price
                if step_size > 0:
                    adjusted_qty = math.ceil(adjusted_qty / step_size) * step_size
                qty = adjusted_qty

        return qty

    # ── アクティブグリッド ──────────────────────────────────────────

    def get_active_buy_grids(self) -> list[GridLevel]:
        """買い注文を配置すべきグリッド（未ポジション、sell_priceあり、現在価格以下）"""
        return [
            g
            for g in self.grids
            if g.buy_price <= self.current_price
            and not g.position_filled
            and g.sell_price is not None
        ]

    def get_active_sell_grids(self) -> list[GridLevel]:
        """売り注文を配置すべきグリッド（ポジション持ち、sell_priceあり）"""
        return [g for g in self.grids if g.position_filled and g.sell_price is not None]

    # ── ポジション管理 ───────────────────────────────────────────────

    def mark_position_filled(self, grid_level: int, order_id: int):
        """買い約定を記録"""
        grid = self._grid_at(grid_level)
        if grid:
            grid.position_filled = True
            grid.buy_order_id = order_id
            logger.info(f"グリッド {grid_level} 買い約定記録: order_id={order_id}")

    def mark_position_closed(self, grid_level: int, order_id: int):
        """売り約定を記録（ポジション解消）"""
        grid = self._grid_at(grid_level)
        if grid:
            grid.position_filled = False
            grid.sell_order_id = order_id
            logger.info(f"グリッド {grid_level} 売り約定記録: order_id={order_id}")

    def _grid_at(self, level: int) -> GridLevel | None:
        """レベル番号からグリッドを取得（O(1)、範囲外はNone）"""
        if 0 <= level < len(self.grids):
            return self.grids[level]
        return None

    # ── グリッドシフト ───────────────────────────────────────────────

    def shift_grids(self, new_lower: float | None = None, new_upper: float | None = None):
        """グリッド範囲をシフト（価格トレンド対応）

        既存のポジションは新しいグリッドに最寄りマッピングで引き継がれます。
        """
        if new_lower is not None and new_upper is not None:
            self.lower_price = new_lower
            self.upper_price = new_upper
        else:
            factor = Settings.GRID_RANGE_FACTOR
            self.lower_price = self.current_price * (1 - factor)
            self.upper_price = self.current_price * (1 + factor)

        logger.info(f"グリッド範囲シフト: {self.lower_price:.2f} - {self.upper_price:.2f}")

        filled_positions = [
            (g.buy_price, g.buy_order_id, g.filled_quantity, g.sell_price)
            for g in self.grids
            if g.position_filled
        ]
        self._calculate_grids()
        if filled_positions:
            self._remap_positions(filled_positions)

    def _remap_positions(self, filled_positions: list[tuple]):
        """シフト前に保存したポジションを新しいグリッドにマッピング"""
        claimed: set[int] = set()
        for buy_price, buy_order_id, filled_quantity, _ in filled_positions:
            available = [g for g in self.grids if g.level not in claimed and not g.position_filled]
            if not available:
                logger.warning("グリッドシフト: 空きグリッド不足、一部ポジションの復元をスキップ")
                break
            best = min(available, key=lambda g: abs(g.buy_price - buy_price))
            best.position_filled = True
            best.buy_order_id = buy_order_id
            best.filled_quantity = filled_quantity
            claimed.add(best.level)
            logger.debug(
                f"ポジションマッピング: 買値{buy_price:.2f} -> "
                f"グリッド{best.level} (買値{best.buy_price:.2f})"
            )
        if claimed:
            logger.info(f"ポジションマッピング完了: {len(claimed)} 件")

    # ── ステータス ─────────────────────────────────────────────────

    @property
    def grid_status(self) -> dict:
        filled = sum(1 for g in self.grids if g.position_filled)
        return {
            "total_grids": len(self.grids),
            "filled_positions": filled,
            "empty_positions": len(self.grids) - filled,
            "current_price": self.current_price,
            "price_range": f"{self.lower_price:.2f} - {self.upper_price:.2f}",
            "grid_spacing": self.grid_spacing,
            "profit_per_grid_percent": self.profit_per_grid_percent,
        }

    def update_current_price(self, price: float):
        self.current_price = price

    def is_within_grid_range(self, price: float) -> bool:
        return self.lower_price <= price <= self.upper_price
