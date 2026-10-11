#!/usr/bin/env bash
# Uruchamia aplikację na http://127.0.0.1:8765 (tylko localhost).
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt
python -c "import spacy, sys; sys.exit(0 if spacy.util.is_package('pl_core_news_lg') else 1)" \
  || python -m spacy download pl_core_news_lg
exec python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8765}"
