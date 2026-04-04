# 🤖 Agent Krypto – System Uczący się (MVP → Produkcja)

## 🎯 CEL PROJEKTU

Zbudować agenta, który:
- analizuje rynek kryptowalut
- uczy się na danych historycznych i bieżących
- symuluje trading (bez ryzyka)
- podejmuje decyzje BUY / SELL / HOLD
- przygotowuje się do realnego tradingu (np. Binance)

---

## 🧠 FILOZOFIA SYSTEMU

❌ NIE:
- nie zgaduje rynku
- nie „wróży” cen

✅ TAK:
- analizuje dane
- testuje strategie
- uczy się na błędach
- poprawia decyzje
- mowi wprost, kiedy wynik jest symulowany, dane sa niepelne albo system nie ma pewnosci
- ma zasade zero klamstwa: niczego nie dopowiada, nie zmysla i nie maskuje niepewnosci danych

---

## ⚙️ TRYBY DZIAŁANIA

### 🟢 TRYB 1 – NAUKA (START)
- tylko analiza + symulacja
- brak realnych transakcji
- zapis wyników

### 🟡 TRYB 2 – PAPER TRADING
- dane live
- symulacja tradingu

### 🔴 TRYB 3 – REAL TRADING
- podpięcie do Binance API
- realne pieniądze

---

## 💰 WIRTUALNY PORTFEL

```json
{
  "balance_pln": 1000,
  "positions": [],
  "history": []
}
```

---

## 💸 PARAMETRY GIEŁDY (BINANCE)

```json
{
  "fee": 0.001,
  "slippage": 0.0005
}
```

---

## 📊 ŹRÓDŁA DANYCH

- CoinGecko
- CryptoCompare
- Binance

---

## 🧱 ARCHITEKTURA SYSTEMU

[Data Collector] → [Database] → [Analyzer] → [Decision Engine] → [Simulator Wallet] → [Learning System]

---

## 🗄️ BAZA DANYCH (POSTGRESQL)

### market_data

symbol, timestamp, open, high, low, close, volume, source

### features

symbol, timestamp, rsi, macd, ema20, ema50, trend

### decisions

symbol, timestamp, decision, confidence, reason

### simulated_trades

symbol, buy_price, sell_price, fee, profit, duration

### learning_log

decision_id, timestamp, result, was_profitable, market_state, notes

---

## 📊 ANALIZA TECHNICZNA

- RSI
- MACD
- EMA 20 / EMA 50
- wolumen

---

## 🧠 LOGIKA DECYZJI (v1)

RSI < 30 → +2  
MACD ↑ → +2  
trend ↑ → +1  
volume ↑ → +1  

score ≥ 4 → BUY

---

## 📉 WARUNKI SPRZEDAŻY

RSI > 65 → SELL  
profit ≥ 4% → SELL  
strata ≤ -3% → STOP LOSS  

---

## 🔁 CYKL UCZENIA

1. pobierz dane  
2. policz wskaźniki  
3. podejmij decyzję  
4. zasymuluj trade  
5. zapisz wynik  
6. oceń decyzję  

---

## 🧪 TESTY

- BACKTEST  
- PAPER TRADING  
- STRESS TEST  

---

## 📊 METRYKI (KPI)

- ROI > +5% miesięcznie  
- win rate > 55%  
- max drawdown < 10%  

---

## 💰 STRATEGIA (START)

- max 3 trade dziennie  
- target zysk: 2–5%  
- stop loss: 2–3%  

---

## 🪙 COINY NA START

- BTC  
- ETH  
- SOL  
- MATIC  
- ADA  

---

## ⚖️ PRZYKŁADOWY PODZIAŁ (1000 PLN)

BTC – 300 PLN  
ETH – 250 PLN  
SOL – 200 PLN  
MATIC – 150 PLN  
ADA – 100 PLN  

---

## 💻 STACK TECHNOLOGICZNY

- Python  
- pandas / numpy  
- ta  
- PostgreSQL  

---

## 🚀 ROADMAP

### Tydzień 1
- data collector  
- baza danych  

### Tydzień 2
- analiza  

### Tydzień 3
- symulator  

### Tydzień 4
- learning system  

---

## ⚠️ WAŻNE

- nie używaj realnych pieniędzy na start  
- zapisuj każdą decyzję  
- analizuj błędy  
- system ma się uczyć, nie zgadywać  
- zero klamstwa: jesli wynik jest z paper tradingu, ma byc oznaczony jako symulowany  
- jesli dane sa stare, niepelne albo sprzeczne, system ma to powiedziec wprost zamiast udawac pewnosc
