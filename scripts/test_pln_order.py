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

# Test order BTCPLN
ts = str(int(time.time() * 1000))
params = {"symbol": "BTCPLN", "side": "BUY", "type": "MARKET", "quoteOrderQty": "50.00", "timestamp": ts}
q = urllib.parse.urlencode(params)
sig = hmac.new(api_secret.encode(), q.encode(), hashlib.sha256).hexdigest()
url = f"https://api.binance.com/api/v3/order/test?{q}&signature={sig}"
req = urllib.request.Request(url, method="POST")
req.add_header("X-MBX-APIKEY", api_key)
try:
    resp = urllib.request.urlopen(req, timeout=10)
    print(f"TEST ORDER BTCPLN OK: {resp.read().decode()}")
except urllib.error.HTTPError as e:
    print(f"TEST ORDER BTCPLN error {e.code}: {e.read().decode()}")

# Test order ETHPLN
ts2 = str(int(time.time() * 1000))
params2 = {"symbol": "ETHPLN", "side": "BUY", "type": "MARKET", "quoteOrderQty": "50.00", "timestamp": ts2}
q2 = urllib.parse.urlencode(params2)
sig2 = hmac.new(api_secret.encode(), q2.encode(), hashlib.sha256).hexdigest()
url2 = f"https://api.binance.com/api/v3/order/test?{q2}&signature={sig2}"
req2 = urllib.request.Request(url2, method="POST")
req2.add_header("X-MBX-APIKEY", api_key)
try:
    resp2 = urllib.request.urlopen(req2, timeout=10)
    print(f"TEST ORDER ETHPLN OK: {resp2.read().decode()}")
except urllib.error.HTTPError as e2:
    print(f"TEST ORDER ETHPLN error {e2.code}: {e2.read().decode()}")
