# Agent Krypto — Instrukcje dla Agenta AI

## Projekt

Agent Krypto — system do analizy rynku kryptowalut z paper tradingiem, AI chatem i dashboardem webowym.

## Stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy, SQLite
- **Frontend:** Jinja2 + vanilla JS (app.js ~4000 linii, styles.css ~3900 linii)
- **AI:** OpenAI API (model: gpt-4.1-mini)
- **Giełdy:** Binance API (public + private), Bybit API, CoinGecko, Coinbase (fallback)

## Lokalne środowisko

- **Workspace:** `C:\Users\User\Documents\Agent Krypto`
- **Python venv:** `.venv\` w katalogu projektu
- **Uruchomienie lokalne:** `scripts\start_agent_krypto_background.ps1`
- **Uruchomienie serwer LAN:** `scripts\start_agent_krypto_server.ps1`
- **Status:** `scripts\status_agent_krypto.cmd`
- **Stop:** `scripts\stop_agent_krypto.cmd`
- **Restart:** `scripts\restart_agent_krypto.cmd`
- **Testy:** `scripts\run_agent_krypto_tests.ps1`
- **Port lokalny:** 8000

## Serwer produkcyjny (MyDevil)

- **Host:** `s84.mydevil.net`
- **User:** `MagicParty`
- **OS:** FreeBSD 14.3-RELEASE
- **Python:** 3.11.13 (`/usr/local/bin/python3`)
- **Uvicorn:** `/home/MagicParty/.local/bin/uvicorn` (0.43.0)
- **Domena:** `https://agentkrypto.apka.org.pl` (alias: `agentkrypto.magicparty.usermd.net`)
- **Deploy path:** `/usr/home/MagicParty/domains/agentkrypto.magicparty.usermd.net/public_python/`
- **Alias path:** `/usr/home/MagicParty/domains/agentkrypto.apka.org.pl/public_python/` (symlinki do deploy path)
- **Baza danych:** `agent_krypto.db` (SQLite, w deploy path)
- **Logi:** `~/domains/agentkrypto.magicparty.usermd.net/logs/error.log`

### SSH

- **Alias:** `ssh mydevil` (skonfigurowane w `~/.ssh/config`)
- **Klucz:** `~/.ssh/id_ed25519` (ed25519, email: radkondjdekar@gmail.com)
- **Config:**
  ```
  Host mydevil
      HostName s84.mydevil.net
      User MagicParty
      IdentityFile ~/.ssh/id_ed25519
  ```

**Logowanie:** wystarczy `ssh mydevil` — klucz publiczny jest dodany na serwerze, hasło nie jest wymagane.

### Ręczne komendy na serwerze

```bash
# Restart serwera
ssh mydevil "devil www restart agentkrypto.apka.org.pl && devil www restart agentkrypto.magicparty.usermd.net"

# Logi
ssh mydevil "tail -50 ~/domains/agentkrypto.magicparty.usermd.net/logs/error.log"

# Health check
ssh mydevil "curl -s -o /dev/null -w '%{http_code}' https://agentkrypto.apka.org.pl/"
```

## Deploy (CI/CD)

- **GitHub repo:** `RadekZ86/agent-krypto` (branch: `master`)
- **Workflow:** `.github/workflows/deploy.yaml`
- **Trigger:** push do `master` lub manual (`workflow_dispatch`)
- **Mechanizm:** zip kodu → scp → unzip → pip install → restart uvicorn
- **GitHub Secrets:** `SSH_USER`, `SSH_PASSWORD`
- **Deploy path:** `/usr/home/MagicParty/domains/agentkrypto.magicparty.usermd.net/public_python/`
- **Domena primarna:** `agentkrypto.apka.org.pl`
- **Uwaga:** workflow używa `sshpass` (hasło), ale SSH key auth też działa

## Konfiguracja (.env na serwerze)

```env
DATABASE_URL=sqlite:///./agent_krypto.db
OPENAI_MODEL=gpt-4.1-mini
OPENAI_API_KEY=***
BINANCE_API_KEY=***
BINANCE_API_SECRET=***
AGENT_KRYPTO_TRADING_MODE=PAPER
AGENT_KRYPTO_AGENT_MODE=normal
AGENT_KRYPTO_SCHEDULER_ENABLED=true
AGENT_KRYPTO_CYCLE_INTERVAL_SECONDS=120
AGENT_KRYPTO_MARKET_INTERVAL=1h
AGENT_KRYPTO_HISTORY_BARS=500
AGENT_KRYPTO_QUOTE_CURRENCY=USD
AGENT_KRYPTO_DISPLAY_CURRENCY=PLN
AGENT_KRYPTO_EXCHANGE_QUOTE=USDT
AGENT_KRYPTO_LEARNING_MODE=true
AGENT_KRYPTO_EXPLORATION_RATE=0.22
AGENT_KRYPTO_LEARNING_BUY_SCORE_THRESHOLD=4
AGENT_KRYPTO_LEARNING_PROFIT_TARGET=0.025
AGENT_KRYPTO_LEARNING_STOP_LOSS=0.05
AGENT_KRYPTO_LEARNING_MAX_HOLD_HOURS=18
AGENT_KRYPTO_START_BALANCE_PLN=1000
AGENT_KRYPTO_FEE_RATE=0.001
AGENT_KRYPTO_SLIPPAGE=0.0005
```

## Główne endpointy API

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/` | GET | Dashboard HTML |
| `/api/dashboard` | GET | Dane dashboardu JSON |
| `/api/run-cycle` | POST | Uruchom cykl analizy |
| `/api/scheduler/start` | POST | Włącz scheduler |
| `/api/scheduler/stop` | POST | Wyłącz scheduler |
| `/api/chart-package?symbol=...` | GET | Dane wykresu (lazy load) |
| `/api/backtest` | GET | Backtest ranking |
| `/api/ai-insight` | GET | AI analiza rynku |
| `/api/agent-chat` | POST | AI chat (z cache exchange) |
| `/api/auth/me` | GET | Status logowania |
| `/api/auth/login` | POST | Logowanie |
| `/api/auth/register` | POST | Rejestracja |
| `/api/auth/api-keys` | GET/POST/DELETE | Zarządzanie kluczami API |

## Struktura kodu

```
app/
  main.py          — FastAPI app, wszystkie endpointy, exchange cache
  config.py        — konfiguracja z .env
  database.py      — SQLAlchemy engine + session
  models.py        — modele ORM
  services/
    agent_cycle.py     — główna logika cyklu (BUY/SELL/HOLD)
    ai_advisor.py      — OpenAI chat + insight
    analysis_frame.py  — generowanie ramki analitycznej
    backtest.py        — backtest strategii
    currency_service.py— kurs walut (USDT/PLN)
    decision_engine.py — 12 buy + 11 sell signals, confluence scoring
    indicators.py      — RSI, MACD, EMA, BB, VWAP, feature_row
    learning.py        — adaptive feedback engine
    learning_center.py — baza wiedzy, playbooki
    market_data.py     — Binance/Coinbase/CoinGecko/Bybit data
    probability_engine.py — prawdopodobieństwo ruchów
    runtime_state.py   — runtime parameters
    scheduler.py       — auto-cycle scheduler
    wallet.py          — paper wallet + LIVE bridge-buy
  static/
    app.js         — frontend JS (~4000 linii)
    styles.css     — CSS z mobile Bybit-style (~3900 linii)
  templates/
    index.html     — Jinja2 template (~1200 linii)
```

## Ważne uwagi techniczne

- **Binance PL** nie ma par USDT — tylko 3 pary PLN (BTC, ETH, USDC). Alty via USDC (bridge-buy: PLN→USDC→ALT).
- **MKR, EOS, CRO** nie mają par na Binance PL — pominięte, zastąpione FET, RENDER, WLD.
- **Decision engine:** wymaga score >= 6 AND 3+ potwierdzających sygnałów do BUY. Sell wymaga score >= 3.
- **Exchange data cache:** 120s TTL per user, thread-safe. Chat endpoint używa `skip_exchange_api=True`.
- **Mobile UI:** Bybit-style dark theme, 5-tab bottom nav, `touch-action: manipulation` na wszystkich buttonach.
- **MyDevil SSH** może rate-limitować — czekaj 30s+ między próbami.
- **quoteOrderQty** musi być floor (nie round) do 2 miejsc po przecinku.
- **Admin email:** `zajcu1986@wp.pl`
- **Język użytkownika:** polski
