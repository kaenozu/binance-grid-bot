#!/usr/bin/env python3
"""Test script for grid map alignment"""

from dataclasses import dataclass
from typing import List


@dataclass
class MockGrid:
    buy_price: float
    position_filled: bool = False
    short_position_filled: bool = False


@dataclass
class MockStrategy:
    grids: List[MockGrid]
    lower_price: float
    upper_price: float


def _build_grid_map(strategy: MockStrategy, current_price: float) -> str:
    parts: list[str] = []
    for g in strategy.grids:
        # 状態判定ロジック
        if g.position_filled:
            parts.append("H")
        elif g.short_position_filled:
            parts.append("s")
        else:
            # 価格位置判定
            near = abs(g.buy_price - current_price) / current_price if current_price > 0 else 1
            if near < 0.01:
                parts.append("*")
            else:
                parts.append("_")

    # マーカー位置計算：価格がグリッド範囲内でどこにいるか（0〜len-1）
    grid_count = len(strategy.grids)
    if grid_count > 0:
        lower = strategy.lower_price
        upper = strategy.upper_price
        if upper > lower:
            ratio = (current_price - lower) / (upper - lower)
            marker_idx = int(ratio * grid_count)
            marker_idx = max(0, min(marker_idx, grid_count - 1))
        else:
            marker_idx = 0
    else:
        marker_idx = 0

    row1 = "|" + "".join(parts) + "|"
    # ^ をグリッドの位置に合わせる
    row2 = " " * (marker_idx + 1) + "^" + " " * (grid_count - marker_idx)
    return f"{row1}\n{row2}"


if __name__ == "__main__":
    # Test with 5 grids
    grids = [MockGrid(buy_price=100 + i * 10) for i in range(5)]
    strategy = MockStrategy(grids=grids, lower_price=100, upper_price=140)

    # Test different price positions
    test_prices = [100, 110, 120, 130, 140]
    for price in test_prices:
        print(f"Price: {price}")
        grid_map = _build_grid_map(strategy, price)
        print(grid_map)
        print()
