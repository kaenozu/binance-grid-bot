"""
ファイルパス: main.py
概要: グリッド取引ボット エントリーポイント
説明: ボットを起動するためのメインスクリプト
関連ファイル: src/bot.py, config/settings.py
"""

import sys

from config.settings import Settings
from utils.logger import setup_logger

logger = setup_logger("main")


def main():
    """メイン関数"""
    print("=" * 60)
    print("Binance グリッド取引ボット")
    print("=" * 60)
    print()
    
    # 設定確認
    print("設定確認:")
    print(f"  取引ペア: {Settings.TRADING_SYMBOL}")
    print(f"  グリッド数: {Settings.GRID_COUNT}")
    print(f"  投資額: {Settings.INVESTMENT_AMOUNT} USDT")
    print(f"  損切り: {Settings.STOP_LOSS_PERCENTAGE}%")
    print(f"  Testnet: {'Yes' if Settings.USE_TESTNET else 'No (Production)'}")
    print()
    
    # Testnet警告
    if not Settings.USE_TESTNET:
        print("警告: 本番モードで実行します")
        confirm = input("続行しますか？ (yes/no): ").strip().lower()
        if confirm != "yes":
            print("中止しました")
            sys.exit(0)
    
    print("ボットを起動中...")
    print()
    
    try:
        from src.bot import GridBot
        bot = GridBot()
        bot.start()
    except ValueError as e:
        logger.error(f"ボット初期化失敗: {e}")
        print(f"\nエラー: {e}")
        print("設定ファイル (.env) を確認してください")
        sys.exit(1)
    except Exception as e:
        logger.error(f"予期せぬエラー: {e}", exc_info=True)
        print(f"\n予期せぬエラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
