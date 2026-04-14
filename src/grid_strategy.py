"""
ファイルパス: src/grid_strategy.py
概要: グリッド取引戦略
説明: 価格帯を分割し、買い注文と売り注文を配置するグリッド取引ロジックを提供
関連ファイル: src/binance_client.py, src/order_manager.py, config/settings.py
"""

import math
from dataclasses import dataclass
from typing import Optional

from config.settings import Settings
from utils.logger import setup_logger

logger = setup_logger("grid_strategy")


@dataclass
class GridLevel:
    """グリッドレベル（各注文の価格帯）"""

    level: int
    buy_price: float
    sell_price: Optional[float]
    buy_order_id: Optional[int] = None
    sell_order_id: Optional[int] = None
    position_filled: bool = False
    filled_quantity: Optional[float] = None


class GridStrategy:
    """グリッド取引戦略"""

    def __init__(
        self,
        symbol: str,
        current_price: float,
        lower_price: Optional[float] = None,
        upper_price: Optional[float] = None,
        grid_count: Optional[int] = None,
        investment_amount: Optional[float] = None,
    ):
        """
        Args:
            symbol: 取引ペア
            current_price: 現在価格
            lower_price: グリッド下限価格（None の場合自動計算）
            upper_price: グリッド上限価格（None の場合自動計算）
            grid_count: グリッド数
            investment_amount: 投資額
        """
        self.symbol = symbol
        self.current_price = current_price
        self.grid_count = grid_count or Settings.GRID_COUNT
        self.investment_amount = investment_amount or Settings.INVESTMENT_AMOUNT

        if lower_price is not None and upper_price is not None:
            self.lower_price = lower_price
            self.upper_price = upper_price
        else:
            range_factor = Settings.GRID_RANGE_FACTOR
            self.lower_price = current_price * (1 - range_factor)
            self.upper_price = current_price * (1 + range_factor)
            logger.info(f"価格帯を自動設定: {self.lower_price:.2f} - {self.upper_price:.2f}")

        self.grids: list[GridLevel] = []
        self._calculate_grids()

        logger.info(
            f"グリッド戦略初期化: {self.grid_count} グリッド, "
            f"範囲: {self.lower_price:.2f}-{self.upper_price:.2f}, "
            f"間隔: {self.grid_spacing:.2f}"
        )

    @property
    def grid_spacing(self) -> float:
        """グリッド間隔"""
        return (self.upper_price - self.lower_price) / self.grid_count

    @property
    def profit_per_grid_percent(self) -> float:
        """1グリッドあたりの利益率（%）"""
        return (self.grid_spacing / self.lower_price) * 100

    def _calculate_grids(self):
        """グリッドレベルを計算"""
        self.grids = []
        spacing = self.grid_spacing

        for i in range(self.grid_count):
            price = self.lower_price + (spacing * i)
            sell_price = price + spacing if i < self.grid_count - 1 else None
            self.grids.append(
                GridLevel(
                    level=i,
                    buy_price=price,
                    sell_price=sell_price,
                )
            )

        logger.info(f"グリッド計算完了: {len(self.grids)} レベル")

    def get_order_quantity(
        self,
        price: float,
        min_qty: float = 0,
        step_size: float = 0,
        min_notional: float = 0,
    ) -> float:
        """注文数量を計算（投資額を均等分配）

        Args:
            price: 注文価格
            min_qty: 最小注文数量（LOT_SIZE filter）
            step_size: 数量の刻み幅（LOT_SIZE filter）
            min_notional: 最低注文金額（MIN_NOTIONAL filter）
        """
        amount_per_grid = self.investment_amount / self.grid_count
        raw_qty = amount_per_grid / price

        if step_size > 0:
            qty = math.floor(raw_qty / step_size) * step_size
        else:
            qty = raw_qty

        if min_qty > 0 and qty < min_qty:
            logger.warning(f"計算数量 {qty} が最小数量 {min_qty} を下回っています")
            # step_sizeの倍数に丸めて最小数量以上にする
            if step_size > 0:
                qty = math.ceil(min_qty / step_size) * step_size
            else:
                qty = min_qty

        # min_notional チェック（Binanceの最低注文金額）
        if min_notional > 0:
            notional_value = qty * price
            if notional_value < min_notional:
                logger.warning(
                    f"注文金額 {notional_value:.2f} USDT が最低注文金額 "
                    f"{min_notional:.2f} USDT を下回っています。"
                    f"数量を調整します: {qty:.8f} -> {min_notional / price:.8f}"
                )
                adjusted_qty = min_notional / price
                if step_size > 0:
                    adjusted_qty = math.ceil(adjusted_qty / step_size) * step_size
                qty = adjusted_qty

        return qty

    def get_active_buy_grids(self) -> list[GridLevel]:
        """買い注文を配置すべきグリッド（現在価格より下で未約定）"""
        return [
            g for g in self.grids if g.buy_price <= self.current_price and not g.position_filled
        ]

    def get_active_sell_grids(self) -> list[GridLevel]:
        """売り注文を配置すべきグリッド（ポジション持ち）"""
        return [g for g in self.grids if g.position_filled and g.sell_price is not None]

    def mark_position_filled(self, grid_level: int, order_id: int):
        """買い約定を記録"""
        for grid in self.grids:
            if grid.level == grid_level:
                grid.position_filled = True
                grid.buy_order_id = order_id
                logger.info(f"グリッド {grid_level} 買い約定記録: order_id={order_id}")
                break

    def mark_position_closed(self, grid_level: int, order_id: int):
        """売り約定を記録（ポジション解消）"""
        for grid in self.grids:
            if grid.level == grid_level:
                grid.position_filled = False
                grid.sell_order_id = order_id
                logger.info(f"グリッド {grid_level} 売り約定記録: order_id={order_id}")
                break

    @property
    def grid_status(self) -> dict:
        """グリッドのステータスを返す"""
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
        """現在価格を更新"""
        self.current_price = price

    def is_within_grid_range(self, price: float) -> bool:
        """価格がグリッド範囲内か"""
        return self.lower_price <= price <= self.upper_price

    def shift_grids(self, new_lower: Optional[float] = None, new_upper: Optional[float] = None):
        """グリッド範囲をシフト（価格トレンド対応）

        Args:
            new_lower: 新しい下限価格（Noneの場合 current_price から自動計算）
            new_upper: 新しい上限価格（Noneの場合 current_price から自動計算）
        """
        range_factor = Settings.GRID_RANGE_FACTOR

        if new_lower is not None and new_upper is not None:
            self.lower_price = new_lower
            self.upper_price = new_upper
        else:
            self.lower_price = self.current_price * (1 - range_factor)
            self.upper_price = self.current_price * (1 + range_factor)

        logger.info(f"グリッド範囲シフト: {self.lower_price:.2f} - {self.upper_price:.2f}")

        self._calculate_grids()
