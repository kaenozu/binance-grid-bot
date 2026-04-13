"""
ファイルパス: src/grid_strategy.py
概要: グリッド取引戦略
説明: 価格帯を分割し、買い注文と売り注文を配置するグリッド取引ロジックを提供
関連ファイル: src/binance_client.py, src/order_manager.py, config/settings.py
"""

import math
from dataclasses import dataclass, field
from typing import Optional

from config.settings import Settings
from utils.logger import setup_logger

logger = setup_logger("grid_strategy")


@dataclass
class GridLevel:
    """グリッドレベル（各注文の価格帯）"""
    level: int
    buy_price: float
    sell_price: float
    buy_order_id: Optional[int] = None
    sell_order_id: Optional[int] = None
    position_filled: bool = False  # True: 買い約定済み、売り待ち


@dataclass
class GridConfig:
    """グリッド設定"""
    symbol: str
    lower_price: float
    upper_price: float
    grid_count: int
    investment_amount: float
    
    @property
    def grid_spacing(self) -> float:
        """グリッド間隔を計算"""
        return (self.upper_price - self.lower_price) / self.grid_count
    
    @property
    def profit_per_grid(self) -> float:
        """1グリッドあたりの利益率（%）"""
        return (self.grid_spacing / self.lower_price) * 100


class GridStrategy:
    """グリッド取引戦略"""
    
    def __init__(self, symbol: str, current_price: float, 
                 lower_price: Optional[float] = None, 
                 upper_price: Optional[float] = None,
                 grid_count: Optional[int] = None,
                 investment_amount: Optional[float] = None):
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
        
        # 価格帯の決定
        if lower_price and upper_price:
            self.lower_price = lower_price
            self.upper_price = upper_price
        else:
            # 現在価格から自動計算（±10%）
            self.lower_price = current_price * 0.9
            self.upper_price = current_price * 1.1
            logger.info(f"価格帯を自動設定: {self.lower_price:.2f} - {self.upper_price:.2f}")
        
        self.config = GridConfig(
            symbol=symbol,
            lower_price=self.lower_price,
            upper_price=self.upper_price,
            grid_count=self.grid_count,
            investment_amount=self.investment_amount
        )
        
        self.grids: list[GridLevel] = []
        self._calculate_grids()
        
        logger.info(f"グリッド戦略初期化: {self.grid_count} グリッド, "
                   f"範囲: {self.lower_price:.2f}-{self.upper_price:.2f}, "
                   f"間隔: {self.config.grid_spacing:.2f}")
    
    def _calculate_grids(self):
        """グリッドレベルを計算"""
        self.grids = []
        spacing = self.config.grid_spacing
        
        for i in range(self.grid_count + 1):
            price = self.lower_price + (spacing * i)
            grid = GridLevel(
                level=i,
                buy_price=price,
                sell_price=price + spacing if i < self.grid_count else None
            )
            self.grids.append(grid)
        
        logger.info(f"グリッド計算完了: {len(self.grids)} レベル")
    
    def get_order_quantity(self, price: float, min_qty: float = 0, step_size: float = 0) -> float:
        """注文数量を計算（投資額を均等分配）"""
        # 1グリッドあたりの投資額
        amount_per_grid = self.investment_amount / self.grid_count
        
        # 数量計算
        raw_qty = amount_per_grid / price
        
        # 最小数量とステップサイズに合わせる
        if step_size > 0:
            # step_size の倍数に丸める
            qty = math.floor(raw_qty / step_size) * step_size
        else:
            qty = raw_qty
        
        # 最小数量チェック
        if min_qty > 0 and qty < min_qty:
            logger.warning(f"計算数量 {qty} が最小数量 {min_qty} を下回っています")
            qty = min_qty
        
        return qty
    
    def find_nearest_grid(self, price: float) -> Optional[GridLevel]:
        """現在価格に最も近いグリッドレベルを返す"""
        if not self.grids:
            return None
        
        # 価格差が最小のグリッドを探す
        nearest = min(self.grids, key=lambda g: abs(g.buy_price - price))
        return nearest
    
    def get_active_buy_grids(self) -> list[GridLevel]:
        """買い注文を配置すべきグリッドを返す（現在価格より下のグリッド）"""
        return [g for g in self.grids if g.buy_price <= self.current_price and not g.position_filled]
    
    def get_active_sell_grids(self) -> list[GridLevel]:
        """売り注文を配置すべきグリッドを返す（ポジション持ちのグリッド）"""
        return [g for g in self.grids if g.position_filled and g.sell_price]
    
    def mark_position_filled(self, grid_level: int, buy_order_id: int):
        """グリッドの買い約定を記録"""
        for grid in self.grids:
            if grid.level == grid_level:
                grid.position_filled = True
                grid.buy_order_id = buy_order_id
                logger.info(f"グリッド {grid_level} 買い約定記録: order_id={buy_order_id}")
                break
    
    def mark_position_closed(self, grid_level: int, sell_order_id: int):
        """グリッドの売り約定を記録（ポジション解消）"""
        for grid in self.grids:
            if grid.level == grid_level:
                grid.position_filled = False
                grid.sell_order_id = sell_order_id
                logger.info(f"グリッド {grid_level} 売り約定記録: order_id={sell_order_id}")
                break
    
    def calculate_realized_profit(self, buy_price: float, sell_price: float, quantity: float) -> float:
        """実現利益を計算"""
        return (sell_price - buy_price) * quantity
    
    def get_grid_status(self) -> dict:
        """グリッドのステータスを返す"""
        filled = sum(1 for g in self.grids if g.position_filled)
        empty = len(self.grids) - filled
        
        return {
            "total_grids": len(self.grids),
            "filled_positions": filled,
            "empty_positions": empty,
            "current_price": self.current_price,
            "price_range": f"{self.lower_price:.2f} - {self.upper_price:.2f}",
            "grid_spacing": self.config.grid_spacing,
            "profit_per_grid_percent": self.config.profit_per_grid
        }
    
    def update_current_price(self, price: float):
        """現在価格を更新"""
        self.current_price = price
    
    def is_within_grid_range(self, price: float) -> bool:
        """価格がグリッド範囲内かどうかをチェック"""
        return self.lower_price <= price <= self.upper_price
