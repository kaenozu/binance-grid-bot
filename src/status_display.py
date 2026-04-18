"""ステータス表示

ファイルの役割: ボットのステータスをログ出力する
なぜ存在するか: 表示ロジックを bot.py から分離するため
関連ファイル: bot.py（呼び出し元）, grid_strategy.py（戦略）, portfolio.py（統計）
"""

from datetime import datetime

from src.grid_strategy import GridStrategy
from src.portfolio import Portfolio
from src.risk_manager import RiskManager
from utils.logger import setup_logger

logger = setup_logger("status_display")


def get_summary(
    is_running: bool,
    current_price: float,
    strategy: GridStrategy,
    portfolio: Portfolio,
) -> dict:
    """集約ステータスを返す"""
    portfolio.set_current_price(current_price)
    stats = portfolio.refresh_stats()
    filled = sum(1 for g in strategy.grids if g.position_filled)
    return {
        "running": is_running,
        "price": current_price,
        "grids": len(strategy.grids),
        "filled": filled,
        "total_profit": stats.total_profit,
        "realized_profit": stats.realized_profit,
        "unrealized_profit": stats.unrealized_profit,
    }


def display_status(
    symbol: str,
    current_price: float,
    strategy: GridStrategy,
    portfolio: Portfolio,
    risk_manager: RiskManager,
    detail: bool = False,
):
    """ステータスを表示（detail=Trueで詳細版）"""
    portfolio.set_current_price(current_price)
    stats = portfolio.refresh_stats()
    filled = sum(1 for g in strategy.grids if g.position_filled)
    logger.info(f"価格={current_price:.2f} ポジション={filled} 利益={stats.total_profit:+.2f}")
    if not detail:
        return
    _display_detail(symbol, current_price, strategy, portfolio, risk_manager)


def _display_detail(
    symbol: str,
    current_price: float,
    strategy: GridStrategy,
    portfolio: Portfolio,
    risk_manager: RiskManager,
):
    gs = strategy.grid_status
    rs = risk_manager.risk_status
    q = portfolio.quote_asset
    stats = portfolio.stats
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "",
        "=" * 70,
        f"グリッドボット ステータス - {now_str}",
        "=" * 70,
        f"取引ペア: {symbol}",
        f"現在価格: {current_price:.2f}",
        f"価格範囲: {gs['price_range']}",
        f"グリッド数: {gs['total_grids']} (間隔: {gs['grid_spacing']:.2f})",
        f"ポジション: {gs['filled_positions']}/{gs['total_grids']}",
        "-" * 70,
        f"初期残高: {stats.initial_balance:.2f} {q}",
        f"現在残高: {stats.current_balance:.2f} {q}",
        f"実現利益: {stats.realized_profit:+.2f} {q}",
        f"未実現利益: {stats.unrealized_profit:+.2f} {q}",
        f"累計手数料: {stats.total_fees:.2f} {q}",
        f"総利益: {stats.total_profit:+.2f} {q}",
        f"最大ドローダウン: {stats.max_drawdown_pct:.2f}%",
        "-" * 70,
        f"取引回数: {stats.total_trades}",
        f"勝率: {stats.win_rate:.1f}%",
        f"損切りライン: {rs['stop_loss_price']:.2f}",
        f"ポジション: {rs['current_positions']}/{rs['max_positions']}",
        "=" * 70,
        "Ctrl+C で停止",
    ]
    logger.info("\n".join(lines))
