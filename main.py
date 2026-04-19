"""グリッド取引ボット エントリーポイント

ファイルの役割: コマンドライン引数の解析・ ボットの起動
なぜ存在するか: ユーザーがボットを起動する入口
関連ファイル: src/bot.py（ボットクラス）, config/settings.py（設定）, config/presets.py（プリセット）
"""

import argparse
import os
import signal
import sys

from config.settings import Settings
from utils.logger import setup_logger

logger = setup_logger("main")


class _ShutdownGuard:
    """SIGTERM/SIGINT 受信時にボットをグレースフルシャットダウン"""

    def __init__(self):
        self._bot = None

    def register(self, bot):
        self._bot = bot

    def handle(self, signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"{sig_name} 受信。グレースフルシャットダウン開始...")
        if self._bot is not None:
            self._bot.stop()
        sys.exit(0)


def _get_data_paths() -> list[str]:
    """DBとエクスポートのパスを収集"""
    from src.persistence import DB_PATH

    paths = []
    db_str = str(DB_PATH)
    for suffix in ("", "-shm", "-wal"):
        p = db_str + suffix
        if os.path.exists(p):
            paths.append(p)
    export_dir = os.path.join("data", "exports")
    if os.path.isdir(export_dir):
        for f in os.listdir(export_dir):
            fp = os.path.join(export_dir, f)
            if os.path.isfile(fp):
                paths.append(fp)
    return paths


def _reset_db():
    """DBとエクスポートを削除"""
    from src.persistence import _reset_connection

    _reset_connection()
    import gc

    gc.collect()
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
    """本番モードの確認（対話・環境変数の両方に対応）"""
    if Settings.USE_TESTNET:
        return

    if os.getenv("CONFIRM_PRODUCTION") == "true":
        logger.warning("本番モード: CONFIRM_PRODUCTION=true により実行を許可")
        return

    print("警告: 本番モードで実行します（実際の資金が使用されます）")
    if not sys.stdin.isatty():
        print(
            "非対話環境です。環境変数 CONFIRM_PRODUCTION=true を設定するか、"
            "対話的なターミナルから実行してください。"
        )
        sys.exit(1)
    # input("【警告】本番環境で実行します（実際の資金が使用されます）。ENTERキーを押すと開始します...")


def _signal_handler(signum, frame):
    """SIGTERM/SIGINT でグレースフルシャットダウン"""
    sig_name = signal.Signals(signum).name
    logger.info(f"{sig_name} 受信。グレースフルシャットダウン開始...")
    if _guard._bot is not None:
        _guard._bot.stop()
    sys.exit(0)


_guard = _ShutdownGuard()


def _show_presets():
    """利用可能なプリセット一覧を表示"""
    from config.presets import PRESETS, MULTI_PRESETS

    print("=" * 70)
    print("利用可能なプリセット一覧")
    print("=" * 70)
    print()

    risk_labels = {"low": "[低リスク]", "medium": "[中リスク]", "high": "[高リスク]"}

    # シングルペア
    print("【シングルペア】")
    print("-" * 70)
    for key, p in PRESETS.items():
        risk = risk_labels.get(p.risk_level, p.risk_level)
        print(f"  {key}:")
        print(f"    {p.name} ({p.symbol})")
        print(f"    {p.description}")
        print(
            f"    グリッド数={p.grid_count}, レンジ=±{p.grid_range_factor * 100:.0f}%, "
            f"投資額={p.investment_amount} USDT"
        )
        print(
            f"    損切り={p.stop_loss_percentage}%, "
            f"最大DD={p.max_drawdown_pct}%, "
            f"最低資金={p.min_capital} USDT"
        )
        print(f"    {risk} | 推定日次リターン: ~{p.expected_daily_return_pct:.2f}%")
        print()

    # マルチペア
    print("【マルチペア（--multi で使用）")
    print("-" * 70)
    for key, cfg in MULTI_PRESETS.items():
        print(f"  {key}: {cfg['name']}")
        print(f"    {cfg['description']}")
        print(f"    ペア: {', '.join(cfg['symbols'])}")
        print(f"    総投資額: {cfg['total_investment_usdt']} USDT")
        alloc_str = ", ".join(f"{k}: {v}" for k, v in cfg['allocation'].items())
        print(f"    配分: {alloc_str}")
        print()

    print("使用例:")
    print("  python main.py --preset eth-balanced")
    print("  python main.py --preset sol-aggressive --reset")
    print("  python main.py --recommend 300")
    print("  python main.py --multi ETHUSDT,SOLUSDT")


def _show_recommendations(capital_usdt: float):
    """資金額に基づく推奨プリセットを表示"""
    from config.presets import recommend_for_capital

    print("=" * 60)
    print(f"資金 {capital_usdt:.0f} USDT に最適なプリセット")
    print("=" * 60)
    print()

    recommended = recommend_for_capital(capital_usdt)
    if not recommended:
        print(f"  {capital_usdt:.0f} USDT で利用可能なプリセットがありません。")
        print("  最低 30 USDT から始められます（xrp-micro / doge-micro）。")
        return

    risk_labels = {"low": "[低]", "medium": "[中]", "high": "[高]"}
    from config.presets import PRESETS
    preset_keys = {id(v): k for k, v in PRESETS.items()}
    for i, p in enumerate(recommended[:5], 1):
        risk = risk_labels.get(p.risk_level, p.risk_level)
        coverage = capital_usdt / p.investment_amount * 100
        pkey = preset_keys.get(id(p), "?")
        print(f"  {i}. --preset {pkey}")
        print(f"     {p.name} ({p.symbol}) [{risk}リスク]")
        print(f"     投資額={p.investment_amount} USDT (資金の{coverage:.0f}%)")
        print(f"     グリッド数={p.grid_count}, レンジ=±{p.grid_range_factor * 100:.0f}%")
        print(f"     推定日次リターン: ~{p.expected_daily_return_pct:.2f}%")
        print()


def _apply_preset(preset_name: str):
    """プリセット設定をSettingsに適用"""
    from config.presets import get_preset

    preset = get_preset(preset_name)
    if not preset:
        print(f"エラー: プリセット '{preset_name}' が見つかりません")
        print("利用可能なプリセットを確認: python main.py --list-presets")
        sys.exit(1)

    # Settings クラスのクラス変数を直接更新
    from config.settings import Settings

    Settings.TRADING_SYMBOL = preset.symbol
    Settings.GRID_COUNT = preset.grid_count
    Settings.GRID_RANGE_FACTOR = preset.grid_range_factor
    Settings.INVESTMENT_AMOUNT = preset.investment_amount
    Settings.STOP_LOSS_PERCENTAGE = preset.stop_loss_percentage
    Settings.MAX_DRAWDOWN_PCT = preset.max_drawdown_pct
    Settings.MAX_POSITIONS = preset.max_positions
    Settings.TRADING_FEE_RATE = preset.trading_fee_rate

    print(f"プリセット適用: {preset.name} ({preset.symbol})")
    print(f"  グリッド数: {preset.grid_count}")
    print(f"  レンジ: ±{preset.grid_range_factor * 100:.0f}%")
    print(f"  投資額: {preset.investment_amount} USDT")
    print(f"  損切り: {preset.stop_loss_percentage}%")
    print(f"  リスク: {preset.risk_level}")
    print()


def main():
    """メイン関数"""
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    parser = argparse.ArgumentParser(description="Binance グリッド取引ボット")
    parser.add_argument("--reset", action="store_true", help="DBとトレード履歴を初期化して起動")
    parser.add_argument("--reset-only", action="store_true", help="DB初期化のみ（起動しない）")
    parser.add_argument(
        "--multi",
        type=str,
        default=None,
        help="マルチボットモード (例: --multi ETHUSDT,BNBUSDT)",
    )
    parser.add_argument(
        "--preset",
        type=str,
        default=None,
        help=(
            "プリセット設定を使用 (例: --preset eth-balanced)。"
            "利用可能なプリセットは --list-presets で確認できます。"
        ),
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help="利用可能なプリセット一覧を表示",
    )
    parser.add_argument(
        "--recommend",
        type=float,
        default=None,
        metavar="CAPITAL_USDT",
        help="指定USDT額に最適なプリセットを推奨 (例: --recommend 300)",
    )
    args = parser.parse_args()

    # ── プリセット一覧表示 ──
    if args.list_presets:
        _show_presets()
        sys.exit(0)

    # ── 資金額に基づく推奨 ──
    if args.recommend is not None:
        _show_recommendations(args.recommend)
        sys.exit(0)

    # ── プリセット適用 ──
    if args.preset:
        _apply_preset(args.preset)

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
            _guard.register(mb)
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
        print(f"  最大ドローダウン: {Settings.MAX_DRAWDOWN_PCT}%")
        print(f"  Testnet: {'Yes' if Settings.USE_TESTNET else 'No (Production)'}")
        print()

        _confirm_production_mode()

        print("ボットを起動中...")
        print()

        try:
            from src.bot import GridBot

            bot = GridBot()
            _guard.register(bot)
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
