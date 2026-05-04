# Deployment Agent Krypto na mydevil.net

## Aktualna konfiguracja

**URL aplikacji:** https://agentkrypto.apka.org.pl (alias: agentkrypto.magicparty.usermd.net)  
**Serwer:** s84.mydevil.net  
**Użytkownik:** MagicParty  
**Port:** 12345  
**GitHub:** https://github.com/RadekZ86/agent-krypto

## Uruchamianie lokalne

### Na komputerze (Windows)

1. Otwórz terminal w folderze projektu:
```powershell
cd "C:\Users\User\Documents\Agent Krypto"
```

2. Aktywuj środowisko wirtualne:
```powershell
.venv\Scripts\Activate.ps1
```

3. Uruchom aplikację:
```powershell
uvicorn app.main:app --reload --port 8000
```

4. Otwórz w przeglądarce: **http://localhost:8000**

### Na serwerze mydevil.net

Aplikacja działa automatycznie. Aby zrestartować:
```bash
ssh MagicParty@s84.mydevil.net
pkill -f "uvicorn app.main:app.*12345"
cd ~/domains/agentkrypto.magicparty.usermd.net/public_python
nohup /home/MagicParty/.local/bin/uvicorn app.main:app --host 127.0.0.1 --port 12345 >> /tmp/uvicorn_agentkrypto.log 2>&1 &
```

## GitHub Actions

Automatyczny deployment uruchamia się przy każdym `git push` do brancha `master`.

### Ręczne uruchomienie deploy:
1. Wejdź na: https://github.com/RadekZ86/agent-krypto/actions
2. Kliknij "Deploy to MyDevil"
3. Kliknij "Run workflow"

### Sprawdzenie statusu:
```powershell
& "C:\Program Files\GitHub CLI\gh.exe" run list --repo RadekZ86/agent-krypto --limit 3
```

## Konfiguracja serwera (już wykonana)

### Subdomena
```bash
devil www add agentkrypto.magicparty.usermd.net proxy localhost 12345
```

### Certyfikat SSL
```bash
devil ssl www add 185.36.169.188 le le agentkrypto.magicparty.usermd.net
```

### Port
```bash
devil port add tcp 12345
```

### BinExec (uruchamianie własnych programów)
```bash
devil binexec on
```

### Autostart (cron)
```bash
echo '@reboot /usr/home/MagicParty/domains/agentkrypto.magicparty.usermd.net/public_python/start_app.sh' | crontab -
```

## Rozwiązywanie problemów

### Sprawdź czy uvicorn działa:
```bash
ssh MagicParty@s84.mydevil.net "ps aux | grep uvicorn"
```

### Sprawdź logi:
```bash
ssh MagicParty@s84.mydevil.net "cat /tmp/uvicorn_agentkrypto.log | tail -50"
```

### Sprawdź lokalnie:
```bash
ssh MagicParty@s84.mydevil.net "curl -s http://127.0.0.1:12345/"
```

## Połączenie z Bybit API

### 1. Utwórz klucz API na Bybit

1. Zaloguj się na **https://www.bybit.com** (lub **https://testnet.bybit.com** dla testnet)
2. Przejdź do: **Konto → API Management → Utwórz nowy klucz**
3. Typ klucza: **System-generated API Keys**
4. Uprawnienia — zaznacz:
   - ✅ **Read** — odczyt portfela i pozycji
   - ✅ **Trade** — składanie zleceń (spot + derivatives)
   - ✅ **Position** — zarządzanie pozycjami perpetual (dźwignia)
5. Ogranicz dostęp IP (opcjonalnie, ale zalecane)
6. Zapisz **API Key** i **API Secret** — secret wyświetla się tylko raz!

### 2. Dodaj klucz w Agent Krypto

1. Otwórz aplikację: **https://agentkrypto.apka.org.pl**
2. Zaloguj się na swoje konto
3. Przejdź do **Status** (ikona zębatki w sidebar)
4. W sekcji **Klucze API** kliknij **Dodaj klucz API**
5. Wybierz giełdę: **Bybit**
6. Wklej **API Key** i **API Secret**
7. Zaznacz **Testnet** jeśli używasz konta testowego
8. Kliknij **Testuj połączenie** — powinno wyświetlić uprawnienia klucza
9. Zapisz klucz

### 3. Testnet vs Mainnet

| | Testnet | Mainnet |
|---|---|---|
| **URL API** | `api-testnet.bybit.com` | `api.bybit.com` |
| **Rejestracja** | https://testnet.bybit.com | https://www.bybit.com |
| **Środki** | Wirtualne (darmowe) | Prawdziwe |
| **Do czego** | Nauka, testy | Trading na żywo |

> **Zalecenie:** Zacznij od **Testnet** — dostaniesz wirtualne USDT do testów bez ryzyka.

### 4. Dostępne endpointy API w Agent Krypto

| Endpoint | Opis |
|---|---|
| `GET /api/bybit/test?key_id=N` | Test połączenia z Bybit |
| `GET /api/bybit/portfolio?key_id=N` | Portfel (saldo, equity, P&L) |
| `GET /api/bybit/positions?key_id=N` | Otwarte pozycje perpetual |
| `GET /api/bybit/leverage/{symbol}?key_id=N` | Aktualny poziom dźwigni |
| `POST /api/bybit/leverage/{symbol}?key_id=N` | Zmień dźwignię (body: `{"leverage": 5}`) |
| `POST /api/bybit/trade?key_id=N` | Złóż zlecenie (body: symbol, side, qty, leverage) |
| `GET /api/bybit/orders?key_id=N` | Otwarte zlecenia |
| `GET /api/bybit/history?key_id=N` | Historia transakcji (50 ostatnich) |
| `GET /api/leverage/snapshot` | Stan paper tradingu z dźwignią (bez klucza) |

### 5. Paper trading z dźwignią

Agent automatycznie uczy się dźwigni na wirtualnym kapitale ($10,000 USDT):
- **Dźwignia startowa:** 2x — rośnie z kolejnymi wygranymi (max 10x)
- **Max pozycji:** 3 jednocześnie (LONG + SHORT)
- **Funding rate:** symulowany 0.01% co 8h
- **Likwidacja:** symulowana (izolowany margin)
- **Próg wejścia:** min 7 punktów sygnałów (wyższy niż spot)

Dane dostępne w zakładce **Portfel** → karta **Nauka dźwigni (Paper)**.

## Sekrety GitHub (już skonfigurowane)

- `SSH_USER`: MagicParty
- `SSH_PASSWORD`: (hasło do mydevil)
