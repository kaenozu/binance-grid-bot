"""全資産をJPYに換えるスクリプト"""

from src.binance_client import BinanceClient
from utils.precision import quantize_down


def convert_all_to_jpy():
    client = BinanceClient()
    balances = client.get_account_balance()

    jpy_before = float(balances.get("JPY", {}).get("free", 0))
    print(f"変換前 JPY: {jpy_before:.2f}")

    sold_count = 0
    total_jpy = 0

    for asset, data in balances.items():
        if asset in ("JPY", "BNB"):  # JPYは変換不要、BNBは保有
            continue

        free = float(data.get("free", 0))
        if free <= 0:
            continue

        # シンボル取得尝试 (例: SOL -> SOLJPY)
        symbol = f"{asset}JPY"
        try:
            symbol_info = client.get_symbol_info(symbol)
        except:
            continue

        if not symbol_info:
            continue

        step_size = float(symbol_info.get("step_size", 0))
        qty = quantize_down(free, step_size)

        if qty <= 0:
            continue

        try:
            price = client.get_symbol_price(symbol)
            order = client.place_order(symbol, "SELL", qty, None)
            jpy_earned = float(order.get("cummulativeQuoteQty", 0))
            total_jpy += jpy_earned
            sold_count += 1
            print(f"  売却: {qty} {asset} -> {jpy_earned:.2f} JPY")
        except Exception as e:
            print(f"  失敗: {asset} ({e})")

    balances = client.get_account_balance()
    jpy_after = float(balances.get("JPY", {}).get("free", 0))

    print(f"\n変換後 JPY: {jpy_after:.2f}")
    print(f"増分: {jpy_after - jpy_before:.2f} JPY")
    print(f"売却枚数: {sold_count}")


if __name__ == "__main__":
    print("========================================")
    print("全資産をJPYに換えるスクリプト")
    print("========================================")
    print()
    confirm = input("実行しますか？ (Y/N): ")
    if confirm.upper() != "Y":
        print("キャンセルしました")
    else:
        convert_all_to_jpy()
