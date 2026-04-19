import sqlite3
import os

db_path = r"C:\gemini-thinkpad\binance-grid-bot\data\bot_state.db"
if not os.path.exists(db_path):
    print("No DB")
    exit()

conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cur.fetchall()
print("Tables:", [t[0] for t in tables])

for t in tables:
    name = t[0]
    print(f"\n=== {name} ===")
    cur.execute(f"SELECT * FROM {name} LIMIT 3")
    rows = cur.fetchall()
    for r in rows:
        print(r)

conn.close()
