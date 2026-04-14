"""
ファイルパス: tests/test_paper_client.py
概要: ペーパートレードクライアントのテスト
説明: PaperClientのシミュレーション機能を検証
関連ファイル: src/paper_client.py
"""

import pytest
from src.paper_client import PaperClient


class TestPaperClient:
    @pytest.fixture
    def client(self):
        return PaperClient()

    def test_place_order_returns_order_id(self, client):
        order = client.place_order(symbol="BTCUSDT", side="BUY", quantity=0.001, price=50000.0)
        assert "orderId" in order
        assert order["status"] == "NEW"

    def test_market_order_fills_immediately(self, client):
        order = client.place_order(symbol="BTCUSDT", side="BUY", quantity=0.001, price=None)
        assert order["status"] == "FILLED"

    def test_open_orders(self, client):
        client.place_order("BTCUSDT", "BUY", 0.001, 50000.0)
        client.place_order("BTCUSDT", "BUY", 0.001, 49000.0)
        client.place_order("BTCUSDT", "BUY", 0.001, price=None)

        open_orders = client.get_open_orders("BTCUSDT")
        assert len(open_orders) == 2

    def test_get_order(self, client):
        order = client.place_order("BTCUSDT", "BUY", 0.001, 50000.0)
        fetched = client.get_order("BTCUSDT", order["orderId"])
        assert fetched["orderId"] == order["orderId"]

    def test_get_symbol_info(self, client):
        info = client.get_symbol_info("BTCUSDT")
        assert info["symbol"] == "BTCUSDT"
        assert info["tick_size"] == 0.01
