#!/bin/bash
# Skrypt do pierwszej konfiguracji na serwerze mydevil.net
# Uruchom przez SSH: bash setup_server.sh

set -e

echo "=== Konfiguracja Agent Krypto na mydevil.net ==="

# Katalog aplikacji
APP_DIR=~/domains/MagicParty.usermd.net/public_python

# Utwórz katalog jeśli nie istnieje
mkdir -p "$APP_DIR"
cd "$APP_DIR"

# Sprawdź wersję Python
echo "Python version:"
python3.11 --version || python3 --version

# Utwórz virtual environment
if [ ! -d ".venv" ]; then
    echo "Tworzę virtual environment..."
    python3.11 -m venv .venv || python3 -m venv .venv
fi

# Aktywuj venv i zainstaluj pip
source .venv/bin/activate
pip install --upgrade pip

echo ""
echo "=== Konfiguracja zakończona ==="
echo ""
echo "Następne kroki:"
echo "1. Sklonuj repo: git clone https://github.com/TWOJ_USER/agent-krypto.git ."
echo "2. Zainstaluj zależności: pip install -r requirements.txt"
echo "3. Skopiuj i skonfiguruj .env: cp .env.example .env && nano .env"
echo "4. Skonfiguruj stronę w panelu DevilWEB jako 'Python + Passenger'"
echo ""
