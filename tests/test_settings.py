"""設定管理のテスト"""

from config.settings import Settings, _safe_float


class TestSafeFloat:
    """_safe_float のテスト"""

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0

    def test_none_returns_custom_default(self):
        assert _safe_float(None, default=42.0) == 42.0

    def test_empty_string_returns_default(self):
        assert _safe_float("") == 0.0

    def test_valid_float(self):
        assert _safe_float("50000.5") == 50000.5

    def test_integer_string(self):
        assert _safe_float("100") == 100.0

    def test_invalid_string_returns_default(self):
        assert _safe_float("abc") == 0.0


class TestSettingsValidation:
    """設定バリデーションのテスト"""

    def test_validate_catches_missing_api_key(self):
        original = Settings.BINANCE_API_KEY
        Settings.BINANCE_API_KEY = ""
        try:
            errors = Settings.validate()
            assert any("BINANCE_API_KEY" in e for e in errors)
        finally:
            Settings.BINANCE_API_KEY = original

    def test_validate_catches_invalid_grid_count(self):
        original = Settings.GRID_COUNT
        Settings.GRID_COUNT = 1
        try:
            errors = Settings.validate()
            assert any("GRID_COUNT" in e for e in errors)
        finally:
            Settings.GRID_COUNT = original

    def test_validate_catches_negative_investment(self):
        original = Settings.INVESTMENT_AMOUNT
        Settings.INVESTMENT_AMOUNT = -100.0
        try:
            errors = Settings.validate()
            assert any("INVESTMENT_AMOUNT" in e for e in errors)
        finally:
            Settings.INVESTMENT_AMOUNT = original

    def test_validate_catches_invalid_stop_loss(self):
        original = Settings.STOP_LOSS_PERCENTAGE
        Settings.STOP_LOSS_PERCENTAGE = 0
        try:
            errors = Settings.validate()
            assert any("STOP_LOSS_PERCENTAGE" in e for e in errors)
        finally:
            Settings.STOP_LOSS_PERCENTAGE = original

    def test_validate_catches_zero_max_positions(self):
        original = Settings.MAX_POSITIONS
        Settings.MAX_POSITIONS = 0
        try:
            errors = Settings.validate()
            assert any("MAX_POSITIONS" in e for e in errors)
        finally:
            Settings.MAX_POSITIONS = original

    def test_validate_catches_invalid_grid_range_factor(self):
        original = Settings.GRID_RANGE_FACTOR
        Settings.GRID_RANGE_FACTOR = 0.0
        try:
            errors = Settings.validate()
            assert any("GRID_RANGE_FACTOR" in e for e in errors)
        finally:
            Settings.GRID_RANGE_FACTOR = original

    def test_validate_catches_zero_check_interval(self):
        original = Settings.CHECK_INTERVAL
        Settings.CHECK_INTERVAL = 0
        try:
            errors = Settings.validate()
            assert any("CHECK_INTERVAL" in e for e in errors)
        finally:
            Settings.CHECK_INTERVAL = original

    def test_validate_catches_negative_fee_rate(self):
        original = Settings.TRADING_FEE_RATE
        Settings.TRADING_FEE_RATE = -0.001
        try:
            errors = Settings.validate()
            assert any("TRADING_FEE_RATE" in e for e in errors)
        finally:
            Settings.TRADING_FEE_RATE = original
