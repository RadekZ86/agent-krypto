@echo off
set SCRIPT_DIR=%~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_agent_krypto_server.ps1"
start "" "http://127.0.0.1:8000"