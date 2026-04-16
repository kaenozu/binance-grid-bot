"""価格ユーティリティ"""

import math


def adjust_price(price: float, tick_size: float, side: str = "BUY") -> float:
    """価格をtick_sizeの倍数に調整

    BUY: 切り下げ（より低い指値で約定し易く）
    SELL: 切り上げ（より高い指値で約定し易く）

    Args:
        price: 調整前の価格
        tick_size: 価格精度（BinanceのtickSize）
        side: BUY または SELL

    Returns:
        tick_size の倍数に調整された価格。tick_size <= 0 の場合はそのまま返す。
    """
    if tick_size <= 0:
        return price
    if side == "BUY":
        return math.floor(round(price / tick_size, 10)) * tick_size
    return math.ceil(round(price / tick_size, 10)) * tick_size
