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

# Test 1: server time (no auth needed)
try:
    req = urllib.request.Request("https://api.binance.com/api/v3/time")
    resp = urllib.request.urlopen(req, timeout=10)
    server_time = json.loads(resp.read())
    print(f"Server time: {server_time}")
except Exception as e:
    print(f"Server time error: {e}")

# Test 2: account info (auth needed)
timestamp = int(time.time() * 1000)
query = f"timestamp={timestamp}"
signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
url = f"https://api.binance.com/api/v3/account?{query}&signature={signature}"

try:
    req = urllib.request.Request(url)
    req.add_header("X-MBX-APIKEY", api_key)
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    # only print non-zero balances
    balances = [b for b in data.get("balances", []) if float(b["free"]) > 0 or float(b["locked"]) > 0]
    print(f"Account OK, permissions: {data.get('permissions')}")
    print(f"Non-zero balances: {balances[:10]}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"Account error {e.code}: {body}")
except Exception as e:
    print(f"Account error: {e}")
