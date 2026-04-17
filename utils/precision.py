"""精度計算ユーティリティ

ファイルの役割: 浮動小数点の丸め誤差を防ぐため、Decimal を使用した共通精度処理を提供
なぜ存在するか: Binance API の priceFilter/lotSize 制約に厳密に従うため
関連ファイル: binance_client.py, order_manager.py, grid_strategy.py
"""

from decimal import ROUND_DOWN, ROUND_UP, Decimal, InvalidOperation


def get_precision(value: float) -> int:
    """float から小数点以下の桁数を算出"""
    if value <= 0:
        return 0
    try:
        normalized = Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError):
        return 0
    exponent = normalized.as_tuple().exponent
    return max(0, -exponent)


def quantize_down(value: float, increment: float) -> float:
    """increment の倍数に切り下げる"""
    if increment <= 0:
        return value
    d_value = Decimal(str(value))
    d_inc = Decimal(str(increment))
    result = (d_value // d_inc) * d_inc
    return float(result)


def quantize_up(value: float, increment: float) -> float:
    """increment の倍数に切り上げる"""
    if increment <= 0:
        return value
    d_value = Decimal(str(value))
    d_inc = Decimal(str(increment))
    if d_value % d_inc == 0:
        return float(d_value)
    result = ((d_value // d_inc) + Decimal(1)) * d_inc
    return float(result)


def quantize(value: float, increment: float, rounding: str = "down") -> float:
    """increment の倍数に丸める

    Args:
        value: 丸め対象の値
        increment: 丸め単位（tick_size, step_size）
        rounding: "down" or "up"
    """
    if rounding == "up":
        return quantize_up(value, increment)
    return quantize_down(value, increment)


def format_decimal(value: float, precision: int) -> str:
    """指定精度でフォーマット（末尾の0を削除）"""
    formatted = f"{Decimal(str(value)):.{precision}f}"
    return str(formatted)
