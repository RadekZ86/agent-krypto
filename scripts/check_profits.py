import sqlite3
c = sqlite3.connect("agent_krypto.db").cursor()

c.execute("SELECT COUNT(*), SUM(profit) FROM simulated_trades WHERE status='CLOSED'")
r = c.fetchone()
print(f"Closed trades: {r[0]}, Total profit: {r[1]:.2f}")

c.execute("SELECT symbol, profit, buy_price, sell_price, quantity FROM simulated_trades WHERE status='CLOSED' ORDER BY profit DESC LIMIT 10")
print("\nTop 10 most profitable trades:")
for x in c.fetchall():
    print(f"  {x[0]}: profit={x[1]:.2f}  buy={x[2]:.6f}  sell={x[3]:.6f}  qty={x[4]:.6f}")

c.execute("SELECT symbol, profit, buy_price, sell_price, quantity FROM simulated_trades WHERE status='CLOSED' ORDER BY profit ASC LIMIT 10")
print("\nWorst 10 trades:")
for x in c.fetchall():
    print(f"  {x[0]}: profit={x[1]:.2f}  buy={x[2]:.6f}  sell={x[3]:.6f}  qty={x[4]:.6f}")

c.execute("SELECT symbol, buy_price, quantity, buy_value FROM simulated_trades WHERE status='OPEN' ORDER BY buy_value DESC")
print("\nOpen positions:")
for x in c.fetchall():
    print(f"  {x[0]}: buy_price={x[1]:.6f}  qty={x[2]:.6f}  value={x[3]:.2f}")

c.execute("SELECT SUM(buy_value) FROM simulated_trades WHERE status='CLOSED'")
print(f"\nTotal invested (closed): {c.fetchone()[0]:.2f}")

c.execute("SELECT symbol, SUM(profit) as tp, COUNT(*) as cnt FROM simulated_trades WHERE status='CLOSED' GROUP BY symbol ORDER BY tp DESC LIMIT 15")
print("\nProfit by coin (top 15):")
for x in c.fetchall():
    print(f"  {x[0]}: total_profit={x[1]:.2f}  trades={x[2]}")
