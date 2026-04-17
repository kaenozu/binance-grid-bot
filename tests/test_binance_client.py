"""Binance APIクライアントのテスト"""

from unittest.mock import MagicMock, patch

import pytest

from src.binance_client import BinanceAPIError, BinanceClient


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


def test_sign_params_replaces_previous_signature(client):
    captured = []

    def fake_generate_signature(query_string: str) -> str:
        captured.append(query_string)
        return f"sig{len(captured)}"

    with patch("src.binance_client.time.time", side_effect=[1.0, 2.0]):
        with patch.object(client, "_generate_signature", side_effect=fake_generate_signature):
            params = {"symbol": "BTCUSDT"}
            client._sign_params(params)
            client._sign_params(params)

    assert captured == [
        "symbol=BTCUSDT&timestamp=1000",
        "symbol=BTCUSDT&timestamp=2000",
    ]
    assert params["signature"] == "sig2"


def test_adjust_price_raises_for_invalid_method(client):
    with pytest.raises(ValueError):
        client._send_request("PUT", "http://example.com", {})


def test_send_request_get(client):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"symbol": "BTCUSDT", "price": "74000.00"}
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


def test_place_order_normalizes_misaligned_quantity(client):
    client.get_symbol_info = MagicMock(
        return_value={
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "min_qty": 0.001,
            "max_qty": 1000.0,
            "step_size": 0.001,
            "min_notional": 10.0,
            "tick_size": 0.01,
        }
    )

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "orderId": 123,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "LIMIT",
        "price": "74000.00",
        "origQty": "0.001",
        "status": "NEW",
    }
    client.session.post.return_value = response

    result = client.place_order("BTCUSDT", "BUY", quantity=0.0014, price=74000.0)
    assert result["orderId"] == 123
    assert client.session.post.call_args.kwargs["data"]["quantity"] == "0.001"


def test_place_order_normalizes_misaligned_price(client):
    client.get_symbol_info = MagicMock(
        return_value={
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "min_qty": 0.001,
            "max_qty": 1000.0,
            "step_size": 0.001,
            "min_notional": 10.0,
            "tick_size": 0.5,
        }
    )

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "orderId": 124,
        "symbol": "BTCUSDT",
        "side": "SELL",
        "type": "LIMIT",
        "price": "74000.5",
        "origQty": "0.002",
        "status": "NEW",
    }
    client.session.post.return_value = response

    result = client.place_order("BTCUSDT", "SELL", quantity=0.002, price=74000.25)
    assert result["orderId"] == 124
    assert client.session.post.call_args.kwargs["data"]["price"] == "74000.5"


def test_sync_server_time_updates_offset(client):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"serverTime": 2500}

    with patch("src.binance_client.time.time", return_value=1.0):
        with patch.object(client, "_send_request", return_value=response):
            client._sync_server_time()

    assert client._time_offset_ms == 1500


def test_is_timestamp_error_detects_binance_error(client):
    response = MagicMock()
    response.text = (
        '{"code":-1021,"msg":"Timestamp for this request was 1000ms ahead of the server\'s time."}'
    )
    response.json.return_value = {
        "code": -1021,
        "msg": "Timestamp for this request was 1000ms ahead of the server's time.",
    }

    assert client._is_timestamp_error(response) is True


def test_place_order_accepts_min_quantity(client):
    client.get_symbol_info = MagicMock(
        return_value={
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "min_qty": 0.001,
            "max_qty": 1000.0,
            "step_size": 0.001,
            "min_notional": 10.0,
            "tick_size": 0.01,
        }
    )
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "orderId": 123,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "LIMIT",
        "price": "74000.00",
        "origQty": "0.001",
        "status": "NEW",
    }
    client.session.post.return_value = response

    result = client.place_order("BTCUSDT", "BUY", quantity=0.001, price=74000.0)
    assert result["orderId"] == 123


def test_place_order_bumps_quantity_to_min_qty(client):
    client.get_symbol_info = MagicMock(
        return_value={
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "min_qty": 0.001,
            "max_qty": 1000.0,
            "step_size": 0.001,
            "min_notional": 10.0,
            "tick_size": 0.01,
        }
    )

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "orderId": 125,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "LIMIT",
        "price": "74000.00",
        "origQty": "0.001",
        "status": "NEW",
    }
    client.session.post.return_value = response

    result = client.place_order("BTCUSDT", "BUY", quantity=0.0005, price=74000.0)
    assert result["orderId"] == 125
    assert client.session.post.call_args.kwargs["data"]["quantity"] == "0.001"


def test_place_order_bumps_quantity_to_meet_min_notional(client):
    client.get_symbol_info = MagicMock(
        return_value={
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "min_qty": 0.00001,
            "max_qty": 9000.0,
            "step_size": 0.00001,
            "min_notional": 10.0,
            "tick_size": 0.01,
        }
    )

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "orderId": 126,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "LIMIT",
        "price": "10.00",
        "origQty": "1",
        "status": "NEW",
    }
    client.session.post.return_value = response

    result = client.place_order("BTCUSDT", "BUY", quantity=0.0001, price=10.0)
    assert result["orderId"] == 126
    assert client.session.post.call_args.kwargs["data"]["quantity"] == "1"


def test_place_order_refreshes_symbol_info_after_filter_failure(client):
    client.get_symbol_info = MagicMock(
        side_effect=[
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "min_qty": 0.001,
                "max_qty": 1000.0,
                "step_size": 0.001,
                "min_notional": 0.5,
                "tick_size": 0.01,
            },
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "min_qty": 0.01,
                "max_qty": 1000.0,
                "step_size": 0.01,
                "min_notional": 10.0,
                "tick_size": 0.01,
            },
        ]
    )

    seen_params = []

    def fake_make_request(method, endpoint, params=None, signed=False):
        seen_params.append(dict(params or {}))
        if len(seen_params) == 1:
            raise BinanceAPIError(
                "Filter failure: LOT_SIZE",
                status_code=400,
                endpoint="/api/v3/order",
            )
        return {
            "orderId": 127,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "price": "100.00",
            "origQty": "0.1",
            "status": "NEW",
        }

    client._make_request = MagicMock(side_effect=fake_make_request)

    result = client.place_order("BTCUSDT", "BUY", quantity=0.0042, price=100.0)

    assert result["orderId"] == 127
    assert client.get_symbol_info.call_count == 2
    assert seen_params[0]["quantity"] == "0.005"
    assert seen_params[1]["quantity"] == "0.1"


def test_check_time_offset_warns_large_offset(client):
    client._time_offset_ms = 10000
    with patch("src.binance_client.logger") as mock_logger:
        client._check_time_offset()
    mock_logger.warning.assert_called_once()
    assert "10000ms" in mock_logger.warning.call_args[0][0]


def test_check_time_offset_passes_small_offset(client):
    client._time_offset_ms = 100
    with patch("src.binance_client.logger") as mock_logger:
        client._check_time_offset()
    mock_logger.info.assert_called_once()
    assert "100ms" in mock_logger.info.call_args[0][0]


def test_unsupported_listen_key_error_uses_status_and_endpoint():
    err = BinanceAPIError(
        "listenKey endpoint unavailable (410)",
        status_code=410,
        endpoint="/api/v3/userDataStream",
    )
    assert err.status_code == 410
    assert err.endpoint.endswith("/userDataStream")
