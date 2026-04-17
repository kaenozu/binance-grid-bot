"""ポートフォリオレポート生成

ファイルの役割: ポートフォリオの終了時レポートを生成
なぜ存在するか: レポート表示ロジックを portfolio.py から分離するため
関連ファイル: portfolio.py（統計データ）, bot.py（呼び出し元）
"""

from datetime import datetime

from src.portfolio import Portfolio


def generate_portfolio_report(portfolio: Portfolio) -> str:
    """ポートフォリオレポートを生成

    Args:
        portfolio: Portfolio インスタンス

    Returns:
        フォーマット済みレポート文字列
    """
    stats = portfolio.stats
    q = portfolio.quote_asset
    elapsed = datetime.now() - stats.start_time if stats.start_time else None
    hours = elapsed.total_seconds() / 3600 if elapsed else 0

    monthly_lines = _format_periodic_profit(stats.monthly_profit, limit=6)
    yearly_lines = _format_periodic_profit(stats.yearly_profit, limit=3)

    return (
        f"\n"
        f"===== ポートフォリオレポート =====\n"
        f"実行時間: {hours:.2f} 時間\n"
        f"初期残高: {stats.initial_balance:.2f} {q}\n"
        f"現在残高: {stats.current_balance:.2f} {q}\n"
        f"--------------------------------\n"
        f"実現利益: {stats.realized_profit:+.2f} {q}\n"
        f"未実現利益: {stats.unrealized_profit:+.2f} {q}\n"
        f"総利益: {stats.total_profit:+.2f} {q}\n"
        f"--------------------------------\n"
        f"取引回数: {stats.total_trades}\n"
        f"勝率: {stats.win_rate:.1f}%\n"
        f"平均利益/取引: {stats.avg_profit_per_trade:+.2f} {q}\n"
        f"--------------------------------\n"
        f"===== リスク指標 =====\n"
        f"ピーク残高: {stats.peak_balance:.2f} {q}\n"
        f"最大ドローダウン: {stats.max_drawdown:.2f} {q}\n"
        f"  ({stats.max_drawdown_pct:.2f}%)\n"
        f"シャープレシオ: {stats.sharpe_ratio:.2f}\n"
        f"--------------------------------\n"
        f"===== 月次利益 =====\n{monthly_lines}\n"
        f"===== 年次利益 =====\n{yearly_lines}\n"
        f"================================"
    )


def _format_periodic_profit(data: dict[str, float], limit: int) -> str:
    """月次/年次利益をフォーマット"""
    if not data:
        return "  (取引なし)"
    items = sorted(data.items(), reverse=True)[:limit]
    return "\n".join(f"  {k}: {v:+.2f}" for k, v in items)
