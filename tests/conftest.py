"""テスト共通設定・フィクスチャ"""

from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from src.grid_strategy import GridStrategy

# ── テスト用価格定数（本番のTestnet価格に合わせる） ─────────
# Testnet の ETH は ~2330 前後で推移
# グリッド幅は GRID_RANGE_FACTOR=0.08 で ±8% = 2144～2516
BASE_PRICE = 2330.0
LOWER_PRICE = 2144.0
UPPER_PRICE = 2516.0
GRID_SPACING = (UPPER_PRICE - LOWER_PRICE) / 10  # 37.2

# Settings クラスの設定項目名（ UPPER_CASE のクラス変数 ）
_SETTING_NAMES = [name for name in dir(Settings) if name.isupper() and not name.startswith("_")]


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    """テスト実行中は本番DBではなく一時DBを使用する（全テスト共通）"""
    db_path = tmp_path / "bot_state.db"
    monkeypatch.setattr("src.persistence.DB_PATH", db_path)
    monkeypatch.setattr("src.persistence._db_initialized", False)
    yield


@pytest.fixture(autouse=True)
def restore_settings_after_test():
    """各テスト後にSettingsの値を復元（自動検出）"""
    original = {name: getattr(Settings, name) for name in _SETTING_NAMES}
    yield
    for name, value in original.items():
        setattr(Settings, name, value)


@pytest.fixture
def grid_strategy():
    """テスト用グリッド戦略（本番価格ベース）"""
    return GridStrategy(
        symbol="BTCUSDT",
        current_price=BASE_PRICE,
        lower_price=LOWER_PRICE,
        upper_price=UPPER_PRICE,
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
    """Binanceクライアントをモック（本番価格ベース）"""
    client = MagicMock()
    client.get_symbol_price.return_value = BASE_PRICE
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
