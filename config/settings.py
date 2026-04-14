"""
ファイルパス: config/settings.py
概要: グリッド取引ボットの設定管理
説明: 環境変数から設定を読み込み、取引パラメータを提供する
関連ファイル: .env.example, src/bot.py
"""

import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()


def _safe_float(value: Optional[str]) -> Optional[float]:
    """環境変数を安全にfloatに変換"""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class Settings:
    """取引ボットの設定を管理するクラス"""

    # Binance API
    BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")
    USE_TESTNET: bool = os.getenv("USE_TESTNET", "true").lower() == "true"

    # 取引設定
    TRADING_SYMBOL: str = os.getenv("TRADING_SYMBOL", "BTCUSDT")
    GRID_COUNT: int = int(os.getenv("GRID_COUNT", "10"))
    LOWER_PRICE: Optional[float] = _safe_float(os.getenv("LOWER_PRICE"))
    UPPER_PRICE: Optional[float] = _safe_float(os.getenv("UPPER_PRICE"))
    INVESTMENT_AMOUNT: float = float(os.getenv("INVESTMENT_AMOUNT", "100"))

    # リスク管理
    STOP_LOSS_PERCENTAGE: float = float(os.getenv("STOP_LOSS_PERCENTAGE", "5"))
    MAX_POSITIONS: int = int(os.getenv("MAX_POSITIONS", "5"))

    # ボット動作設定
    CHECK_INTERVAL: int = int(os.getenv("CHECK_INTERVAL", "10"))
    STATUS_DISPLAY_INTERVAL: int = int(os.getenv("STATUS_DISPLAY_INTERVAL", "60"))
    MAX_CONSECUTIVE_ERRORS: int = int(os.getenv("MAX_CONSECUTIVE_ERRORS", "5"))
    GRID_RANGE_FACTOR: float = float(os.getenv("GRID_RANGE_FACTOR", "0.15"))
    TRADING_FEE_RATE: float = float(os.getenv("TRADING_FEE_RATE", "0.001"))
    CLOSE_ON_STOP: bool = os.getenv("CLOSE_ON_STOP", "true").lower() == "true"

    @classmethod
    def validate(cls) -> list[str]:
        """設定のバリデーションを行い、エラーリストを返す"""
        errors = []

        if not cls.BINANCE_API_KEY or cls.BINANCE_API_KEY == "your_api_key_here":
            errors.append("BINANCE_API_KEY が設定されていません")

        if not cls.BINANCE_API_SECRET or cls.BINANCE_API_SECRET == "your_api_secret_here":
            errors.append("BINANCE_API_SECRET が設定されていません")

        if cls.GRID_COUNT < 2:
            errors.append("GRID_COUNT は 2 以上である必要があります")

        if cls.INVESTMENT_AMOUNT <= 0:
            errors.append("INVESTMENT_AMOUNT は 0 より大きい必要があります")

        if cls.STOP_LOSS_PERCENTAGE <= 0 or cls.STOP_LOSS_PERCENTAGE > 100:
            errors.append("STOP_LOSS_PERCENTAGE は 0-100 の範囲である必要があります")

        if cls.MAX_POSITIONS < 1:
            errors.append("MAX_POSITIONS は 1 以上である必要があります")

        return errors
