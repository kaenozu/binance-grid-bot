"""ロギング設定

ファイルの役割: アプリケーション全体のログ設定を統一
なぜ存在するか: ログ出力の一貫性・フォーマット統一のため
関連ファイル: 全モジュール（logger使用）
"""

import datetime
import logging
import os
import sys
from logging.handlers import RotatingFileHandler, BaseRotatingHandler
from pathlib import Path


class HumanFormatter(logging.Formatter):
    """人間可読のログフォーマッタ"""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname
        msg = record.getMessage()
        module = record.module

        color = self.COLORS.get(level, "")
        reset = self.RESET if color else ""

        if os.environ.get("NO_COLOR") or not sys.stderr.isatty():
            return f"{ts} [{level:>8}] {module}: {msg}"
        return f"{ts} {color}[{level:>8}]{reset} {module}: {msg}"


class WindowsSafeRotatingFileHandler(RotatingFileHandler):
    """Windows でファイルロック時にローテーション失敗しないハンドラ"""

    def rotate(self, source, dest):
        try:
            super().rotate(source, dest)
        except PermissionError:
            # 別プロセスが掴んでいる場合はローテーションをスキップ（追記し続ける）
            pass

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            # ローテーション失敗時は現在のファイルに追記し続ける
            pass


class FileFormatter(logging.Formatter):
    """ファイル用フォーマッタ（色なし・ミリ秒付き）"""

    def format(self, record):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        return f"{ts} [{record.levelname:>8}] {record.module}: {record.getMessage()}"


def setup_logger(name: str = "grid_bot") -> logging.Logger:
    """ロガーを設定して返す"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    logger.propagate = False

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(HumanFormatter())
    logger.addHandler(console_handler)

    in_pytest = os.environ.get("PYTEST_CURRENT_TEST") is not None
    if not in_pytest:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "grid_bot.log"
        file_handler = WindowsSafeRotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(FileFormatter())
        logger.addHandler(file_handler)

    return logger
