"""マルチボットのテスト"""

import threading
import time
from unittest.mock import MagicMock, patch

from src.api_weight import APIWeightTracker
from src.multi_bot import MultiBot


def _make_mock_bot(running=True):
    bot = MagicMock()
    bot.is_running = running
    bot.current_price = 74000.0
    bot.strategy = MagicMock()
    bot.strategy.grids = []
    bot.portfolio = MagicMock()
    bot.portfolio.refresh_stats.return_value = MagicMock(
        total_profit=0.0,
        realized_profit=0.0,
        unrealized_profit=0.0,
    )

    def _get_summary():
        filled = sum(1 for g in bot.strategy.grids if g.position_filled)
        return {
            "running": bot.is_running,
            "price": bot.current_price,
            "grids": len(bot.strategy.grids),
            "filled": filled,
            "total_profit": bot.portfolio.refresh_stats.return_value.total_profit,
            "realized_profit": bot.portfolio.refresh_stats.return_value.realized_profit,
            "unrealized_profit": bot.portfolio.refresh_stats.return_value.unrealized_profit,
        }

    bot.get_summary.side_effect = _get_summary
    bot.stop = MagicMock()
    bot.start = MagicMock()
    return bot


class TestMultiBot:
    def test_start_and_stop(self):
        mb = MultiBot(symbols=["BTCUSDT"])

        with patch("src.bot.GridBot") as MockBot:
            mock_bot = _make_mock_bot()
            MockBot.return_value = mock_bot
            mock_bot.start.side_effect = Exception("stop loop")

            with patch("src.multi_bot.BinanceWebSocketClient"):
                t = threading.Thread(target=mb.start_all, daemon=True)
                t.start()
                time.sleep(0.5)
                mb.stop_all(timeout=5)
                t.join(timeout=5)

        mock_bot.stop.assert_called()

    def test_multiple_symbols(self):
        mb = MultiBot(symbols=["ETHUSDT", "BNBUSDT"])

        with patch("src.bot.GridBot") as MockBot:
            bot1 = _make_mock_bot()
            bot2 = _make_mock_bot()
            MockBot.side_effect = [bot1, bot2]
            bot1.start.side_effect = Exception("stop1")
            bot2.start.side_effect = Exception("stop2")

            with patch("src.multi_bot.BinanceWebSocketClient"):
                t = threading.Thread(target=mb.start_all, daemon=True)
                t.start()
                time.sleep(1)
                mb.stop_all(timeout=5)
                t.join(timeout=5)

        assert len(mb._bots) == 2
        bot1.stop.assert_called()
        bot2.stop.assert_called()

    def test_shared_weight_tracker(self):
        tracker = APIWeightTracker()
        mb = MultiBot(symbols=["BTCUSDT"], weight_tracker=tracker)
        assert mb.weight_tracker is tracker

    def test_error_isolation(self):
        mb = MultiBot(symbols=["FAILCOIN"])

        with patch("src.bot.GridBot") as MockBot:
            MockBot.side_effect = RuntimeError("init failed")

            with patch("src.multi_bot.BinanceWebSocketClient"):
                t = threading.Thread(target=mb.start_all, daemon=True)
                t.start()
                t.join(timeout=3)

        assert len(mb._bots) == 0
        assert len(mb._errors["FAILCOIN"]) > 0

    def test_stop_all_timeout(self):
        mb = MultiBot(symbols=["BTCUSDT"])

        with patch("src.bot.GridBot") as MockBot:
            mock_bot = _make_mock_bot()
            mock_bot.start.side_effect = Exception("stop loop")
            MockBot.return_value = mock_bot

            with patch("src.multi_bot.BinanceWebSocketClient"):
                t = threading.Thread(target=mb.start_all, daemon=True)
                t.start()
                time.sleep(0.5)

                start = time.time()
                mb.stop_all(timeout=2)
                elapsed = time.time() - start

                t.join(timeout=5)
                assert elapsed < 5

    def test_get_status(self):
        mb = MultiBot(symbols=["BTCUSDT", "ETHUSDT"])

        with patch("src.bot.GridBot") as MockBot:
            grid = MagicMock()
            grid.position_filled = True
            bot1 = _make_mock_bot()
            bot1.strategy.grids = [grid, MagicMock(position_filled=False)]
            MockBot.side_effect = [bot1, RuntimeError("eth fail")]

            with patch("src.multi_bot.BinanceWebSocketClient"):
                t = threading.Thread(target=mb.start_all, daemon=True)
                t.start()
                time.sleep(0.5)

                status = mb.get_status()
                assert status["symbols"]["BTCUSDT"]["running"] is True
                assert status["symbols"]["BTCUSDT"]["filled"] == 1
                assert status["symbols"]["BTCUSDT"]["grids"] == 2
                assert "total_profit" in status["symbols"]["BTCUSDT"]
                assert status["symbols"]["ETHUSDT"]["running"] is False
                assert len(status["symbols"]["ETHUSDT"]["errors"]) > 0
                assert "weight" in status
                assert "current_weight" in status["weight"]

                mb.stop_all(timeout=5)
                t.join(timeout=5)
