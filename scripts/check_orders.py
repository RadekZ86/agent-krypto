#!/usr/bin/env python3
import sqlite3

db = sqlite3.connect("agent_krypto.db")
db.row_factory = sqlite3.Row

# List all tables
tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Tables:", tables)

# Create live_order_log if missing
if "live_order_log" not in tables:
    db.execute("""CREATE TABLE IF NOT EXISTS live_order_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        username VARCHAR(64),
        symbol VARCHAR(32),
        action VARCHAR(8),
        status VARCHAR(16),
        detail TEXT,
        order_id VARCHAR(64),
        allocation REAL,
        quote_currency VARCHAR(8)
    )""")
    db.commit()
    print("Created live_order_log table")

# Create audit_logs if missing
if "audit_logs" not in tables:
    db.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action VARCHAR(64),
        resource VARCHAR(64) DEFAULT '',
        details TEXT,
        ip_address VARCHAR(45),
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.commit()
    print("Created audit_logs table")

# Create failed_login_attempts if missing
if "failed_login_attempts" not in tables:
    db.execute("""CREATE TABLE IF NOT EXISTS failed_login_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        ip_address VARCHAR(45),
        attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.commit()
    print("Created failed_login_attempts table")

print("\n=== LATEST LIVE ORDERS ===")
rows = db.execute(
    "SELECT created_at, symbol, action, status, detail, allocation, quote_currency "
    "FROM live_order_log ORDER BY created_at DESC LIMIT 25"
).fetchall()
if not rows:
    print("(no orders yet)")
for r in rows:
    print(f"{r[0]} | {r[1]:12s} | {r[2]:4s} | {r[3]:6s} | alloc={r[5]} {r[6]} | {r[4]}")

db.close()
