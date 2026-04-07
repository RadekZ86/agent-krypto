import sqlite3
c = sqlite3.connect("agent_krypto.db").cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", [r[0] for r in c.fetchall()])

# Check where cash_balance is stored
for tbl in ["runtime_state", "wallet", "settings", "app_state"]:
    try:
        c.execute(f"SELECT * FROM {tbl} LIMIT 3")
        print(f"\n{tbl}:", c.fetchall())
    except:
        pass
