import sys, os, time, hmac, hashlib
import urllib.request, urllib.parse, json

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

# Get account to see permissions and trading groups
timestamp = int(time.time() * 1000)
query = f"timestamp={timestamp}"
signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
url = f"https://api.binance.com/api/v3/account?{query}&signature={signature}"

req = urllib.request.Request(url)
req.add_header("X-MBX-APIKEY", api_key)
resp = urllib.request.urlopen(req, timeout=10)
data = json.loads(resp.read())
print(f"Permissions: {data.get('permissions')}")
print(f"Account type: {data.get('accountType')}")

# Get exchange info to find which symbols are in the user's trading groups
resp2 = urllib.request.urlopen("https://api.binance.com/api/v3/exchangeInfo", timeout=15)
info = json.loads(resp2.read())

user_perms = set(data.get("permissions", []))
print(f"\nUser trading groups: {user_perms}")

# Find symbols available for this user
available = []
for sym in info.get("symbols", []):
    sym_perms = set(sym.get("permissions", []) + sym.get("permissionSets", [[]])[0] if isinstance(sym.get("permissionSets", [[]])[0], list) else sym.get("permissions", []))
    # Check permissionSets (new format)
    psets = sym.get("permissionSets", [])
    for pset in psets:
        if isinstance(pset, list):
            for p in pset:
                if p in user_perms:
                    if sym["quoteAsset"] in ("USDT", "PLN"):
                        available.append(f"{sym['symbol']} (quote={sym['quoteAsset']}, status={sym['status']})")
                    break

print(f"\nAvailable USDT/PLN pairs count: {len(available)}")
# Show first 30
for a in sorted(available)[:30]:
    print(f"  {a}")
print(f"  ... and {max(0, len(available)-30)} more")

# Specifically check PLN pairs
pln_pairs = [a for a in available if "PLN" in a]
print(f"\nPLN pairs ({len(pln_pairs)}):")
for p in pln_pairs:
    print(f"  {p}")
