@echo off
REM Instalator dla Windows: dwuklik, poczekaj do konca - na pulpicie pojawi sie ikona.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\install.ps1"
