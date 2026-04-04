import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.database import SessionLocal
from app.models import UserAPIKey
from app.services.auth import APIKeyService

s = SessionLocal()
svc = APIKeyService()
for k in s.query(UserAPIKey).all():
    secret = svc.get_decrypted_secret(k)
    print(f"user_id={k.user_id}")
    print(f"  api_key={k.api_key}")
    print(f"  secret_len={len(secret)}")
    print(f"  secret_start={secret[:10]}")
    print(f"  secret_end={secret[-10:]}")
    print(f"  encrypted_hex_len={len(k.api_secret_encrypted)}")
s.close()
