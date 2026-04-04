import sys, time, hmac, hashlib, urllib.request, urllib.parse, json

sys.path.insert(0, ".")
from app.database import SessionLocal
from app.models import UserAPIKey
from app.services.auth import APIKeyService

s = SessionLocal()
svc = APIKeyService()
k = s.query(UserAPIKey).first()
api_key = k.api_key
api_secret = svc.get_decrypted_secret(k)
s.close()

# Get exchange info for BTCPLN and ETHPLN
url = "https://api.binance.com/api/v3/exchangeInfo?symbols=[%22BTCPLN%22,%22ETHPLN%22,%22USDCPLN%22]"
req = urllib.request.Request(url)
resp = urllib.request.urlopen(req, timeout=10)
data = json.loads(resp.read())

for sym in data.get("symbols", []):
    print(f"\n=== {sym['symbol']} ===")
    print(f"  status: {sym['status']}")
    print(f"  baseAsset: {sym['baseAsset']}, quoteAsset: {sym['quoteAsset']}")
    for f in sym.get("filters", []):
        ftype = f.get("filterType")
        if ftype in ("NOTIONAL", "MIN_NOTIONAL", "LOT_SIZE", "MARKET_LOT_SIZE", "PRICE_FILTER"):
            print(f"  {ftype}: {f}")

# Also check balance
timestamp = int(time.time() * 1000)
query = f"timestamp={timestamp}"
signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
url2 = f"https://api.binance.com/api/v3/account?{query}&signature={signature}"
req2 = urllib.request.Request(url2)
req2.add_header("X-MBX-APIKEY", api_key)
resp2 = urllib.request.urlopen(req2, timeout=10)
account = json.loads(resp2.read())
for b in account.get("balances", []):
    free = float(b.get("free", 0))
    locked = float(b.get("locked", 0))
    if free > 0 or locked > 0:
        print(f"\nBalance: {b['asset']} free={free} locked={locked}")
