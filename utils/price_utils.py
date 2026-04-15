import math

def adjust_price(price: float, tick_size: float, side: str = "BUY") -> float:
    """価格をtick_sizeの倍数に調整（BUY: 切り下げ, SELL: 切り上げ）"""
    if side == "BUY":
        return math.floor(price / tick_size) * tick_size
    return math.ceil(price / tick_size) * tick_size
