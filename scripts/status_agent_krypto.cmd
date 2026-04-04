@echo off
set SCRIPT_DIR=%~dp0
powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%status_agent_krypto.ps1"