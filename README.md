# Agent Krypto

MVP w Pythonie z panelem WWW do:
- pobierania live danych z API gield,
- liczenia wskaznikow technicznych,
- analizy wykresow i historii cen,
- szacowania prawdopodobienstwa ruchu w gore oraz lokalnego dolka/szczytu,
- podejmowania decyzji BUY / SELL / HOLD,
- symulacji portfela,
- harmonogramu automatycznych cykli,
- backtestu i rankingu strategii,
- zapisu decyzji i transakcji,
- programu nauki agenta i retrospektywy decyzji,
- sekcji artykulow edukacyjnych z sieci,
- przygotowania pod przyszla integracje z OpenAI.

## Stack

- FastAPI
- SQLAlchemy
- pandas / numpy
- Jinja2 + vanilla JS
- SQLite domyslnie, latwo podmienialne na PostgreSQL przez `DATABASE_URL`

## Uruchomienie

1. Utworz i aktywuj srodowisko Python.
2. Zainstaluj zaleznosci:

```bash
pip install -r requirements.txt
```

3. Skopiuj konfiguracje:

```bash
copy .env.example .env
```

4. Uruchom serwer lokalnie:

```bash
powershell -ExecutionPolicy Bypass -File scripts/start_agent_krypto_background.ps1
```

5. Otworz panel:

```text
http://127.0.0.1:8000
```

## OpenAI

Gdy podasz klucz API, wpisz go do `.env` w polu `OPENAI_API_KEY`.
Wtedy endpoint AI w panelu zacznie generowac komentarz do sytuacji rynkowej i wybranego wykresu.

## Co nowego w panelu

- przycisk resetu paper portfela do bazowego 1000 PLN z automatycznym zatrzymaniem schedulera,
- boczne menu skrotow do sekcji panelu, wygodniejsze tez na telefonie,
- wykres ceny z EMA20 i EMA50,
- wykres swiecowy z wolumenem, RSI i MACD do nauki price action,
- tryb wykresu "Od startu" z historia aktywa od pierwszych dostepnych notowan,
- tryby agenta: ostrozny / normalny / ryzykowny,
- widok portfela i rynku w PLN przy zachowaniu glownej logiki tradingowej na parach o wysokiej plynnosci,
- rozliczenie OpenAI: liczba wywolan, tokeny i szacunkowy koszt,
- podsumowanie 24h / 7d / 30d / zmiennosc / wsparcie / opor,
- prawdopodobienstwo: ruch w gore, lokalny dolek, lokalny szczyt,
- sekcja "Czego agent sie uczy",
- sekcja "Baza wiedzy" z playbookami trend / breakout / mean reversion / risk,
- sektorowe filtry rynku: Majors / Layer1 / DeFi / Infra / Payments / Memes,
- sekcja "Co jeszcze potrzebne" do dojrzalej pracy systemu,
- scheduler automatycznych cykli,
- ranking strategii po backtescie,
- lista materialow edukacyjnych oparta o zrodla z sieci,
- rozszerzona watchlista coinow z wiekszym uniwersum setupow.

## Live feed i tryby

- publiczne dane rynkowe z Binance API,
- fallback do Coinbase i CoinGecko,
- widok PLN liczony z live kursu USDT/PLN z CoinGecko, z fallbackiem do NBP,
- domyslny tryb `PAPER`,
- gotowosc pod przyszle klucze Binance do rozszerzenia wykonania zlecen.

## Konfiguracja runtime

Najwazniejsze pola w `.env`:

- `AGENT_KRYPTO_MARKET_INTERVAL=1h`
- `AGENT_KRYPTO_HISTORY_BARS=500`
- `AGENT_KRYPTO_CYCLE_INTERVAL_SECONDS=300`
- `AGENT_KRYPTO_LEARNING_MODE=true`
- `AGENT_KRYPTO_AGENT_MODE=normal`
- `AGENT_KRYPTO_EXPLORATION_RATE=0.22`
- `AGENT_KRYPTO_LEARNING_BUY_SCORE_THRESHOLD=4`
- `AGENT_KRYPTO_LEARNING_PROFIT_TARGET=0.025`
- `AGENT_KRYPTO_LEARNING_STOP_LOSS=0.05`
- `AGENT_KRYPTO_LEARNING_MAX_HOLD_HOURS=18`
- `AGENT_KRYPTO_SCHEDULER_ENABLED=true`
- `AGENT_KRYPTO_TRADING_MODE=PAPER`
- `AGENT_KRYPTO_DISPLAY_CURRENCY=PLN`
- `AGENT_KRYPTO_START_BALANCE_PLN=1000`
- `AGENT_KRYPTO_QUOTE_CURRENCY=USD`
- `AGENT_KRYPTO_EXCHANGE_QUOTE=USDT`
- `BINANCE_API_KEY=` i `BINANCE_API_SECRET=` tylko jesli pozniej chcesz rozszerzyc wykonanie zlecen

## Uruchamianie bez VS Code

- lokalnie na tym samym laptopie: `scripts\open_agent_krypto.cmd`
- jako serwer w sieci domowej: `powershell -ExecutionPolicy Bypass -File scripts\start_agent_krypto_server.ps1`
- status procesu i schedulera: `scripts\status_agent_krypto.cmd`
- zatrzymanie procesu: `scripts\stop_agent_krypto.cmd`
- restart procesu: `scripts\restart_agent_krypto.cmd`
- wlaczenie autostartu po logowaniu Windows: `powershell -ExecutionPolicy Bypass -File scripts\install_agent_krypto_autostart.ps1`
- wylaczenie autostartu: `powershell -ExecutionPolicy Bypass -File scripts\remove_agent_krypto_autostart.ps1`
- tworzenie skrotow na pulpicie: `powershell -ExecutionPolicy Bypass -File scripts\install_agent_krypto_shortcuts.ps1`
- instalacja globalnych komend terminala: `powershell -ExecutionPolicy Bypass -File scripts\install_agent_krypto_commands.ps1`
- po instalacji mozesz uruchamiac z dowolnego katalogu: `agent-krypto`, `agent-krypto-server`, `agent-krypto-test`, `agent-krypto-autostart-on`, `agent-krypto-autostart-off`, `agent-krypto-status`, `agent-krypto-stop`, `agent-krypto-restart`

Autostart korzysta z Harmonogramu zadan Windows i po zalogowaniu uruchamia tylko launcher w tle. Nie otwiera automatycznie przegladarki.

Skrypty `status`, `stop` i `restart` sa przygotowane do odpalania dwuklikiem. Otwieraja okno PowerShell z wynikiem, zeby bylo od razu widac co sie stalo.

## Wydajnosc panelu

- `GET /api/dashboard` zwraca teraz lekki payload bez kompletnego pakietu wykresow dla wszystkich coinow,
- wykres wybranego symbolu laduje sie osobno przez `GET /api/chart-package?symbol=BTC`,
- glowne odswiezenie panelu nie liczy juz 40 wykresow naraz.

## Log schedulera

Osobny log pracy schedulera zapisuje sie w pliku `logs/scheduler_history.log`.
Znajdziesz tam wpisy typu: start schedulera, start cyklu, koniec cyklu, blad cyklu oraz automatyczne wznowienie przez watchdog.

## Telefon poza domem

Szczegoly sa w pliku `docs/remote-access.md`, ale w praktyce masz 3 sensowne opcje:

1. Tailscale - najprostsze i najbezpieczniejsze. Instalujesz na laptopie-serwerze i na telefonie, potem otwierasz adres Tailscale IP.
2. Cloudflare Tunnel - dostajesz publiczny link HTTPS bez przekierowania portow na routerze.
3. Port forwarding + DDNS - dziala, ale jest najbardziej wrazliwe i wymaga pilnowania bezpieczenstwa.

## Zmiana bazy na PostgreSQL

Przyklad:

```env
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/agent_krypto
```

Do PostgreSQL trzeba wtedy dodatkowo doinstalowac sterownik, np. `psycopg[binary]`.