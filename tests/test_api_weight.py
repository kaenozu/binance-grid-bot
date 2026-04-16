"""APIWeightTracker のテスト"""

import threading
import time
from unittest.mock import patch

import pytest

from src.api_weight import APIWeightTracker


class TestAPIWeightTracker:
    def test_update_weight(self):
        tracker = APIWeightTracker(max_weight=1200, weight_buffer=200)
        tracker.update_weight(100)
        assert tracker.available_weight == 900

    def test_should_wait(self):
        tracker = APIWeightTracker(max_weight=1200, weight_buffer=200)
        assert tracker.available_weight == 1000
        assert tracker.should_wait() is False
        tracker.update_weight(1000)
        assert tracker.available_weight == 0
        assert tracker.should_wait() is True
        tracker.update_weight(1001)
        assert tracker.should_wait() is True

    @pytest.mark.slow
    def test_window_reset(self):
        """window_seconds のリセットをモック時間でテスト。"""
        with patch.object(time, "time", return_value=100.0):
            tracker = APIWeightTracker(max_weight=1200, weight_buffer=200, window_seconds=1)
            tracker.update_weight(1000)
            assert tracker.available_weight == 0

        # 時間経過後にリセットされることを確認
        with patch.object(time, "time", return_value=101.5):
            tracker.update_weight(50)
        assert tracker.available_weight == 950

    def test_wait_if_needed_resets_weight(self):
        tracker = APIWeightTracker(max_weight=1200, weight_buffer=200, window_seconds=1)
        tracker.update_weight(1001)
        assert tracker.should_wait()

        # wait_if_neededの待機をモック
        with patch.object(tracker._condition, "wait"):
            tracker.wait_if_needed()
        assert tracker._current_weight == 0

    def test_thread_safety(self):
        tracker = APIWeightTracker(max_weight=1200, weight_buffer=200)
        errors = []

        def writer():
            try:
                for _ in range(100):
                    tracker.update_weight(10)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    _ = tracker.available_weight
                    _ = tracker.should_wait()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
