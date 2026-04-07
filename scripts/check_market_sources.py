import sqlite3
c = sqlite3.connect("agent_krypto.db").cursor()

# Check market data sources for a few coins
for sym in ["KAS", "MKR", "CRO", "EOS", "MNT", "BTC", "ETH"]:
    c.execute("SELECT source, COUNT(*), MIN(close), MAX(close), AVG(close) FROM market_data WHERE symbol=? GROUP BY source", (sym,))
    rows = c.fetchall()
    print(f"\n{sym}:")
    for r in rows:
        print(f"  source={r[0]}: count={r[1]}, min={r[2]:.6f}, max={r[3]:.6f}, avg={r[4]:.6f}")

# Check latest 5 records for KAS
print("\n\nKAS latest 10 records:")
c.execute("SELECT timestamp, source, close FROM market_data WHERE symbol='KAS' ORDER BY timestamp DESC LIMIT 10")
for r in c.fetchall():
    print(f"  {r[0]} src={r[1]} close={r[2]:.6f}")
