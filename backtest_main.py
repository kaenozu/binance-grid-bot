"""バックテスト実行スクリプト

ファイルの役割: 過去データを使ったバックテストの実行
なぜ存在するか: ユーザーが戦略をテストする入口
関連ファイル: src/backtest.py（バックテストクラス）, src/grid_strategy.py（戦略）
"""

import argparse
import json
import sys

from config.settings import Settings
from src.backtest import BacktestDataFetcher, BacktestEngine
from utils.logger import setup_logger

logger = setup_logger("backtest_main")


def parse_args() -> argparse.Namespace:
    """CLI引数をパース"""
    parser = argparse.ArgumentParser(
        description="グリッド取引ボットのバックテストを実行",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=Settings.TRADING_SYMBOL,
        help="取引ペア",
    )
    parser.add_argument(
        "--grid-count",
        type=int,
        default=Settings.GRID_COUNT,
        help="グリッド数",
    )
    parser.add_argument(
        "--investment",
        type=float,
        default=Settings.INVESTMENT_AMOUNT,
        help="投資額（USDT）",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=Settings.STOP_LOSS_PERCENTAGE,
        help="損切り割合（%%）",
    )
    parser.add_argument(
        "--kline-limit",
        type=int,
        default=720,
        help="K線データ取得件数",
    )
    parser.add_argument(
        "--kline-interval",
        type=str,
        default="1h",
        help="K線時間足",
    )
    return parser.parse_args()


def main():
    """バックテストを実行"""
    args = parse_args()

    print("=" * 60)
    print("バックテスト実行")
    print("=" * 60)
    print()

    symbol = args.symbol
    investment = args.investment
    grid_count = args.grid_count
    stop_loss_percent = args.stop_loss

    print("設定:")
    print(f"  取引ペア: {symbol}")
    print(f"  グリッド数: {grid_count}")
    print(f"  投資額: {investment} USDT")
    print(f"  損切り: {stop_loss_percent}%")
    print()

    # K線データ取得
    print("K線データ取得中...")
    klines = BacktestDataFetcher.fetch_klines(
        symbol, interval=args.kline_interval, limit=args.kline_limit
    )

    if not klines:
        print("エラー: K線データの取得に失敗しました")
        sys.exit(1)

    print(f"  {len(klines)}件のデータを取得")
    print(f"  期間: {klines[0]['open_time']} ~ {klines[-1]['open_time']}")
    print(f"  開始価格: ${klines[0]['close']:,.2f}")
    print(f"  終了価格: ${klines[-1]['close']:,.2f}")
    print()

    # バックテスト実行
    print("バックテスト実行中...")

    engine = BacktestEngine(
        symbol=symbol,
        investment_amount=investment,
        grid_count=grid_count,
        stop_loss_percent=stop_loss_percent,
    )

    report = engine.run(klines)

    if not report:
        print("エラー: バックテストの実行に失敗しました")
        sys.exit(1)

    # 結果表示
    print()
    print("=" * 60)
    print("バックテスト結果")
    print("=" * 60)
    print(f"  取引ペア: {report['symbol']}")
    print(f"  期間: {report['period']}")
    print(f"  データ数: {report['kline_count']}件")
    print("-" * 60)
    print(f"  開始価格: ${report['start_price']:,.2f}")
    print(f"  終了価格: ${report['end_price']:,.2f}")
    print(f"  価格変動: {report['price_change_percent']:+.2f}%")
    print("-" * 60)
    print(f"  グリッド数: {report['grid_count']}")
    print(f"  グリッド範囲: ${report['grid_range']}")
    print("-" * 60)
    print(f"  取引回数: {report['total_trades']}")
    print(f"  総利益: ${report['total_profit']:.2f}")
    print(f"  ROI: {report['roi_percent']:+.2f}%")
    print(f"  最大ドローダウン: {report['max_drawdown_percent']:.2f}%")
    print(f"  損切り発動: {'あり' if report['stop_loss_triggered'] else 'なし'}")
    if report["total_trades"] > 0:
        print(f"  平均利益/取引: ${report['avg_profit_per_trade']:.2f}")
    print("=" * 60)

    # JSONで保存
    output_file = f"backtest_{symbol}_{report['period'].replace(' ', '_').replace(':', '')}.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\n結果を {output_file} に保存しました")
    except Exception as e:
        print(f"\nファイル保存エラー: {e}")


if __name__ == "__main__":
    main()
