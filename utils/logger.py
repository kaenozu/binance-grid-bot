"""ロギング設定（JSON形式）

ファイルの役割: アプリケーション全体のログ設定を統一
なぜ存在するか: ログ出力の一貫性・フォーマット統一のため
関連ファイル: 全モジュール（logger使用）
"""

import datetime
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class JsonFormatter(logging.Formatter):
    """JSON形式のログフォーマッタ"""

    def format(self, record):
        log_record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        return json.dumps(log_record, ensure_ascii=False)


def setup_logger(name: str = "grid_bot") -> logging.Logger:
    """ロガーを設定して返す"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    logger.propagate = False
    formatter = JsonFormatter()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    in_pytest = os.environ.get("PYTEST_CURRENT_TEST") is not None
    if not in_pytest:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "grid_bot.log"
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
