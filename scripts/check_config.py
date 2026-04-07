from app.config import settings
print("exchange_quote:", settings.exchange_quote_currency)
print("quote_currency:", settings.quote_currency)
print("display_currency:", settings.display_currency)
for k, v in sorted(settings.binance_symbols.items()):
    print(f"  {k}: {v}")
