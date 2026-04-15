"""トレードエクスポートのテスト"""

import csv
import json
from datetime import datetime

import pytest

from src.exporter import export_trades_csv, export_trades_json
from src.portfolio import Trade


@pytest.fixture
def sample_trades():
    return [
        Trade(
            timestamp=datetime(2026, 1, 1, 10, 0, 0),
            symbol="BTCUSDT",
            side="BUY",
            price=74000.0,
            quantity=0.002,
            order_id=100,
            grid_level=5,
        ),
        Trade(
            timestamp=datetime(2026, 1, 1, 11, 0, 0),
            symbol="BTCUSDT",
            side="SELL",
            price=51000.0,
            quantity=0.002,
            order_id=101,
            grid_level=5,
            profit=2.0,
            matched=True,
        ),
    ]


def test_export_csv(tmp_path, sample_trades):
    filepath = tmp_path / "trades.csv"
    count = export_trades_csv(sample_trades, filepath)
    assert count == 2
    assert filepath.exists()

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["side"] == "BUY"
    assert rows[1]["side"] == "SELL"
    assert float(rows[1]["profit"]) == 2.0


def test_export_json(tmp_path, sample_trades):
    filepath = tmp_path / "trades.json"
    count = export_trades_json(sample_trades, filepath)
    assert count == 2
    assert filepath.exists()

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 2
    assert data[0]["side"] == "BUY"
    assert data[1]["profit"] == 2.0


def test_export_empty(tmp_path):
    filepath = tmp_path / "empty.csv"
    count = export_trades_csv([], filepath)
    assert count == 0
    assert not filepath.exists()


def test_export_creates_directory(tmp_path):
    filepath = tmp_path / "subdir" / "trades.csv"
    export_trades_csv(
        [Trade(datetime.now(), "BTCUSDT", "BUY", 74000.0, 0.001, 1, 0)],
        filepath,
    )
    assert filepath.exists()
