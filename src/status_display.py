"""ステータス表示

ファイルの役割: ボットのステータスをログ出力する
なぜ存在するか: 表示ロジックを bot.py から分離するため
関連ファイル: bot.py（呼び出し元）, grid_strategy.py（戦略）, portfolio.py（統計）
"""

from datetime import datetime
from typing import TYPE_CHECKING

from src.grid_strategy import GridStrategy
from src.portfolio import Portfolio
from src.risk_manager import RiskManager
from utils.logger import setup_logger

if TYPE_CHECKING:
    from src.order_manager import OrderManager

logger = setup_logger("status_display")


def get_summary(
    is_running: bool,
    current_price: float,
    strategy: GridStrategy,
    portfolio: Portfolio,
) -> dict:
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
    order_manager: "OrderManager | None" = None,
    start_time: float | None = None,
    dynamic_factor: float | None = None,
    ws_connected: bool | None = None,
):
    print("\n" + "=" * 60)
    print(f"グリッドボット ステータス - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    portfolio.set_current_price(current_price)
    stats = portfolio.refresh_stats()
    filled = sum(1 for g in strategy.grids if g.position_filled)
    short_filled = sum(1 for g in strategy.grids if g.short_position_filled)
    q = portfolio.quote_asset

    active_orders = {}
    if order_manager:
        active_orders = order_manager.active_orders
    buy_pending = sum(1 for o in active_orders.values() if o.side == "BUY" and o.status != "FILLED")
    sell_pending = sum(
        1 for o in active_orders.values() if o.side == "SELL" and o.status != "FILLED"
    )

    uptime_str = ""
    if start_time and start_time > 0:
        elapsed = datetime.now().timestamp() - start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        uptime_str = f" 稼働={hours}h{minutes}m"

    grid_map = _build_grid_map(strategy, current_price)

    profit_per_hour = 0.0
    if start_time and start_time > 0 and stats.realized_profit != 0:
        elapsed_h = (datetime.now().timestamp() - start_time) / 3600
        if elapsed_h > 0:
            profit_per_hour = stats.realized_profit / elapsed_h

    ws_str = ""
    if ws_connected is not None:
        ws_str = " WS=OK" if ws_connected else " WS=NG"

    factor_str = ""
    if dynamic_factor is not None:
        factor_str = f" factor={dynamic_factor:.4f}"

    logger.info(
        f"価格={current_price:.2f} ポジション={filled}/{len(strategy.grids)}"
        f" ショート={short_filled}"
        f" 注文(BUY={buy_pending} SELL={sell_pending})"
        f" 利益={stats.realized_profit:+.2f}{q}"
        f" 未実現={stats.unrealized_profit:+.2f}{q}"
        f"{uptime_str}{ws_str}"
    )
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"価格={current_price:.2f} 利益={stats.realized_profit:+.2f}{q} "
        f"未実現={stats.unrealized_profit:+.2f}{q}"
    )
    # インデントなしで出力
    logger.info(f"グリッド図:\n{grid_map}")

    if stats.total_trades > 0 and profit_per_hour != 0:
        logger.info(
            f"取引={stats.total_trades}件 勝率={stats.win_rate:.0f}%"
            f" ペース={profit_per_hour:+.2f}{q}/h"
            f"{factor_str}"
        )

    if not detail:
        return
    _display_detail(
        symbol,
        current_price,
        strategy,
        portfolio,
        risk_manager,
        order_manager=order_manager,
        start_time=start_time,
        dynamic_factor=dynamic_factor,
        ws_connected=ws_connected,
        grid_map=grid_map,
        profit_per_hour=profit_per_hour,
    )


def _build_grid_map(strategy: GridStrategy, current_price: float) -> str:
    parts: list[str] = []
    for g in strategy.grids:
        # 状態判定ロジック
        if g.position_filled:
            parts.append("H")
        elif g.short_position_filled:
            parts.append("s")
        else:
            # 価格位置判定
            near = abs(g.buy_price - current_price) / current_price if current_price > 0 else 1
            if near < 0.01:
                parts.append("*")
            else:
                parts.append("_")

    # マーカー位置計算：価格がグリッド範囲内でどこにいるか（0〜len-1）
    grid_count = len(strategy.grids)
    if grid_count > 0:
        lower = strategy.lower_price
        upper = strategy.upper_price
        if upper > lower:
            ratio = (current_price - lower) / (upper - lower)
            marker_idx = int(ratio * grid_count)
            marker_idx = max(0, min(marker_idx, grid_count - 1))
        else:
            marker_idx = 0
    else:
        marker_idx = 0

    row1 = "|" + "".join(parts) + "|"
    # ^ をグリッドの位置に合わせる
    row2 = " " * (marker_idx + 1) + "^" + " " * (grid_count - marker_idx)
    return f"{row1}\n{row2}"


def _price_marker_index(strategy: GridStrategy, current_price: float) -> int:
    if not strategy.grids:
        return 0
    lower = strategy.lower_price
    upper = strategy.upper_price
    if upper <= lower:
        return 0
    ratio = (current_price - lower) / (upper - lower)
    idx = int(ratio * len(strategy.grids))
    return max(0, min(idx, len(strategy.grids) - 1))


def _display_detail(
    symbol: str,
    current_price: float,
    strategy: GridStrategy,
    portfolio: Portfolio,
    risk_manager: RiskManager,
    order_manager: "OrderManager | None" = None,
    start_time: float | None = None,
    dynamic_factor: float | None = None,
    ws_connected: bool | None = None,
    grid_map: str = "",
    profit_per_hour: float = 0.0,
):
    gs = strategy.grid_status
    rs = risk_manager.risk_status
    q = portfolio.quote_asset
    stats = portfolio.stats
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    active_orders = {}
    if order_manager:
        active_orders = order_manager.active_orders
    buy_pending = sum(1 for o in active_orders.values() if o.side == "BUY" and o.status != "FILLED")
    sell_pending = sum(
        1 for o in active_orders.values() if o.side == "SELL" and o.status != "FILLED"
    )
    short_filled = sum(1 for g in strategy.grids if g.short_position_filled)

    uptime_str = ""
    if start_time and start_time > 0:
        elapsed = datetime.now().timestamp() - start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        uptime_str = f"{hours}h{minutes}m"

    ws_str = ""
    if ws_connected is not None:
        ws_str = "OK" if ws_connected else "NG"

    lines = [
        "",
        "=" * 70,
        f"グリッドボット ステータス - {now_str}",
        "=" * 70,
        f"取引ペア: {symbol}",
        f"現在価格: {current_price:.2f} {q}",
        f"価格範囲: {gs['price_range']}",
        f"グリッド数: {gs['total_grids']} (間隔: {gs['grid_spacing']:.2f})"
        + (f" factor={dynamic_factor:.4f}" if dynamic_factor else ""),
        f"ポジション: {gs['filled_positions']}/{gs['total_grids']} (ショート={short_filled})",
        f"未約定注文: BUY={buy_pending} SELL={sell_pending}",
        "グリッド図: H=ホールド S=売待ち s=ショート *=価格付近 _=空き",
        grid_map,
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
        f"ポジション上限: {rs['current_positions']}/{rs['max_positions']}",
    ]

    if profit_per_hour != 0:
        lines.append(f"利益ペース: {profit_per_hour:+.2f} {q}/h")
    if uptime_str:
        lines.append(f"稼働時間: {uptime_str}")
    if ws_str:
        lines.append(f"WebSocket: {ws_str}")

    lines.extend(
        [
            "=" * 70,
            "Ctrl+C で停止",
        ]
    )
    logger.info("\n".join(lines))
