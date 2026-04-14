"""
ファイルパス: utils/logger.py
概要: ロギング設定
説明: コンソールとファイルにログを出力する設定を提供
関連ファイル: src/bot.py, main.py
"""

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logger(name: str = "grid_bot") -> logging.Logger:
    """ロガーを設定して返す

    Args:
        name: ロガー名

    Returns:
        設定済みロガー
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # すでにハンドラが設定されている場合はスキップ
    if logger.handlers:
        return logger

    # 親ロガーへの伝播を防止（ログの重複出力を防ぐ）
    logger.propagate = False

    # フォーマット
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # コンソールハンドラ
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # pytest 実行中はファイル出力しない（実運用ログとテスト出力を分離）
    in_pytest = "pytest" in sys.modules or any("pytest" in str(a) for a in sys.argv)
    if not in_pytest:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)

        log_file = log_dir / "grid_bot.log"
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
