"""ヘルスチェックスクリプト

ファイルの役割: Docker HEALTHCHECK / 外形監視用にボットの稼働状態を確認
なぜ存在するか: DBファイルの存在確認だけではボットのフリーズを検知できないため
関連ファイル: Dockerfile（HEALTHCHECK命令）, bot.py（状態確認）
"""

import sys
from pathlib import Path

DB_PATH = Path("data") / "bot_state.db"
HEALTH_FILE = Path("data") / ".health"
STALE_THRESHOLD_SECONDS = 300


def main():
    if not DB_PATH.exists():
        print("UNHEALTHY: DBファイルが存在しません")
        sys.exit(1)

    db_mtime = DB_PATH.stat().st_mtime
    import time

    stale_seconds = time.time() - db_mtime
    if stale_seconds > STALE_THRESHOLD_SECONDS:
        print(f"UNHEALTHY: DB更新が {stale_seconds:.0f}秒前（閾値: {STALE_THRESHOLD_SECONDS}秒）")
        sys.exit(1)

    if HEALTH_FILE.exists():
        health_mtime = HEALTH_FILE.stat().st_mtime
        health_age = time.time() - health_mtime
        if health_age > STALE_THRESHOLD_SECONDS:
            print(f"UNHEALTHY: ヘルスファイルが {health_age:.0f}秒前（ボット応答なし）")
            sys.exit(1)

    print(f"HEALTHY: DB更新 {stale_seconds:.0f}秒前")
    sys.exit(0)


if __name__ == "__main__":
    main()
