import sqlite3
import pandas as pd

db_path = "data/bot_state.db"
conn = sqlite3.connect(db_path)

# トレード履歴を取得
trades = pd.read_sql_query("SELECT * FROM trades", conn)
print("--- Recent Trades ---")
print(trades[['side', 'price', 'quantity', 'profit', 'matched']].tail(10))

# 実現利益の合計を確認
total_profit = trades['profit'].sum()
print(f"\nCalculated Total Realized Profit: {total_profit:.2f} JPY")

conn.close()
