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

# Test order (test endpoint - no real order)
timestamp = int(time.time() * 1000)
params = {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "type": "MARKET",
    "quoteOrderQty": "11.00",
    "timestamp": str(timestamp)
}
query = urllib.parse.urlencode(params)
signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
url = f"https://api.binance.com/api/v3/order/test?{query}&signature={signature}"

try:
    req = urllib.request.Request(url, method="POST")
    req.add_header("X-MBX-APIKEY", api_key)
    resp = urllib.request.urlopen(req, timeout=10)
    print(f"TEST ORDER OK: {resp.read().decode()}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"TEST ORDER error {e.code}: {body}")
except Exception as e:
    print(f"TEST ORDER exception: {e}")

# Also try real order endpoint to see exact error
timestamp2 = int(time.time() * 1000)
params2 = {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "type": "MARKET",
    "quoteOrderQty": "11.00",
    "timestamp": str(timestamp2)
}
query2 = urllib.parse.urlencode(params2)
signature2 = hmac.new(api_secret.encode(), query2.encode(), hashlib.sha256).hexdigest()
url2 = f"https://api.binance.com/api/v3/order?{query2}&signature={signature2}"

try:
    req2 = urllib.request.Request(url2, method="POST")
    req2.add_header("X-MBX-APIKEY", api_key)
    resp2 = urllib.request.urlopen(req2, timeout=10)
    print(f"REAL ORDER OK: {resp2.read().decode()}")
except urllib.error.HTTPError as e2:
    body2 = e2.read().decode()
    print(f"REAL ORDER error {e2.code}: {body2}")
except Exception as e2:
    print(f"REAL ORDER exception: {e2}")
