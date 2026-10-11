@echo off
REM Uruchamia aplikacje na http://127.0.0.1:8765 (tylko localhost).
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
python -c "import spacy, sys; sys.exit(0 if spacy.util.is_package('pl_core_news_lg') else 1)" || python -m spacy download pl_core_news_lg
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
