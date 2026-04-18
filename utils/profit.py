"""利益計算ユーティリティ"""

from config.settings import Settings
from utils.precision import quantize_down, quantize_up


def estimate_cycle_profit(
    current_price: float,
    lower_price: float,
    upper_price: float,
    grid_count: int,
    investment_amount: float,
    fee_rate: float,
) -> float:
    """1往復（BUY→SELL）の概算純利益を返す。

    Args:
        current_price: 現在価格
        lower_price: グリッド下限価格
        upper_price: グリッド上限価格
        grid_count: グリッド数
        investment_amount: 投資額
        fee_rate: 手数料率

    Returns:
        純利益（手数料差引後）
    """
    if current_price <= 0 or grid_count <= 0:
        return 0.0

    amount_per_grid = investment_amount / grid_count
    raw_qty = amount_per_grid / current_price

    # グリッド間隔
    grid_spacing = (upper_price - lower_price) / grid_count

    gross = raw_qty * grid_spacing
    fees = amount_per_grid * (fee_rate * 2)  # 往復手数料
    return gross - fees
