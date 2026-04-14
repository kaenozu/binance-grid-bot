"""
ファイルパス: src/bot_display.py
概要: ボットステータス表示
説明: CUIでのステータス表示ロジック
関連ファイル: src/bot.py, src/portfolio.py, src/risk_manager.py
"""

from datetime import datetime


def display_status(symbol: str, current_price: float, grid_status: dict, stats, risk_status: dict):
    """ステータスをCUIに表示"""
    print("\n" + "=" * 70)
    print(f"グリッドボット ステータス - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print(f"取引ペア: {symbol}")
    print(f"現在価格: {current_price:.2f}")
    print(f"価格範囲: {grid_status['price_range']}")
    print(f"グリッド数: {grid_status['total_grids']} (間隔: {grid_status['grid_spacing']:.2f})")
    print(f"ポジション: {grid_status['filled_positions']}/{grid_status['total_grids']}")
    print("-" * 70)
    print(f"初期残高: {stats.initial_balance:.2f} USDT")
    print(f"現在残高: {stats.current_balance:.2f} USDT")
    print(f"実現利益: {stats.realized_profit:+.2f} USDT")
    print(f"未実現利益: {stats.unrealized_profit:+.2f} USDT")
    print(f"累計手数料: {stats.total_fees:.2f} USDT")
    print(f"総利益: {stats.total_profit:+.2f} USDT")
    print("-" * 70)
    print(f"取引回数: {stats.total_trades}")
    print(f"勝率: {stats.win_rate:.1f}%")
    print(f"損切りライン: {risk_status['stop_loss_price']:.2f}")
    print(f"ポジション: {risk_status['current_positions']}/{risk_status['max_positions']}")
    print("=" * 70)
    print("Ctrl+C で停止")
