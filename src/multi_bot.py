"""
ファイルパス: src/multi_bot.py
概要: マルチペア対応ボット
説明: 複数の通貨ペアで同時にグリッド取引を実行
関連ファイル: src/bot.py, config/settings.py
"""

import threading
import time
from unittest.mock import patch

from config.settings import Settings
from src.binance_client import BinanceClient
from utils.logger import setup_logger

logger = setup_logger("multi_bot")


class MultiBot:
    """マルチペアグリッドボット"""

    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self._bots = []
        self._threads: list[threading.Thread] = []

    def start_all(self):
        """全ペアのボットを開始"""
        from src.bot import GridBot

        for symbol in self.symbols:
            logger.info(f"ペア {symbol} のボットを起動中...")
            try:
                with patch("config.settings.Settings.TRADING_SYMBOL", symbol):
                    bot = GridBot()
                t = threading.Thread(target=bot.start, daemon=True)
                t.start()
                self._threads.append(t)
                self._bots.append(bot)
            except Exception as e:
                logger.error(f"ペア {symbol} の起動に失敗: {e}")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("全ボットを停止中...")
            for bot in self._bots:
                bot.stop()
            logger.info("全ボット停止完了")
