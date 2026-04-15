"""価格計算ユーティリティ

ファイルの役割: 価格調整・数量計算などのヘルパー関数
なぜ存在するか: 複数モジュールで共有される計算ロジックをまとめため
関連ファイル: src/order_manager.py（注文配置）, src/grid_strategy.py（戦略）
"""

import math


def adjust_price(price: float, tick_size: float, side: str = "BUY") -> float:
    """価格をtick_sizeの倍数に調整（BUY: 切り下げ, SELL: 切り上げ）"""
    if side == "BUY":
        return math.floor(round(price / tick_size, 10)) * tick_size
    return math.ceil(round(price / tick_size, 10)) * tick_size
