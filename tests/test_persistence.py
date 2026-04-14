"""
ファイルパス: tests/test_persistence.py
概要: 状態永続化のテスト
説明: SQLiteへの保存・復元を検証
関連ファイル: src/persistence.py
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from src.persistence import (
    DB_PATH,
    save_trade,
    save_grid_states,
    save_portfolio_stats,
    load_grid_states,
    load_portfolio_stats,
)


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    db_path = tmp_path / "bot_state.db"
    monkeypatch.setattr("src.persistence.DB_PATH", db_path)
    yield


def test_save_and_load_grid_states():
    from types import SimpleNamespace

    grids = [
        SimpleNamespace(
            level=0,
            buy_price=45000.0,
            sell_price=46000.0,
            buy_order_id=100,
            sell_order_id=None,
            position_filled=True,
        ),
        SimpleNamespace(
            level=1,
            buy_price=46000.0,
            sell_price=47000.0,
            buy_order_id=None,
            sell_order_id=101,
            position_filled=False,
        ),
    ]
    save_grid_states("BTCUSDT", grids)

    loaded = load_grid_states("BTCUSDT")
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded[0]["position_filled"] is True
    assert loaded[0]["buy_order_id"] == 100
    assert loaded[1]["position_filled"] is False


def test_load_returns_none_when_empty():
    assert load_grid_states("NONEXIST") is None


def test_save_and_load_portfolio_stats():
    from src.portfolio import PortfolioStats

    stats = PortfolioStats(
        initial_balance=1000.0,
        current_balance=1050.0,
        total_profit=50.0,
        realized_profit=30.0,
        total_trades=5,
        total_fees=1.5,
    )
    stats.start_time = datetime(2026, 1, 1)
    stats.last_update = datetime(2026, 1, 2)
    save_portfolio_stats(stats)

    loaded = load_portfolio_stats()
    assert loaded is not None
    assert loaded["initial_balance"] == 1000.0
    assert loaded["total_profit"] == 50.0
    assert loaded["total_trades"] == 5
    assert loaded["total_fees"] == 1.5


def test_save_trade():
    import src.persistence as persist

    save_trade(
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        symbol="BTCUSDT",
        side="BUY",
        price=50000.0,
        quantity=0.001,
        order_id=123,
        grid_level=3,
    )
    conn = sqlite3.connect(str(persist.DB_PATH))
    rows = conn.execute("SELECT COUNT(*) as cnt FROM trades").fetchone()
    conn.close()
    assert rows[0] == 1


def test_db_file_created():
    import src.persistence as persist

    save_trade(
        datetime.now(),
        "BTCUSDT",
        "BUY",
        50000.0,
        0.001,
        1,
        0,
    )
    assert persist.DB_PATH.exists()
