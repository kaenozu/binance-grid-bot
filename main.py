"""グリッド取引ボット エントリーポイント

ファイルの役割: コマンドライン引数の解析・ ボットの起動
なぜ存在するか: ユーザーがボットを起動する入口
関連ファイル: src/bot.py（ボットクラス）, config/settings.py（設定）
"""

import argparse
import os
import sys

from config.settings import Settings
from utils.logger import setup_logger

logger = setup_logger("main")


def _get_data_paths() -> list[str]:
    """DBとエクスポートのパスを収集"""
    from src.persistence import DB_PATH

    paths = []
    if os.path.exists(DB_PATH):
        paths.append(str(DB_PATH))
    export_dir = os.path.join("data", "exports")
    if os.path.isdir(export_dir):
        for f in os.listdir(export_dir):
            fp = os.path.join(export_dir, f)
            if os.path.isfile(fp):
                paths.append(fp)
    return paths


def _reset_db():
    """DBとエクスポートを削除"""
    removed = _get_data_paths()
    for p in removed:
        os.remove(p)
    if removed:
        print("削除完了:")
        for r in removed:
            print(f"  - {r}")
    else:
        print("削除対象なし（DBは既にクリーン）")


def _confirm_production_mode():
    """本番モードの確認"""
    if Settings.USE_TESTNET:
        return
    print("警告: 本番モードで実行します")
    if not sys.stdin.isatty():
        print("非対話環境のため本番モードを中止します")
        sys.exit(1)
    confirm = input("続行しますか？ (yes/no): ").strip().lower()
    if confirm != "yes":
        print("中止しました")
        sys.exit(0)


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description="Binance グリッド取引ボット")
    parser.add_argument("--reset", action="store_true", help="DBとトレード履歴を初期化して起動")
    parser.add_argument("--reset-only", action="store_true", help="DB初期化のみ（起動しない）")
    parser.add_argument(
        "--multi",
        type=str,
        default=None,
        help="マルチボットモード (例: --multi ETHUSDT,BNBUSDT)",
    )
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

    if args.multi:
        symbols = [s.strip().upper() for s in args.multi.split(",") if s.strip()]
        if not symbols:
            print("エラー: --multi にシンボルを指定してください (例: --multi ETHUSDT,BNBUSDT)")
            sys.exit(1)

        print(f"マルチボットモード: {', '.join(symbols)}")
        print()

        _confirm_production_mode()

        print("ボットを起動中...")
        print()

        try:
            from src.api_weight import APIWeightTracker
            from src.multi_bot import MultiBot

            tracker = APIWeightTracker()
            mb = MultiBot(symbols=symbols, weight_tracker=tracker)
            mb.start_all()
        except Exception as e:
            logger.error(f"マルチボット起動失敗: {e}", exc_info=True)
            print(f"\n予期せぬエラー: {e}")
            sys.exit(1)
    else:
        print("設定確認:")
        print(f"  取引ペア: {Settings.TRADING_SYMBOL}")
        print(f"  グリッド数: {Settings.GRID_COUNT}")
        print(f"  投資額: {Settings.INVESTMENT_AMOUNT} USDT")
        print(f"  損切り: {Settings.STOP_LOSS_PERCENTAGE}%")
        print(f"  Testnet: {'Yes' if Settings.USE_TESTNET else 'No (Production)'}")
        print()

        _confirm_production_mode()

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
