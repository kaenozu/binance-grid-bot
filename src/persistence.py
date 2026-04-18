"""状態永続化（SQLite）

ファイルの役割: グリッド状態・ポートフォリオ統計・取引履歴の保存と復元
なぜ存在するか: ボットの再起動時に取引状態を復元するため
関連ファイル: bot.py（メインループ）, portfolio.py（統計）, grid_strategy.py（グリッド状態）
注意: スレッド安全性のため _db_lock による排他制御を行う。
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

_STAT_COLUMNS = [
    "id",
    "symbol",
    "investment_amount",
    "grid_count",
    "lower_price",
    "upper_price",
    "profit",
    "trade_count",
    "max_drawdown",
    "current_price",
    "status",
    "matched",
    "created_at",
]
_PORTFOLIO_STATS_COLUMNS = [
    "initial_balance",
    "current_balance",
    "total_profit",
    "realized_profit",
    "unrealized_profit",
    "total_trades",
    "winning_trades",
    "losing_trades",
    "settled_trades",
    "win_rate",
    "avg_profit_per_trade",
    "total_fees",
    "peak_balance",
    "max_drawdown",
    "max_drawdown_pct",
    "sharpe_ratio",
]
_JSON_COLUMNS = {"monthly_profit", "yearly_profit"}
_ISO_COLUMNS = {"start_time", "last_update"}


def set_db_path(path: Path | str):
    """DBパスを変更する（テスト用途のみ。_db_initialized と接続をリセット）

    注意: この関数はテストからのみ呼び出すこと。本番環境で使用すると
    競合状態を引き起こす可能性があります。
    """
    global DB_PATH, _db_initialized, _connection, _TEST_MODE
    _TEST_MODE = True
    DB_PATH = Path(path)
    _db_initialized = False
    old_conn = _connection
    _connection = None
    if old_conn:
        try:
            old_conn.close()
        except Exception:
            pass
    logger.info(f"DBパス切替: {path}")


def _ensure_db():
    global _db_initialized, _connection
    with _db_lock:
        logger.debug("_ensure_db: got lock")
        if _db_initialized and _connection is not None:
            logger.debug("_ensure_db: already initialized, returning")
            return
        logger.debug(f"_ensure_db: creating DB at {DB_PATH}")
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        _create_tables(conn)
        _migrate_portfolio_stats(conn)
        _connection = conn
        _db_initialized = True
        logger.info(f"DB初期化完了: {DB_PATH}")


def _create_tables(conn: sqlite3.Connection):
    conn.execute("""
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
    conn.execute("""
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
    conn.execute("""
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
                last_update TEXT,
                peak_balance REAL DEFAULT 0,
                max_drawdown REAL DEFAULT 0,
                max_drawdown_pct REAL DEFAULT 0,
                sharpe_ratio REAL DEFAULT 0,
                monthly_profit TEXT DEFAULT '{}',
                yearly_profit TEXT DEFAULT '{}'
            )
        """)
    conn.commit()


def _get_connection() -> sqlite3.Connection:
    _ensure_db()
    assert _connection is not None
    return _connection


def _migrate_portfolio_stats(conn: sqlite3.Connection):
    """既存DBに新カラムがなければ追加（ロック内で呼ぶこと）"""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(portfolio_stats)").fetchall()}
    new_columns = {
        "peak_balance": "REAL DEFAULT 0",
        "max_drawdown": "REAL DEFAULT 0",
        "max_drawdown_pct": "REAL DEFAULT 0",
        "sharpe_ratio": "REAL DEFAULT 0",
        "monthly_profit": "TEXT DEFAULT '{}'",
        "yearly_profit": "TEXT DEFAULT '{}'",
    }
    for col, definition in new_columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE portfolio_stats ADD COLUMN {col} {definition}")
            logger.info(f"DB移行: カラム {col} を追加")
    if any(col not in existing for col in new_columns):
        conn.commit()


def _reset_connection():
    """接続をリセット（テスト用）"""
    global _connection, _db_initialized
    if _connection:
        try:
            _connection.close()
        except Exception:
            pass
    _connection = None
    _db_initialized = False
    logger.info("DB接続リセット完了")


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
        values: list = []
        for col in _PORTFOLIO_STATS_COLUMNS:
            values.append(getattr(stats, col, 0))
        for col in _JSON_COLUMNS:
            values.append(json.dumps(getattr(stats, col, {})))
        for col in _ISO_COLUMNS:
            val = getattr(stats, col, None)
            values.append(val.isoformat() if val else None)

        col_names = _PORTFOLIO_STATS_COLUMNS + list(_JSON_COLUMNS) + list(_ISO_COLUMNS)
        placeholders = ", ".join(["?"] * len(col_names))
        col_str = ", ".join(col_names)
        with conn:
            conn.execute("DELETE FROM portfolio_stats WHERE id = 1")
            conn.execute(
                f"INSERT INTO portfolio_stats (id, {col_str}) VALUES (1, {placeholders})",
                values,
            )


def load_grid_states(symbol: str) -> list[dict] | None:
    with _db_lock:
        if not DB_PATH.exists():
            return None
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
    with _db_lock:
        if not DB_PATH.exists():
            return None
        conn = _get_connection()
        rows = conn.execute("SELECT * FROM portfolio_stats WHERE id = 1").fetchall()
    if not rows:
        return None
    row = rows[0]
    result: dict = {}
    for col in _PORTFOLIO_STATS_COLUMNS:
        result[col] = row[col]
    for col in _JSON_COLUMNS:
        result[col] = json.loads(row[col]) if row[col] else {}
    for col in _ISO_COLUMNS:
        result[col] = datetime.fromisoformat(row[col]) if row[col] else None
    return result


def update_trade_matched(order_id: int, matched: bool):
    """指定order_idのトレードのmatchedフラグを更新"""
    with _db_lock:
        conn = _get_connection()
        with conn:
            conn.execute(
                "UPDATE trades SET matched = ? WHERE order_id = ?",
                (int(matched), order_id),
            )
    logger.debug(f"matchedフラグ更新: order_id={order_id}, matched={matched}")


def load_trades() -> list[dict]:
    with _db_lock:
        if not DB_PATH.exists():
            return []
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
