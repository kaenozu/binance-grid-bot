"""状態永続化（SQLite）

ファイルの役割: グリッド状態・ポートフォリオ統計・取引履歴の保存と復元
なぜ存在するか: ボットの再起動時に取引状態を復元するため
関連ファイル: bot.py（メインループ）, portfolio.py（統計）, grid_strategy.py（グリッド状態）
注意: このモジュールはメインボットループ（シングルスレッド）からの使用を想定。
マルチスレッド環境では、呼び出し元で同期化を行うこと。
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from utils.logger import setup_logger

logger = setup_logger("persistence")

DB_PATH = Path("data") / "bot_state.db"
_db_initialized = False
_db_lock = threading.RLock()
_connection: sqlite3.Connection | None = None
_TEST_MODE = False


def set_db_path(path: Path | str):
    """DBパスを変更する（テスト用途のみ。_db_initialized と接続をリセット）

    注意: この関数はテストからのみ呼び出すこと。本番環境で使用すると
    競合状態を引き起こす可能性があります。
    """
    global DB_PATH, _db_initialized, _connection, _TEST_MODE
    with _db_lock:
        _TEST_MODE = True
        DB_PATH = Path(path)
        _db_initialized = False
        if _connection:
            try:
                _connection.close()
            except Exception:
                pass
            _connection = None


def _ensure_db():
    global _db_initialized, _connection
    with _db_lock:
        if _db_initialized and _connection is not None:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _connection = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        try:
            _connection.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    order_id INTEGER NOT NULL,
                    grid_level INTEGER NOT NULL,
                    profit REAL NOT NULL DEFAULT 0,
                    matched INTEGER NOT NULL DEFAULT 0
                )
            """)
            _connection.execute("""
                CREATE TABLE IF NOT EXISTS grid_states (
                    symbol TEXT NOT NULL,
                    grid_level INTEGER NOT NULL,
                    buy_price REAL NOT NULL,
                    sell_price TEXT,
                    buy_order_id INTEGER,
                    sell_order_id INTEGER,
                    position_filled INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (symbol, grid_level)
                )
            """)
            _connection.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_stats (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    initial_balance REAL DEFAULT 0,
                    current_balance REAL DEFAULT 0,
                    total_profit REAL DEFAULT 0,
                    realized_profit REAL DEFAULT 0,
                    unrealized_profit REAL DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    settled_trades INTEGER DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    avg_profit_per_trade REAL DEFAULT 0,
                    total_fees REAL DEFAULT 0,
                    start_time TEXT,
                    last_update TEXT
                )
            """)
            _connection.commit()
        finally:
            pass
        _db_initialized = True
        logger.info(f"DB初期化完了: {DB_PATH}")


def _get_connection() -> sqlite3.Connection:
    _ensure_db()
    assert _connection is not None
    return _connection


def _reset_connection():
    """接続をリセット（テスト用）"""
    global _connection, _db_initialized
    with _db_lock:
        if _connection:
            try:
                _connection.close()
            except Exception:
                pass
            _connection = None
        _db_initialized = False


def save_trade(
    timestamp: datetime,
    symbol: str,
    side: str,
    price: float,
    quantity: float,
    order_id: int,
    grid_level: int,
    profit: float = 0.0,
    matched: bool = False,
):
    with _db_lock:
        conn = _get_connection()
        with conn:
            conn.execute(
                "INSERT INTO trades "
                "(timestamp, symbol, side, price, quantity, order_id, "
                "grid_level, profit, matched) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    timestamp.isoformat(),
                    symbol,
                    side,
                    price,
                    quantity,
                    order_id,
                    grid_level,
                    profit,
                    int(matched),
                ),
            )


def save_grid_states(symbol: str, grids: list):
    with _db_lock:
        conn = _get_connection()
        with conn:
            conn.execute("DELETE FROM grid_states WHERE symbol = ?", (symbol,))
            for g in grids:
                conn.execute(
                    "INSERT INTO grid_states "
                    "(symbol, grid_level, buy_price, sell_price, buy_order_id, "
                    "sell_order_id, position_filled) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        symbol,
                        g.level,
                        g.buy_price,
                        json.dumps(g.sell_price) if g.sell_price is not None else None,
                        g.buy_order_id,
                        g.sell_order_id,
                        int(g.position_filled),
                    ),
                )


def save_portfolio_stats(stats):
    with _db_lock:
        conn = _get_connection()
        with conn:
            conn.execute("DELETE FROM portfolio_stats WHERE id = 1")
            conn.execute(
                "INSERT INTO portfolio_stats "
                "(id, initial_balance, current_balance, total_profit, realized_profit, "
                "unrealized_profit, total_trades, winning_trades, losing_trades, "
                "settled_trades, win_rate, avg_profit_per_trade, total_fees, "
                "start_time, last_update) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?, ?)",
                (
                    stats.initial_balance,
                    stats.current_balance,
                    stats.total_profit,
                    stats.realized_profit,
                    stats.unrealized_profit,
                    stats.total_trades,
                    stats.winning_trades,
                    stats.losing_trades,
                    stats.settled_trades,
                    stats.win_rate,
                    stats.avg_profit_per_trade,
                    stats.total_fees,
                    stats.start_time.isoformat() if stats.start_time else None,
                    stats.last_update.isoformat() if stats.last_update else None,
                ),
            )


def load_grid_states(symbol: str) -> list[dict] | None:
    if not DB_PATH.exists():
        return None
    with _db_lock:
        conn = _get_connection()
        rows = conn.execute(
            "SELECT grid_level, buy_price, sell_price, buy_order_id, "
            "sell_order_id, position_filled FROM grid_states "
            "WHERE symbol = ? ORDER BY grid_level",
            (symbol,),
        ).fetchall()
    if not rows:
        return None
    return [
        {
            "level": row["grid_level"],
            "buy_price": row["buy_price"],
            "sell_price": json.loads(row["sell_price"]) if row["sell_price"] else None,
            "buy_order_id": row["buy_order_id"],
            "sell_order_id": row["sell_order_id"],
            "position_filled": bool(row["position_filled"]),
        }
        for row in rows
    ]


def load_portfolio_stats() -> dict | None:
    if not DB_PATH.exists():
        return None
    with _db_lock:
        conn = _get_connection()
        rows = conn.execute("SELECT * FROM portfolio_stats WHERE id = 1").fetchall()
    if not rows:
        return None
    row = rows[0]
    return {
        "initial_balance": row["initial_balance"],
        "current_balance": row["current_balance"],
        "total_profit": row["total_profit"],
        "realized_profit": row["realized_profit"],
        "unrealized_profit": row["unrealized_profit"],
        "total_trades": row["total_trades"],
        "winning_trades": row["winning_trades"],
        "losing_trades": row["losing_trades"],
        "settled_trades": row["settled_trades"],
        "win_rate": row["win_rate"],
        "avg_profit_per_trade": row["avg_profit_per_trade"],
        "total_fees": row["total_fees"],
        "start_time": datetime.fromisoformat(row["start_time"]) if row["start_time"] else None,
        "last_update": datetime.fromisoformat(row["last_update"]) if row["last_update"] else None,
    }


def update_trade_matched(order_id: int, matched: bool):
    """指定order_idのトレードのmatchedフラグを更新"""
    with _db_lock:
        conn = _get_connection()
        with conn:
            conn.execute(
                "UPDATE trades SET matched = ? WHERE order_id = ?",
                (int(matched), order_id),
            )


def load_trades() -> list[dict]:
    if not DB_PATH.exists():
        return []
    with _db_lock:
        conn = _get_connection()
        rows = conn.execute(
            "SELECT timestamp, symbol, side, price, quantity, "
            "order_id, grid_level, profit, matched "
            "FROM trades ORDER BY id ASC"
        ).fetchall()
    return [
        {
            "timestamp": datetime.fromisoformat(row["timestamp"]),
            "symbol": row["symbol"],
            "side": row["side"],
            "price": row["price"],
            "quantity": row["quantity"],
            "order_id": row["order_id"],
            "grid_level": row["grid_level"],
            "profit": row["profit"],
            "matched": bool(row["matched"]),
        }
        for row in rows
    ]


def _get_stats_fields() -> list[str]:
    from src.portfolio import PortfolioStats

    return [f for f in PortfolioStats.__dataclass_fields__.keys()]


def restore_stats_to(stats_obj, data: dict):
    for field in _get_stats_fields():
        if field in data:
            setattr(stats_obj, field, data[field])
