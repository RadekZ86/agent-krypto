#!/bin/bash
cd ~/domains/MagicParty.usermd.net/agent-krypto
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
echo "Setup completed!"
