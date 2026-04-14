"""
ファイルパス: src/fee.py
概要: 手数料計算ユーティリティ
説明: 買い/売りの手数料を差し引いた純利益を計算
関連ファイル: src/portfolio.py, src/backtest.py
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
