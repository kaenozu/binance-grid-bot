"""プリセット設定のテスト"""

import pytest

from config.presets import (
    PRESETS,
    MULTI_PRESETS,
    GridPreset,
    get_preset,
    list_presets,
    list_presets_by_risk,
    preset_to_env,
    recommend_for_capital,
)


class TestPresetDefinitions:
    """プリセット定義の整合性テスト"""

    def test_all_presets_have_required_fields(self):
        for key, preset in PRESETS.items():
            assert isinstance(preset, GridPreset)
            assert preset.name, f"{key}: name が空"
            assert preset.symbol, f"{key}: symbol が空"
            assert preset.symbol.endswith("USDT") or preset.symbol.endswith("JPY"), f"{key}: symbol はUSDT/JPYペアであるべき"
            assert preset.grid_count >= 2, f"{key}: grid_count >= 2"
            assert 0 < preset.grid_range_factor <= 1, f"{key}: grid_range_factor の範囲"
            assert preset.investment_amount > 0, f"{key}: investment_amount > 0"
            assert 0 < preset.stop_loss_percentage <= 100, f"{key}: stop_loss の範囲"
            assert 0 < preset.max_drawdown_pct <= 100, f"{key}: max_drawdown の範囲"
            assert preset.max_positions >= 1, f"{key}: max_positions >= 1"
            assert preset.trading_fee_rate >= 0, f"{key}: fee_rate >= 0"
            assert preset.risk_level in ("low", "medium", "high"), f"{key}: risk_level 不正"
            assert preset.min_capital > 0, f"{key}: min_capital > 0"

    def test_stop_loss_less_than_max_drawdown(self):
        """損切りは最大DD以下であるべき"""
        for key, preset in PRESETS.items():
            assert (
                preset.stop_loss_percentage <= preset.max_drawdown_pct
            ), f"{key}: stop_loss > max_drawdown"

    def test_min_capital_leq_investment(self):
        """最低資金は投資額以下であるべき"""
        for key, preset in PRESETS.items():
            assert (
                preset.min_capital <= preset.investment_amount
            ), f"{key}: min_capital > investment"

    def test_unique_symbols_in_multi_presets(self):
        """マルチプリセットのシンボルは重複なし"""
        for key, cfg in MULTI_PRESETS.items():
            symbols = cfg["symbols"]
            assert len(symbols) == len(set(symbols)), f"{key}: シンボル重複"
            # allocation と symbols が一致
            for sym in symbols:
                assert sym in cfg["allocation"], f"{key}: {sym} が allocation にない"


class TestPresetLookup:
    def test_get_preset_exists(self):
        preset = get_preset("eth-balanced")
        assert preset is not None
        assert preset.symbol == "ETHUSDT"

    def test_get_preset_not_exists(self):
        assert get_preset("nonexistent") is None

    def test_list_presets_returns_all(self):
        presets = list_presets()
        assert len(presets) == len(PRESETS)

    def test_list_presets_by_risk(self):
        low = list_presets_by_risk("low")
        assert all(p.risk_level == "low" for p in low)
        assert len(low) > 0

        high = list_presets_by_risk("high")
        assert all(p.risk_level == "high" for p in high)


class TestRecommendForCapital:
    def test_small_capital(self):
        results = recommend_for_capital(30)
        assert len(results) > 0
        # 最低資金30以下のプリセットが含まれる
        symbols = [p.symbol for p in results]
        assert "XRPUSDT" in symbols or "DOGEUSDT" in symbols

    def test_large_capital(self):
        results = recommend_for_capital(5000)
        assert len(results) > 0
        # 大口向けが上位に来るはず
        symbols = [p.symbol for p in results]

    def test_zero_capital(self):
        results = recommend_for_capital(0)
        assert len(results) == 0

    def test_very_small_capital(self):
        results = recommend_for_capital(10)
        assert len(results) == 0  # 最低30 USDT


class TestPresetToEnv:
    def test_converts_to_env_dict(self):
        preset = get_preset("eth-balanced")
        env = preset_to_env(preset)
        assert env["TRADING_SYMBOL"] == "ETHUSDT"
        assert env["GRID_COUNT"] == "10"
        assert env["GRID_RANGE_FACTOR"] == "0.08"
        assert env["INVESTMENT_AMOUNT"] == "500"
        assert float(env["STOP_LOSS_PERCENTAGE"]) == 10.0

    def test_all_values_are_strings(self):
        preset = get_preset("xrp-micro")
        env = preset_to_env(preset)
        for key, value in env.items():
            assert isinstance(value, str), f"{key} の値が文字列ではない"
