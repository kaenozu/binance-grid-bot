"""
ファイルパス: tests/conftest.py
概要: テスト共通の設定・フィクスチャ
説明: pytestで使用する共通モック・フィクスチャを定義
関連ファイル: tests/test_grid_strategy.py, tests/test_risk_manager.py
"""

import pytest
from unittest.mock import MagicMock, patch

from config.settings import Settings
from src.grid_strategy import GridStrategy


@pytest.fixture(autouse=True)
def restore_settings_after_test():
    """各テスト後にSettingsの値を復元"""
    # テスト前の値を保存
    original = {
        "BINANCE_API_KEY": Settings.BINANCE_API_KEY,
        "BINANCE_API_SECRET": Settings.BINANCE_API_SECRET,
        "USE_TESTNET": Settings.USE_TESTNET,
        "TRADING_SYMBOL": Settings.TRADING_SYMBOL,
        "GRID_COUNT": Settings.GRID_COUNT,
        "LOWER_PRICE": Settings.LOWER_PRICE,
        "UPPER_PRICE": Settings.UPPER_PRICE,
        "INVESTMENT_AMOUNT": Settings.INVESTMENT_AMOUNT,
        "STOP_LOSS_PERCENTAGE": Settings.STOP_LOSS_PERCENTAGE,
        "MAX_POSITIONS": Settings.MAX_POSITIONS,
        "CHECK_INTERVAL": Settings.CHECK_INTERVAL,
        "STATUS_DISPLAY_INTERVAL": Settings.STATUS_DISPLAY_INTERVAL,
        "MAX_CONSECUTIVE_ERRORS": Settings.MAX_CONSECUTIVE_ERRORS,
        "GRID_RANGE_FACTOR": Settings.GRID_RANGE_FACTOR,
        "TRADING_FEE_RATE": Settings.TRADING_FEE_RATE,
        "CLOSE_ON_STOP": Settings.CLOSE_ON_STOP,
        "PERSIST_INTERVAL": Settings.PERSIST_INTERVAL,
    }
    yield
    # テスト後に値を復元
    for key, value in original.items():
        setattr(Settings, key, value)


@pytest.fixture
def grid_strategy():
    """テスト用グリッド戦略"""
    return GridStrategy(
        symbol="BTCUSDT",
        current_price=50000.0,
        lower_price=45000.0,
        upper_price=55000.0,
        grid_count=10,
        investment_amount=1000.0,
    )


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
        mock.CHECK_INTERVAL = 10
        mock.MAX_CONSECUTIVE_ERRORS = 5
        mock.GRID_RANGE_FACTOR = 0.15
        mock.TRADING_FEE_RATE = 0.001
        mock.CLOSE_ON_STOP = False
        mock.PERSIST_INTERVAL = 60
        mock.validate.return_value = []
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


@pytest.fixture
def mock_client_for_portfolio():
    """Portfolioテスト用モッククライアント"""
    client = MagicMock()
    client.get_account_balance.return_value = {
        "USDT": {"free": 10000.0, "locked": 0.0},
        "BTC": {"free": 0.002, "locked": 0.0},
    }
    return client
