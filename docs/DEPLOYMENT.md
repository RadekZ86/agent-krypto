# Deployment Agent Krypto na mydevil.net

## Wymagania
- Konto na mydevil.net (masz: MagicParty)
- Konto GitHub

## Krok 1: Utwórz repozytorium na GitHub

1. Wejdź na https://github.com/new
2. Nazwa repo: `agent-krypto`
3. Ustaw jako **Private** (prywatne)
4. Nie zaznaczaj "Initialize with README"
5. Kliknij "Create repository"

## Krok 2: Wypchnij kod na GitHub

W terminalu VS Code:
```powershell
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/TWOJ_USERNAME/agent-krypto.git
git push -u origin main
```

## Krok 3: Skonfiguruj GitHub Secrets

1. Wejdź do Settings → Secrets and variables → Actions
2. Dodaj następujące sekrety:
   - `SSH_USER`: `MagicParty`
   - `SSH_PASSWORD`: (twoje nowe hasło do mydevil)

## Krok 4: Skonfiguruj serwer mydevil.net

### 4.1 Połącz się przez SSH
```bash
ssh MagicParty@s84.mydevil.net
```

### 4.2 Utwórz stronę w panelu DevilWEB
1. Wejdź na https://panel84.mydevil.net/
2. Strony WWW → Dodaj stronę
3. Typ: **Własna aplikacja (proxy)**
4. Domena: `MagicParty.usermd.net`
5. Port: `8000`

### 4.3 Utwórz katalog i sklonuj repo
```bash
mkdir -p ~/domains/MagicParty.usermd.net/app
cd ~/domains/MagicParty.usermd.net/app
git clone https://github.com/TWOJ_USERNAME/agent-krypto.git .
```

### 4.4 Skonfiguruj środowisko Python
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4.5 Skonfiguruj plik .env
```bash
cp .env.example .env
nano .env
```
Ustaw:
- `OPENAI_API_KEY=` (twój klucz OpenAI)
- `DATABASE_URL=sqlite:///./agent_krypto.db`

### 4.6 Utwórz daemon do uruchomienia aplikacji
```bash
devil daemon add agent-krypto /usr/home/MagicParty/domains/MagicParty.usermd.net/app/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
devil daemon restart agent-krypto
```

### 4.7 Sprawdź czy działa
```bash
devil daemon status agent-krypto
curl http://127.0.0.1:8000
```

## Krok 5: Automatyczny deployment

Po każdym `git push` do brancha `main`, GitHub Actions automatycznie:
1. Połączy się z serwerem
2. Pobierze najnowszy kod
3. Zainstaluje zależności
4. Zrestartuje aplikację

## Dostęp do aplikacji

Po konfiguracji aplikacja będzie dostępna pod:
**https://MagicParty.usermd.net**

## Rozwiązywanie problemów

### Sprawdź logi daemona
```bash
devil daemon log agent-krypto
```

### Restart aplikacji
```bash
devil daemon restart agent-krypto
```

### Sprawdź czy port jest zajęty
```bash
netstat -tlnp | grep 8000
```
