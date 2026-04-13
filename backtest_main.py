"""
ファイルパス: backtest_main.py
概要: バックテスト実行スクリプト
説明: 過去の価格データを取得し、グリッド戦略のシミュレーションを実行
関連ファイル: src/backtest.py, config/settings.py
"""

import sys
import json

from config.settings import Settings
from src.backtest import BacktestDataFetcher, BacktestEngine
from utils.logger import setup_logger

logger = setup_logger("backtest_main")


def main():
    """バックテストを実行"""
    print("=" * 60)
    print("バックテスト実行")
    print("=" * 60)
    print()
    
    symbol = Settings.TRADING_SYMBOL
    investment = Settings.INVESTMENT_AMOUNT
    grid_count = Settings.GRID_COUNT
    
    # 引数で設定を上書き可能
    if len(sys.argv) > 1:
        symbol = sys.argv[1]
    if len(sys.argv) > 2:
        grid_count = int(sys.argv[2])
    if len(sys.argv) > 3:
        investment = float(sys.argv[3])
    
    print(f"設定:")
    print(f"  取引ペア: {symbol}")
    print(f"  グリッド数: {grid_count}")
    print(f"  投資額: {investment} USDT")
    print()
    
    # K線データ取得（1時間足、720件 = 約30日分）
    print("K線データ取得中...")
    klines = BacktestDataFetcher.fetch_klines(symbol, interval="1h", limit=720)
    
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
        lower_price=klines[0]["close"] * 0.85,
        upper_price=klines[0]["close"] * 1.15,
        stop_loss_percent=15.0  # バックテストでは広めに
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
    if report['total_trades'] > 0:
        print(f"  平均利益/取引: ${report['avg_profit_per_trade']:.2f}")
    print("=" * 60)
    
    # JSONで保存
    output_file = f"backtest_{symbol}_{report['period'].replace(' ', '_').replace(':', '')}.json"
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\n結果を {output_file} に保存しました")
    except Exception as e:
        print(f"\nファイル保存エラー: {e}")


if __name__ == "__main__":
    main()
