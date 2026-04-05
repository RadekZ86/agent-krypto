#!/usr/bin/env python3
"""Diagnose why USDCPLN bridge buy fails."""
import sys, os
sys.path.insert(0, ".")
os.environ.setdefault("DATABASE_URL", "sqlite:///./agent_krypto.db")

from app.services.binance_api import BinanceService
from app.services.auth import APIKeyService
from app.database import SessionLocal
from app.models import User, UserAPIKey
from sqlalchemy import select

session = SessionLocal()
bs = BinanceService()
aks = APIKeyService()

user = session.execute(select(User).where(User.username == "radek")).scalar_one()
keys = aks.get_user_api_keys(session, user.id)
tk = next(k for k in keys if k.is_active and not k.is_testnet and k.permissions in ("trade", "trading"))
secret = aks.get_decrypted_secret(tk)
client = bs.get_client(api_key=tk.api_key, api_secret=secret, testnet=False)

# 1. Check PLN balance
balances = client.get_balances()
for b in balances:
    if b.get("asset") == "PLN":
        print(f"PLN: free={b['free']}, locked={b['locked']}")
    if b.get("asset") == "USDC":
        print(f"USDC: free={b['free']}, locked={b['locked']}")

# 2. Check tradeable pairs for USDC
pairs = client.get_tradeable_pairs()
usdc_quotes = pairs.get("USDC", [])
print(f"\nUSDC tradeable quotes: {usdc_quotes}")

# 3. Get exchange info for USDCPLN
info = client._request("GET", "/api/v3/exchangeInfo", {"symbol": "USDCPLN"})
if "error" in info:
    print(f"\nUSDCPLN exchangeInfo error: {info['error']}")
else:
    for sym in info.get("symbols", []):
        if sym["symbol"] == "USDCPLN":
            print(f"\nUSDCPLN status: {sym['status']}")
            print(f"  baseAsset: {sym['baseAsset']}, quoteAsset: {sym['quoteAsset']}")
            print(f"  orderTypes: {sym.get('orderTypes')}")
            print(f"  quoteOrderQtyMarketAllowed: {sym.get('quoteOrderQtyMarketAllowed')}")
            for f in sym.get("filters", []):
                ft = f.get("filterType")
                if ft in ("LOT_SIZE", "NOTIONAL", "MIN_NOTIONAL", "MARKET_LOT_SIZE"):
                    print(f"  filter {ft}: {f}")

# 4. Try a small test order
print("\n--- Test order: BUY USDCPLN quoteOrderQty=30 PLN ---")
test = client.create_test_order(
    symbol="USDCPLN", side="BUY", order_type="MARKET", quote_quantity=30.0
)
print(f"Test order result: {test}")

# 5. Try actual market BUY with 30 PLN
print("\n--- REAL order: BUY USDCPLN quoteOrderQty=30 PLN ---")
real = client.create_order(symbol="USDCPLN", side="BUY", order_type="MARKET", quote_quantity=30.0)
print(f"Real order result: {real}")

session.close()
