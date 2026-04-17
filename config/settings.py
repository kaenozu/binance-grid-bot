"""環境変数から設定を読み込む

ファイルの役割: 環境変数から設定を読み込み、バリデーションを提供
なぜ存在するか: 設定の一元管理とタイプセーフなアクセスため
関連ファイル: src/bot.py（設定参照）, src/binance_client.py（API認証）
"""

import os
import re

from dotenv import load_dotenv

load_dotenv()


def _safe_float_optional(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _safe_float(value: str | None, default: float = 0.0) -> float:
    result = _safe_float_optional(value)
    return result if result is not None else default


def _safe_int(value: str | None, default: int = 0) -> int:
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


class Settings:
    """取引ボットの設定を管理するクラス"""

    # Binance API
    BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")
    USE_TESTNET: bool = os.getenv("USE_TESTNET", "true").lower() == "true"

    # 取引設定
    TRADING_SYMBOL: str = os.getenv("TRADING_SYMBOL", "BTCUSDT")
    GRID_COUNT: int = _safe_int(os.getenv("GRID_COUNT"), 10)
    LOWER_PRICE: float | None = _safe_float_optional(os.getenv("LOWER_PRICE"))
    UPPER_PRICE: float | None = _safe_float_optional(os.getenv("UPPER_PRICE"))
    INVESTMENT_AMOUNT: float = _safe_float(os.getenv("INVESTMENT_AMOUNT"), 100.0)

    # リスク管理
    STOP_LOSS_PERCENTAGE: float = _safe_float(os.getenv("STOP_LOSS_PERCENTAGE"), 5.0)
    MAX_DRAWDOWN_PCT: float = _safe_float(os.getenv("MAX_DRAWDOWN_PCT"), 10.0)
    MAX_POSITIONS: int = _safe_int(os.getenv("MAX_POSITIONS"), 5)

    # ボット動作設定
    CHECK_INTERVAL: int = _safe_int(os.getenv("CHECK_INTERVAL"), 10)
    STATUS_DISPLAY_INTERVAL: int = _safe_int(os.getenv("STATUS_DISPLAY_INTERVAL"), 60)
    MAX_CONSECUTIVE_ERRORS: int = _safe_int(os.getenv("MAX_CONSECUTIVE_ERRORS"), 5)
    GRID_RANGE_FACTOR: float = _safe_float(os.getenv("GRID_RANGE_FACTOR"), 0.15)
    TRADING_FEE_RATE: float = _safe_float(os.getenv("TRADING_FEE_RATE"), 0.001)
    CLOSE_ON_STOP: bool = os.getenv("CLOSE_ON_STOP", "true").lower() == "true"
    PERSIST_INTERVAL: int = _safe_int(os.getenv("PERSIST_INTERVAL"), 60)
    USE_USER_STREAM: bool = os.getenv("USE_USER_STREAM", "true").lower() == "true"

    @classmethod
    def validate(cls) -> list[str]:
        """設定のバリデーションを行い、エラーリストを返す"""
        errors = []

        if not cls.BINANCE_API_KEY or cls.BINANCE_API_KEY == "your_api_key_here":
            errors.append("BINANCE_API_KEY が設定されていません")

        if not cls.BINANCE_API_SECRET or cls.BINANCE_API_SECRET == "your_api_secret_here":
            errors.append("BINANCE_API_SECRET が設定されていません")

        if cls.BINANCE_API_KEY and not re.match(r"^[A-Za-z0-9+/]+$", cls.BINANCE_API_KEY):
            errors.append("BINANCE_API_KEY の形式が不正です（英数字と記号 +/ のみ）")

        if cls.BINANCE_API_SECRET and not re.match(r"^[A-Za-z0-9+/]+$", cls.BINANCE_API_SECRET):
            errors.append("BINANCE_API_SECRET の形式が不正です（英数字と記号 +/ のみ）")

        if cls.GRID_COUNT < 0:
            errors.append("GRID_COUNT は 0 以上である必要があります（0=自動、2以上で手動）")
        if cls.GRID_COUNT == 1:
            errors.append("GRID_COUNT は 2 以上である必要があります（0=自動）")

        if cls.INVESTMENT_AMOUNT < 0:
            errors.append("INVESTMENT_AMOUNT は 0 以上である必要があります")

        # JPY pairs: threshold is higher (1 USD ~ 150 JPY)
        symbol = cls.TRADING_SYMBOL.upper()
        is_jpy = symbol.endswith("JPY")
        amount_threshold = 750000 if is_jpy else 5000  # 750k JPY ~ 5000 USDT

        if cls.INVESTMENT_AMOUNT > 0 and not cls.USE_TESTNET and cls.INVESTMENT_AMOUNT > amount_threshold:
            unit = "JPY" if is_jpy else "USDT"
            errors.append(
                f"本番環境での INVESTMENT_AMOUNT が {int(amount_threshold)} {unit} を超えています。"
                "少額から開始することを強く推奨します。"
            )

        if cls.STOP_LOSS_PERCENTAGE <= 0 or cls.STOP_LOSS_PERCENTAGE > 100:
            errors.append("STOP_LOSS_PERCENTAGE は 0-100 の範囲である必要があります")

        if cls.MAX_DRAWDOWN_PCT <= 0 or cls.MAX_DRAWDOWN_PCT > 100:
            errors.append("MAX_DRAWDOWN_PCT は 0-100 の範囲である必要があります")

        if cls.MAX_POSITIONS < 1:
            errors.append("MAX_POSITIONS は 1 以上である必要があります")

        if cls.GRID_RANGE_FACTOR <= 0 or cls.GRID_RANGE_FACTOR > 1:
            errors.append("GRID_RANGE_FACTOR は 0-1 の範囲である必要があります")

        if cls.CHECK_INTERVAL < 1:
            errors.append("CHECK_INTERVAL は 1 以上である必要があります")

        if cls.TRADING_FEE_RATE < 0:
            errors.append("TRADING_FEE_RATE は 0 以上である必要があります")

        return errors
