"""
ファイルパス: main.py
概要: グリッド取引ボット エントリーポイント
説明: ボットを起動するためのメインスクリプト
関連ファイル: src/bot.py, config/settings.py
"""

import argparse
import os
import sys

from config.settings import Settings
from utils.logger import setup_logger

logger = setup_logger("main")

DB_PATH = os.path.join("data", "bot_state.db")


def _reset_db():
    """DBとエクスポートを削除"""
    removed = []
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        removed.append(DB_PATH)
    export_dir = os.path.join("data", "exports")
    if os.path.isdir(export_dir):
        for f in os.listdir(export_dir):
            fp = os.path.join(export_dir, f)
            os.remove(fp)
            removed.append(fp)
    if removed:
        print(f"削除完了:")
        for r in removed:
            print(f"  - {r}")
    else:
        print("削除対象なし（DBは既にクリーン）")


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description="Binance グリッド取引ボット")
    parser.add_argument("--reset", action="store_true", help="DBとトレード履歴を初期化して起動")
    parser.add_argument("--reset-only", action="store_true", help="DB初期化のみ（起動しない）")
    args = parser.parse_args()

    if args.reset or args.reset_only:
        print("DB初期化...")
        _reset_db()
        if args.reset_only:
            sys.exit(0)
        print()

    print("=" * 60)
    print("Binance グリッド取引ボット")
    print("=" * 60)
    print()

    print("設定確認:")
    print(f"  取引ペア: {Settings.TRADING_SYMBOL}")
    print(f"  グリッド数: {Settings.GRID_COUNT}")
    print(f"  投資額: {Settings.INVESTMENT_AMOUNT} USDT")
    print(f"  損切り: {Settings.STOP_LOSS_PERCENTAGE}%")
    print(f"  Testnet: {'Yes' if Settings.USE_TESTNET else 'No (Production)'}")
    print()

    if not Settings.USE_TESTNET:
        print("警告: 本番モードで実行します")
        if not sys.stdin.isatty():
            print("非対話環境のため本番モードを中止します")
            sys.exit(1)
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
