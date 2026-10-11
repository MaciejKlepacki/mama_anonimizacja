@echo off
REM Aktualizacja do najnowszej wersji z GitHuba: dwuklik, poczekaj do konca. Ustawienia i srodowisko zostaja.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\update.ps1"
