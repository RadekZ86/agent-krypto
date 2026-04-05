"""Check which trading pairs are available for the user's Binance PL account."""
from app.database import SessionLocal
from app.models import User, UserAPIKey
from app.services.auth import APIKeyService
from app.services.binance_api import BinanceService
from sqlalchemy import select

api_key_service = APIKeyService()
binance_service = BinanceService()

with SessionLocal() as s:
    u = s.execute(select(User).where(User.username == "radek")).scalar_one()
    keys = api_key_service.get_user_api_keys(s, u.id)
    trade_key = next((k for k in keys if k.is_active and not k.is_testnet), None)
    secret = api_key_service.get_decrypted_secret(trade_key)
    client = binance_service.get_client(trade_key.api_key, secret, trade_key.is_testnet)

    # Get balances
    balances = client.get_balances()
    print("=== BALANCES ===")
    for b in balances:
        free = float(b.get("free", 0))
        locked = float(b.get("locked", 0))
        if free + locked > 0:
            print(f"  {b['asset']}: free={free} locked={locked}")

    # Get tradeable pairs for key symbols
    pairs = client.get_tradeable_pairs()
    test_symbols = ["BTC", "ETH", "BNB", "SOL", "XRP", "LINK", "AVAX", "DOT", "SHIB", "ARB", "XLM", "HBAR", "MKR", "EOS", "CRO", "ADA", "DOGE"]
    print("\n=== TRADEABLE PAIRS ===")
    for sym in test_symbols:
        quotes = pairs.get(sym, [])
        print(f"  {sym}: {quotes}")

    # Count total symbols with PLN pairs
    pln_pairs = [sym for sym, qs in pairs.items() if "PLN" in qs]
    print(f"\n=== PLN pairs count: {len(pln_pairs)} ===")
    print(f"  {sorted(pln_pairs)}")

    usdt_pairs = [sym for sym, qs in pairs.items() if "USDT" in qs]
    print(f"\n=== USDT pairs count: {len(usdt_pairs)} ===")
