"""
ファイルパス: src/api_weight.py
概要: Binance API ウェイト管理
説明: リクエストウェイトを追跡し、レートリミットを予防。スレッドセーフ。
関連ファイル: src/binance_client.py, src/multi_bot.py
"""

import threading
import time
from utils.logger import setup_logger

logger = setup_logger("api_weight")

MAX_WEIGHT = 1200
WEIGHT_BUFFER = 200


class APIWeightTracker:
    """Binance API ウェイト追跡（スレッドセーフ）"""

    def __init__(
        self,
        max_weight: int = MAX_WEIGHT,
        weight_buffer: int = WEIGHT_BUFFER,
        window_seconds: int = 60,
    ):
        self.max_weight = max_weight
        self.weight_buffer = weight_buffer
        self.window_seconds = window_seconds
        self._current_weight = 0
        self._last_reset = time.time()
        self._lock = threading.Lock()

    def update_weight(self, used_weight: int):
        """ウェイト使用量を更新"""
        with self._lock:
            now = time.time()
            if now - self._last_reset >= self.window_seconds:
                self._current_weight = 0
                self._last_reset = now

            self._current_weight = used_weight

    @property
    def available_weight(self) -> int:
        """利用可能ウェイト"""
        with self._lock:
            available = self.max_weight - self._current_weight - self.weight_buffer
            return max(0, available)

    def should_wait(self) -> bool:
        """ウェイト不足で待機すべきか"""
        return self.available_weight <= 0

    def wait_if_needed(self):
        """必要に応じてウェイトリセットまで待機"""
        if not self.should_wait():
            return

        with self._lock:
            elapsed = time.time() - self._last_reset
            reset_in = max(0, self.window_seconds - elapsed)

            if reset_in > 0:
                logger.warning(
                    f"APIウェイト不足 (残り {self._current_weight}/{self.max_weight})。"
                    f"{reset_in}秒後にリセットされます。待機中..."
                )
                self._lock.release()
                time.sleep(reset_in + 1)
                self._lock.acquire()

            self._current_weight = 0
            self._last_reset = time.time()
            logger.info("APIウェイトリセット完了")

    @property
    def info(self) -> dict:
        with self._lock:
            return {
                "current_weight": self._current_weight,
                "max_weight": self.max_weight,
                "available_weight": self.max_weight - self._current_weight - self.weight_buffer,
                "buffer": self.weight_buffer,
            }
