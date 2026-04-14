"""
ファイルパス: tests/test_binance_client.py
概要: Binance APIクライアントのテスト
説明: 署名生成、リトライ、エラーハンドリングを検証
関連ファイル: src/binance_client.py
"""

from unittest.mock import MagicMock, patch
import pytest

from src.binance_client import BinanceClient, BinanceAPIError, MAX_RETRIES


@pytest.fixture
def client():
    with patch("src.binance_client.Settings") as mock:
        mock.BINANCE_API_KEY = "test_key"
        mock.BINANCE_API_SECRET = "test_secret"
        mock.USE_TESTNET = True
        with patch("src.binance_client.requests.Session"):
            yield BinanceClient()


def test_client_initialization(client):
    assert client.base_url == "https://testnet.binance.vision"
    assert client.api_key == "test_key"


def test_generate_signature(client):
    sig = client._generate_signature("symbol=BTCUSDT&timestamp=1234")
    assert isinstance(sig, str)
    assert len(sig) == 64


def test_adjust_price_raises_for_invalid_method(client):
    with pytest.raises(ValueError):
        client._send_request("PUT", "http://example.com", {})


def test_send_request_get(client):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"symbol": "BTCUSDT", "price": "50000.00"}
    client.session.get.return_value = response

    result = client._send_request("GET", "http://example.com", {"symbol": "BTCUSDT"})
    assert result.json()["symbol"] == "BTCUSDT"


def test_binance_api_error():
    err = BinanceAPIError("test error")
    assert str(err) == "test error"


def test_context_manager():
    with patch("src.binance_client.Settings") as mock:
        mock.BINANCE_API_KEY = "test_key"
        mock.BINANCE_API_SECRET = "test_secret"
        mock.USE_TESTNET = True
        with patch("src.binance_client.requests.Session"):
            with BinanceClient() as c:
                assert c is not None
