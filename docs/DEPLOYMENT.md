# Deployment Agent Krypto na mydevil.net

## Aktualna konfiguracja

**URL aplikacji:** http://agentkrypto.magicparty.usermd.net  
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

## Sekrety GitHub (już skonfigurowane)

- `SSH_USER`: MagicParty
- `SSH_PASSWORD`: (hasło do mydevil)
