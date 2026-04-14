"""
ファイルパス: src/exporter.py
概要: トレード履歴のエクスポート
説明: 取引記録をCSV/JSON形式でファイルに出力
関連ファイル: src/portfolio.py, src/bot.py
"""

import csv
import json
from pathlib import Path

from src.portfolio import Trade


def export_trades_csv(trades: list[Trade], filepath: str | Path) -> int:
    """トレード履歴をCSVにエクスポート

    Args:
        trades: 取引リスト
        filepath: 出力ファイルパス

    Returns:
        エクスポートした件数
    """
    if not trades:
        return 0

    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "timestamp",
        "symbol",
        "side",
        "price",
        "quantity",
        "order_id",
        "grid_level",
        "profit",
        "matched",
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for trade in trades:
            writer.writerow(
                {
                    "timestamp": trade.timestamp.isoformat(),
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "price": trade.price,
                    "quantity": trade.quantity,
                    "order_id": trade.order_id,
                    "grid_level": trade.grid_level,
                    "profit": trade.profit,
                    "matched": trade.matched,
                }
            )

    return len(trades)


def export_trades_json(trades: list[Trade], filepath: str | Path) -> int:
    """トレード履歴をJSONにエクスポート

    Args:
        trades: 取引リスト
        filepath: 出力ファイルパス

    Returns:
        エクスポートした件数
    """
    if not trades:
        return 0

    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    data = [
        {
            "timestamp": t.timestamp.isoformat(),
            "symbol": t.symbol,
            "side": t.side,
            "price": t.price,
            "quantity": t.quantity,
            "order_id": t.order_id,
            "grid_level": t.grid_level,
            "profit": t.profit,
            "matched": t.matched,
        }
        for t in trades
    ]

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return len(data)
