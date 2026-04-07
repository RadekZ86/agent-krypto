"""Clean up corrupt demo market data and reset paper trades."""
import sqlite3

conn = sqlite3.connect("agent_krypto.db")
c = conn.cursor()

# 1. Delete all demo-source market data (they have wrong base prices)
c.execute("SELECT COUNT(*) FROM market_data WHERE source='demo'")
demo_count = c.fetchone()[0]
c.execute("DELETE FROM market_data WHERE source='demo'")
print(f"Deleted {demo_count} demo market data rows")

# 2. Reset paper trades — close all OPEN, mark everything as corrupt
c.execute("SELECT COUNT(*) FROM simulated_trades")
total_trades = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM simulated_trades WHERE status='OPEN'")
open_trades = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM simulated_trades WHERE status='CLOSED'")
closed_trades = c.fetchone()[0]
print(f"Paper trades: {total_trades} total ({open_trades} OPEN, {closed_trades} CLOSED)")

# Delete all paper trades — they're based on corrupt price data
c.execute("DELETE FROM simulated_trades")
print(f"Deleted all {total_trades} simulated trades (corrupt prices)")

# 3. Reset wallet cash balance to starting amount
c.execute("UPDATE runtime_state SET value='10000' WHERE key='cash_balance'")
print("Reset cash_balance to 10000")

# 4. Reset decisions referencing bad data
c.execute("SELECT COUNT(*) FROM decisions")
dec_count = c.fetchone()[0]
c.execute("DELETE FROM decisions")
print(f"Deleted {dec_count} decisions")

conn.commit()
conn.close()
print("\nDone! Paper trading reset to clean state.")
