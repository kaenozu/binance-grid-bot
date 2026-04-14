"""
ファイルパス: src/risk_manager.py
概要: リスク管理
説明: 損切り、ポジション制限、証拠金管理などのリスク管理機能を提供
関連ファイル: src/binance_client.py, src/grid_strategy.py, src/portfolio.py
"""

from typing import Optional

from config.settings import Settings
from src.binance_client import BinanceClient
from src.grid_strategy import GridStrategy
from utils.logger import setup_logger

logger = setup_logger("risk_manager")


class RiskManager:
    """リスク管理クラス"""

    def __init__(
        self,
        client: BinanceClient,
        strategy: GridStrategy,
        halt_on_out_of_range: bool = False,
    ):
        """
        Args:
            client: Binance API クライアント
            strategy: グリッド戦略
            halt_on_out_of_range: 価格がグリッド範囲外の場合に停止するかどうか
        """
        self.client = client
        self.strategy = strategy
        self.halt_on_out_of_range = halt_on_out_of_range

        # 損切り価格: グリッド下限価格を基準にパーセンテージを下回る
        self.stop_loss_price = self.strategy.lower_price * (1 - Settings.STOP_LOSS_PERCENTAGE / 100)

        # ポジション管理
        self.max_positions = Settings.MAX_POSITIONS
        self.current_positions = 0

        logger.info(
            f"リスク管理初期化: 損切り={self.stop_loss_price:.2f}, "
            f"最大ポジション={self.max_positions}"
        )

    def check_stop_loss(self, current_price: float) -> bool:
        """損切りラインをチェック

        Args:
            current_price: 現在価格

        Returns:
            True: 損切り発動、False: 正常
        """
        if current_price <= self.stop_loss_price:
            logger.warning(
                f"[STOP_LOSS] 損切り発動! 現在価格: {current_price:.2f}, 損切り価格: {self.stop_loss_price:.2f}"
            )
            return True
        return False

    def can_open_position(self) -> bool:
        """新規ポジション可能かチェック

        Returns:
            True: 可能、False: 不可
        """
        if self.current_positions >= self.max_positions:
            logger.warning(f"最大ポジション数到達: {self.current_positions}/{self.max_positions}")
            return False
        return True

    def record_position_open(self):
        """ポジション開設を記録"""
        self.current_positions += 1
        logger.info(f"ポジション開設: {self.current_positions}/{self.max_positions}")

    def record_position_close(self, profit: float = 0.0):
        """ポジション決済を記録

        Args:
            profit: 利益（損失の場合は負の値）
        """
        if self.current_positions > 0:
            self.current_positions -= 1

        logger.info(f"ポジション決済: 利益={profit:.2f}")

    @property
    def risk_status(self) -> dict:
        """リスクステータスを返す"""
        return {
            "stop_loss_price": self.stop_loss_price,
            "current_positions": self.current_positions,
            "max_positions": self.max_positions,
            "stop_loss_percentage": Settings.STOP_LOSS_PERCENTAGE,
        }

    def should_halt_trading(self, current_price: float) -> bool:
        """取引停止すべきか判断

        Args:
            current_price: 現在価格

        Returns:
            True: 停止すべき、False: 継続
        """
        # 損切りチェック
        if self.check_stop_loss(current_price):
            return True

        # グリッド範囲外チェック（設定可能な動作）
        if not self.strategy.is_within_grid_range(current_price):
            logger.warning(f"価格がグリッド範囲外: {current_price:.2f}")
            return self.halt_on_out_of_range

        return False
