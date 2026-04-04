#!/usr/bin/env python3
"""Debug portfolio value calculation."""
import sys, os, json
APP_DIR = '/usr/home/MagicParty/domains/magicparty.usermd.net/public_python'
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

from app.database import SessionLocal
from app.models import User
from app.services.auth import APIKeyService
from app.services.binance_api import BinanceService
from sqlalchemy import select

aks = APIKeyService()
bs = BinanceService()
with SessionLocal() as session:
    user = session.execute(select(User).where(User.username == 'radek')).scalar_one_or_none()
    if not user:
        print('No user radek')
        sys.exit(1)
    keys = aks.get_user_api_keys(session, user.id)
    trade_key = next((k for k in keys if k.is_active and not k.is_testnet), None)
    if not trade_key:
        print('No active key')
        sys.exit(1)
    secret = aks.get_decrypted_secret(trade_key)
    client = bs.get_client(api_key=trade_key.api_key, api_secret=secret, testnet=False)
    
    # Get raw balances
    balances = client.get_balances()
    print("=== RAW BALANCES ===")
    for b in balances:
        free = float(b.get('free', 0))
        locked = float(b.get('locked', 0))
        if free + locked > 0:
            print(f"  {b['asset']:10s} free={free:15.8f}  locked={locked:15.8f}")
    
    # Get portfolio value in PLN
    p = client.get_portfolio_value('PLN')
    print("\n=== PORTFOLIO (PLN) ===")
    print(f"Total: {p.get('total_value', 0):.2f} PLN")
    for h in p.get('holdings', []):
        print(f"  {h['asset']:10s} total={h['total']:15.8f}  value={h['value']:.2f} PLN")
