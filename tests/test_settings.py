"""
ファイルパス: tests/test_settings.py
概要: 設定管理のテスト
説明: バリデーション、_safe_float、デフォルト値を検証
関連ファイル: config/settings.py, tests/conftest.py
"""

import pytest
from config.settings import Settings, _safe_float


class TestSafeFloat:
    """_safe_float のテスト"""

    def test_none_returns_none(self):
        assert _safe_float(None) is None

    def test_empty_string_returns_none(self):
        assert _safe_float("") is None

    def test_valid_float(self):
        assert _safe_float("50000.5") == 50000.5

    def test_integer_string(self):
        assert _safe_float("100") == 100.0

    def test_invalid_string_returns_none(self):
        assert _safe_float("abc") is None


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
