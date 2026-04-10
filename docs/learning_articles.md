# Materialy do nauki agenta

Punktem tej listy nie jest kopiowanie cudzych strategii, tylko zbudowanie programu nauki dla agenta.

## 1. RSI: jak czytac momentum

- Zrodlo: Investopedia
- Link: https://www.investopedia.com/terms/r/rsi.asp
- Wniosek dla agenta: RSI < 30 i RSI > 70 to tylko sygnal ostrzegawczy. Agent powinien laczyc RSI z trendem i szukac potwierdzenia, zamiast reagowac automatycznie.

## 2. MACD: potwierdzenie kierunku

- Zrodlo: Investopedia
- Link: https://www.investopedia.com/terms/m/macd.asp
- Wniosek dla agenta: crossover MACD ma sens dopiero wtedy, gdy wspiera go kierunek EMA i wolumen. Sam MACD nie wystarcza w konsolidacji.

## 3. Day trading: plan i dziennik

- Zrodlo: Investopedia
- Link: https://www.investopedia.com/articles/trading/06/daytradingretail.asp
- Wniosek dla agenta: przed realnym tradingiem trzeba przejsc backtest, paper trading, limit strat dziennych i regularny przeglad historii decyzji.

## 4. Zasady dyscypliny inwestycyjnej

- Zrodlo: Investopedia
- Link: https://www.investopedia.com/articles/trading/10/top-ten-rules-for-trading.asp
- Wniosek dla agenta: system nie moze zmieniac zasad pod wplywem jednej straty. Potrzebuje stalego planu wejsc, wyjsc i reakcji na zmiennosc.

## 5. Risk management w krypto

- Zrodlo: Binance Academy
- Link: https://www.binance.com/en/academy/articles/risk-management-in-crypto-trading
- Wniosek dla agenta: pozycja, stop loss, limit ekspozycji i relacja risk-reward sa wazniejsze niz pojedynczy dobry sygnal.

## 6. Support i resistance

- Zrodlo: Binance Academy
- Link: https://www.binance.com/en/academy/articles/support-and-resistance-explained
- Wniosek dla agenta: poziomy dzialaja jako strefy, nie jako pojedyncze kreski. Trzeba obserwowac, czy cena i wolumen potwierdzaja obrone albo wybicie.

## 7. Candlestick context

- Zrodlo: Investopedia
- Link: https://www.investopedia.com/trading/candlestick-charting-what-is-it/
- Wniosek dla agenta: pojedyncza swieca nie jest strategia. Jej znaczenie zalezy od trendu, wolumenu i miejsca na wykresie.

## 8. Volume analysis

- Zrodlo: Investopedia
- Link: https://www.investopedia.com/articles/technical/02/010702.asp
- Wniosek dla agenta: agent powinien odroznic ruch ceny z naplywem kapitalu od pustego podbicia bez uczestnictwa.

## 9. Moving averages jako filtr reżimu

- Zrodlo: Binance Academy
- Link: https://www.binance.com/en/academy/articles/a-guide-to-the-most-common-technical-indicators
- Wniosek dla agenta: EMA20 i EMA50 sa dobrym filtrem trendu, ale nie powinny byc jedynym triggerem wejscia.

---

# Materialy do nauki dzwigni (Leverage / Perpetual)

## 10. Kontrakty perpetual: jak dzialaja

- Zrodlo: Bybit Learn
- Link: https://learn.bybit.com/trading/what-are-perpetual-contracts/
- Wniosek dla agenta: perpetuale to instrumenty bez daty wygasniecia z funding rate co 8h. Pozwalaja na LONG i SHORT z dzwignia. Agent musi rozumiec ze dzwignia mnozy zysk I strate.

## 11. Dzwignia finansowa: jak dobrac poziom

- Zrodlo: Bybit Learn
- Link: https://learn.bybit.com/trading/what-is-leverage-in-trading/
- Wniosek dla agenta: zaczynaj od 2-3x, zwieksaj dopiero po serii wygranych. 10x+ to awansowany poziom wymagajacy strict stop-lossow. Przy 100x nawet 1% ruchu = likwidacja.

## 12. Funding rate: ukryty koszt trzymania

- Zrodlo: Binance Academy
- Link: https://www.binance.com/en/academy/articles/what-are-perpetual-futures-contracts
- Wniosek dla agenta: pozytywny FR = longi placa shortom (rynek przegrzany). Negatywny FR = shorty placa longom (oversold). Agent powinien uwzglednic FR w timing wejscia.

## 13. Likwidacja pozycji: jak sie chronic

- Zrodlo: Bybit Learn
- Link: https://learn.bybit.com/trading/what-is-liquidation-in-trading/
- Wniosek dla agenta: uzywaj isolated margin (nie cross!), stop-loss MUSI byc dalej od wejscia niz liq price. Liq distance = ~1/leverage (np. 10x = liq 10% od wejscia).

## 14. Short selling: zarabianie na spadkach

- Zrodlo: Investopedia
- Link: https://www.investopedia.com/terms/s/shortselling.asp
- Wniosek dla agenta: SHORT przy RSI > 70, MACD bearish, trend DOWN. Zamykaj SHORT przy RSI < 35 lub dywergencji byczej. UWAGA na short squeeze - nagly skok ceny.

## 15. Position sizing z dzwignia

- Zrodlo: Binance Academy
- Link: https://www.binance.com/en/academy/articles/a-complete-guide-to-cryptocurrency-trading-for-beginners
- Wniosek dla agenta: regula = kapital * max_risk% / (stop_loss% * leverage). Przy 10x i 2% SL, max risk 1% = pozycja = 50% konta. Agent nie moze overleverage.

## 10. Dziennik tradingowy i retrospektywa

- Zrodlo: Coinbase Learn
- Link: https://www.coinbase.com/learn/crypto-basics/what-is-risk-management
- Wniosek dla agenta: poza wynikiem trzeba zapisywac powod wejscia, confidence, warunki rynku i powod wyjscia.

## 11. Drawdown management

- Zrodlo: Binance Academy
- Link: https://www.binance.com/en/academy/articles/what-is-a-stop-loss-order
- Wniosek dla agenta: system powinien chronic kapital podczas serii strat i liczyc drawdown dla calego portfela, a nie tylko pojedynczego trade'u.