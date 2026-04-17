"""マルチペア対応ボット

ファイルの役割: 複数のシンボルに対してボットを並列で管理
なぜ存在するか: 単一Botは1つのシンボルのみ対応するため、複数Botを統合管理するため
関連ファイル: bot.py（単一Bot）, settings.py（設定）
"""

import threading
import time
from collections import deque
from typing import TYPE_CHECKING

from src.api_weight import APIWeightTracker
from src.ws_client import BinanceWebSocketClient
from utils.logger import setup_logger

if TYPE_CHECKING:
    from src.bot import GridBot

logger = setup_logger("multi_bot")


class MultiBot:
    """マルチペアグリッドボット"""

    def __init__(
        self,
        symbols: list[str],
        weight_tracker: APIWeightTracker | None = None,
    ):
        self.symbols = symbols
        self.weight_tracker = weight_tracker or APIWeightTracker()
        self._bots: dict[str, GridBot] = {}  # type: ignore[name-defined]
        self._threads: list[threading.Thread] = []
        self._shutdown_event = threading.Event()
        self._stop_done = False
        self._errors: dict[str, deque] = {s: deque(maxlen=100) for s in symbols}

    def start_all(self):
        """全ペアのボットを開始"""
        from src.bot import GridBot

        for symbol in self.symbols:
            logger.info(f"ペア {symbol} のボットを起動中...")
            try:
                ws_client = BinanceWebSocketClient()
                bot = GridBot(
                    symbol=symbol,
                    ws_client=ws_client,
                    weight_tracker=self.weight_tracker,
                )
                t = threading.Thread(target=self._run_bot, args=(bot, symbol), daemon=True)
                t.start()
                self._threads.append(t)
                self._bots[symbol] = bot
            except Exception as e:
                self._errors[symbol].append(str(e))
                logger.error(f"ペア {symbol} の起動に失敗: {e}")

        logger.info(f"全ボット起動完了: {len(self._bots)}/{len(self.symbols)}")

        try:
            while not self._shutdown_event.is_set():
                self._shutdown_event.wait(timeout=1)
        except KeyboardInterrupt:
            logger.info("全ボットを停止中...")

        self._stop_done = False
        self.stop_all()
        logger.info("全ボット停止完了")

    def _run_bot(self, bot, symbol: str):
        max_retries = 10
        retry_count = 0
        while not self._shutdown_event.is_set():
            try:
                bot.start()
                retry_count = 0
            except Exception as e:
                retry_count += 1
                self._errors[symbol].append(str(e))
                logger.error(f"ペア {symbol} エラー (リトライ {retry_count}/{max_retries}): {e}")
                if retry_count >= max_retries:
                    logger.critical(
                        f"ペア {symbol}: 連続失敗 {max_retries} 回。全ボットを停止します。"
                    )
                    self._bots.pop(symbol, None)
                    self._shutdown_event.set()
                    break
                if not self._shutdown_event.is_set():
                    time.sleep(5)

    def stop(self, timeout: float = 30):
        """全ボットを停止（stop_all のエイリアス）"""
        self.stop_all(timeout)

    def stop_all(self, timeout: float = 30):
        """全ボットを停止

        Args:
            timeout: タイムアウト秒数
        """
        self._shutdown_event.set()
        if self._stop_done:
            return
        self._stop_done = True
        for bot in self._bots.values():
            try:
                bot.stop()
            except Exception as e:
                logger.error(f"ボット停止エラー: {e}")

        deadline = time.time() + timeout
        for t in self._threads:
            remaining = max(0, deadline - time.time())
            t.join(timeout=remaining)

    def get_status(self) -> dict:
        """集約ステータスを返す"""
        statuses = {}
        for symbol in self.symbols:
            bot = self._bots.get(symbol)
            if bot:
                summary = bot.get_summary()
                statuses[symbol] = {
                    "running": summary["running"],
                    "price": summary["price"],
                    "grids": summary["grids"],
                    "filled": summary["filled"],
                    "total_profit": summary["total_profit"],
                    "errors": self._errors.get(symbol, []),
                }
            else:
                statuses[symbol] = {
                    "running": False,
                    "errors": self._errors.get(symbol, []),
                }
        return {
            "symbols": statuses,
            "weight": self.weight_tracker.info,
        }
