"""手数料計算

ファイルの役割: 取引手数料差し引き後の純利益計算
なぜ存在するか: 正確な損益把握のため
関連ファイル: portfolio.py（統計）, settings.py（設定）
"""


def calculate_net_profit(
    buy_price: float, sell_price: float, quantity: float, fee_rate: float
) -> tuple[float, float, float]:
    """純利益と各手数料を計算

    Returns:
        (net_profit, buy_fee, sell_fee)
    """
    gross_profit = (sell_price - buy_price) * quantity
    buy_fee = buy_price * quantity * fee_rate
    sell_fee = sell_price * quantity * fee_rate
    return gross_profit - buy_fee - sell_fee, buy_fee, sell_fee
