"""convert_to_jpyスクリプトのテスト（モック）"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    with patch("scripts.convert_to_jpy.BinanceClient") as MockClient:
        mock = MagicMock()
        MockClient.return_value = mock
        yield mock


def test_convert_all_to_jpy_with_balance(mock_client):
    """資産がある場合のテスト"""
    mock_client.get_account_balance.return_value = {
        "JPY": {"free": 10000.0, "locked": 0.0},
        "BTC": {"free": 0.01, "locked": 0.0},
    }
    mock_client.get_symbol_info.return_value = {"step_size": 0.00001}
    mock_client.get_symbol_price.return_value = 15000000.0
    mock_client.place_order.return_value = {
        "symbol": "BTCJPY",
        "cummulativeQuoteQty": "150000.0",
    }

    from scripts.convert_to_jpy import convert_all_to_jpy

    convert_all_to_jpy()

    mock_client.place_order.assert_called_once()
    call_args = mock_client.place_order.call_args
    assert call_args[0][0] == "BTCJPY"
    assert call_args[0][1] == "SELL"


def test_convert_all_to_jpy_jpy_only(mock_client):
    """JPYだけの場合のテスト"""
    mock_client.get_account_balance.return_value = {
        "JPY": {"free": 5000.0, "locked": 0.0},
    }

    from scripts.convert_to_jpy import convert_all_to_jpy

    convert_all_to_jpy()

    mock_client.place_order.assert_not_called()


def test_convert_all_to_jpy_no_balance(mock_client):
    """残高がない場合のテスト"""
    mock_client.get_account_balance.return_value = {
        "JPY": {"free": 0.0, "locked": 0.0},
    }

    from scripts.convert_to_jpy import convert_all_to_jpy

    convert_all_to_jpy()

    mock_client.place_order.assert_not_called()


def test_convert_all_to_jpy_multiple_assets(mock_client):
    """複数資産がある場合のテスト"""
    mock_client.get_account_balance.return_value = {
        "JPY": {"free": 10000.0, "locked": 0.0},
        "BTC": {"free": 0.01, "locked": 0.0},
        "ETH": {"free": 0.1, "locked": 0.0},
        "SOL": {"free": 1.0, "locked": 0.0},
    }
    mock_client.get_symbol_info.return_value = {"step_size": 0.00001}
    mock_client.get_symbol_price.return_value = 15000000.0
    mock_client.place_order.return_value = {
        "symbol": "BTCJPY",
        "cummulativeQuoteQty": "150000.0",
    }

    from scripts.convert_to_jpy import convert_all_to_jpy

    convert_all_to_jpy()

    assert mock_client.place_order.call_count == 3  # JPY以外3つ


def test_convert_all_to_jpy_handles_exception(mock_client):
    """エラーの出る資産がある場合のテスト"""
    mock_client.get_account_balance.return_value = {
        "JPY": {"free": 10000.0, "locked": 0.0},
        "BTC": {"free": 0.01, "locked": 0.0},
        "ETH": {"free": 0.1, "locked": 0.0},
    }
    mock_client.get_symbol_info.side_effect = Exception("API Error")

    from scripts.convert_to_jpy import convert_all_to_jpy

    convert_all_to_jpy()

    mock_client.place_order.assert_not_called()  # エラーで売却されない
