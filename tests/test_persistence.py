"""
ファイルパス: tests/test_persistence.py
概要: 状態永続化のテスト
説明: SQLiteへの保存・復元を検証
関連ファイル: src/persistence.py
"""

import sqlite3
from datetime import datetime

import pytest

from src.persistence import (
    load_grid_states,
    load_portfolio_stats,
    load_trades,
    restore_stats_to,
    save_grid_states,
    save_portfolio_stats,
    save_trade,
)


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    db_path = tmp_path / "bot_state.db"
    monkeypatch.setattr("src.persistence.DB_PATH", db_path)
    monkeypatch.setattr("src.persistence._db_initialized", False)
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


def test_load_trades():
    save_trade(
        timestamp=datetime(2026, 1, 1, 10, 0, 0),
        symbol="BTCUSDT",
        side="BUY",
        price=50000.0,
        quantity=0.001,
        order_id=1,
        grid_level=0,
        profit=0.0,
    )
    save_trade(
        timestamp=datetime(2026, 1, 1, 11, 0, 0),
        symbol="ETHUSDT",
        side="SELL",
        price=3000.0,
        quantity=0.1,
        order_id=2,
        grid_level=1,
        profit=5.0,
    )

    trades = load_trades()
    assert len(trades) == 2
    assert trades[0]["side"] == "BUY"
    assert trades[1]["side"] == "SELL"
    assert trades[1]["profit"] == 5.0


def test_save_grid_states_overwrites():
    from types import SimpleNamespace

    grids_v1 = [
        SimpleNamespace(
            level=0,
            buy_price=45000.0,
            sell_price=46000.0,
            buy_order_id=1,
            sell_order_id=None,
            position_filled=True,
        ),
    ]
    save_grid_states("BTCUSDT", grids_v1)

    grids_v2 = [
        SimpleNamespace(
            level=0,
            buy_price=48000.0,
            sell_price=49000.0,
            buy_order_id=2,
            sell_order_id=None,
            position_filled=False,
        ),
    ]
    save_grid_states("BTCUSDT", grids_v2)

    loaded = load_grid_states("BTCUSDT")
    assert len(loaded) == 1
    assert loaded[0]["buy_price"] == 48000.0
    assert loaded[0]["position_filled"] is False


def test_multiple_symbols_independent():
    from types import SimpleNamespace

    grids_btc = [
        SimpleNamespace(
            level=0,
            buy_price=45000.0,
            sell_price=46000.0,
            buy_order_id=1,
            sell_order_id=None,
            position_filled=True,
        ),
    ]
    grids_eth = [
        SimpleNamespace(
            level=0,
            buy_price=3000.0,
            sell_price=3100.0,
            buy_order_id=2,
            sell_order_id=None,
            position_filled=False,
        ),
    ]
    save_grid_states("BTCUSDT", grids_btc)
    save_grid_states("ETHUSDT", grids_eth)

    loaded_btc = load_grid_states("BTCUSDT")
    loaded_eth = load_grid_states("ETHUSDT")

    assert loaded_btc[0]["buy_price"] == 45000.0
    assert loaded_btc[0]["position_filled"] is True
    assert loaded_eth[0]["buy_price"] == 3000.0
    assert loaded_eth[0]["position_filled"] is False


def test_restore_stats_to():
    from src.portfolio import PortfolioStats

    stats = PortfolioStats()
    data = {
        "initial_balance": 500.0,
        "total_trades": 10,
        "realized_profit": 25.0,
    }
    restore_stats_to(stats, data)
    assert stats.initial_balance == 500.0
    assert stats.total_trades == 10
    assert stats.realized_profit == 25.0
