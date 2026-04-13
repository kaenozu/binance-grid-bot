"""
ファイルパス: utils/__init__.py
概要: utils パッケージの初期化
説明: ユーティリティモジュールの公開APIを定義
関連ファイル: utils/logger.py
"""

from utils.logger import setup_logger

__all__ = ["setup_logger"]
