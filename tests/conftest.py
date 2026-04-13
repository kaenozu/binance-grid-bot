"""
ファイルパス: tests/conftest.py
概要: テスト共通の設定・フィクスチャ
説明: pytestで使用する共通モック・フィクスチャを定義
関連ファイル: tests/test_grid_strategy.py, tests/test_risk_manager.py
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_settings():
    """設定をテスト用にモック"""
    with patch("config.settings.Settings") as mock:
        mock.BINANCE_API_KEY = "test_api_key"
        mock.BINANCE_API_SECRET = "test_api_secret"
        mock.USE_TESTNET = True
        mock.TRADING_SYMBOL = "BTCUSDT"
        mock.GRID_COUNT = 10
        mock.LOWER_PRICE = None
        mock.UPPER_PRICE = None
        mock.INVESTMENT_AMOUNT = 1000.0
        mock.STOP_LOSS_PERCENTAGE = 5.0
        mock.MAX_POSITIONS = 5
        yield mock


@pytest.fixture
def mock_binance_client():
    """Binanceクライアントをモック"""
    client = MagicMock()
    client.get_symbol_price.return_value = 50000.0
    client.get_symbol_info.return_value = {
        "symbol": "BTCUSDT",
        "status": "TRADING",
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "price_precision": 2,
        "quantity_precision": 6,
        "min_qty": 0.00001,
        "max_qty": 9000.0,
        "step_size": 0.00001,
        "min_notional": 10.0,
        "tick_size": 0.01,
    }
    client.get_account_balance.return_value = {
        "USDT": {"free": 10000.0, "locked": 0.0},
        "BTC": {"free": 0.0, "locked": 0.0},
    }
    return client
