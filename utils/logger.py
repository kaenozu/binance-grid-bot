"""
ファイルパス: utils/logger.py
概要: ロギング設定
説明: コンソールとファイルにログを出力する設定を提供
関連ファイル: src/bot.py, main.py
"""

import logging
import sys
from datetime import datetime
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
    
    # フォーマット
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # コンソールハンドラ
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # ファイルハンドラ（logs ディレクトリ）
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f"grid_bot_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger
