"""Serwer lokalny (FastAPI): upload .docx → Markdown, ustawienia Presidio, test na tekście."""

from __future__ import annotations

import io
import json
import logging
import re
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ValidationError

from . import __version__
from .engine import get_anonymizer
from .markdown import ENTITY_NAMES
from .pipeline import anonymize_docx, anonymize_plain_text
from .settings import DEFAULT_SETTINGS_PATH, Settings, load_settings, reset_settings, save_settings

log = logging.getLogger("mama_anonimizacja")
STATIC_DIR = Path(__file__).parent / "static"
MAX_UPLOAD_MB = 50

@asynccontextmanager
async def _lifespan(_: FastAPI):
    """Załaduj model spaCy przy starcie, żeby pierwszy upload nie czekał."""
    try:
        get_anonymizer(load_settings())
        log.info("Silnik Presidio gotowy.")
    except Exception as e:  # pragma: no cover - diagnostyka
        log.exception("Nie udało się zbudować silnika: %s", e)
    yield


app = FastAPI(
    title="mama_anonimizacja", version=__version__, docs_url="/api/docs", redoc_url=None, lifespan=_lifespan
)


# ------------------------------------------------------------------ strony
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/settings", include_in_schema=False)
def settings_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html")


@app.get("/static/{name}", include_in_schema=False)
def static_file(name: str) -> FileResponse:
    path = (STATIC_DIR / name).resolve()
    if path.parent != STATIC_DIR.resolve() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


# ------------------------------------------------------------------ API
_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _safe_stem(filename: str) -> str:
    stem = Path(filename or "dokument").stem.translate(_PL)
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "dokument"
    return stem[:80]


@app.post("/api/anonymize")
async def api_anonymize(file: UploadFile = File(...)) -> JSONResponse:
    name = file.filename or "dokument.docx"
    if not name.lower().endswith(".docx"):
        raise HTTPException(400, "Obsługiwane są tylko pliki .docx (Word). Zapisz .doc jako .docx.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Plik jest większy niż {MAX_UPLOAD_MB} MB.")
    if not data[:2] == b"PK":
        raise HTTPException(400, "To nie jest poprawny plik .docx.")
    settings = load_settings()
    try:
        result = anonymize_docx(data, settings, source_name=name)
    except Exception as e:  # noqa: BLE001
        log.exception("Błąd anonimizacji")
        raise HTTPException(500, f"Błąd przetwarzania dokumentu: {e}") from e
    return JSONResponse(
        {
            "filename": f"{_safe_stem(name)}_anonimizacja.md",
            "mapping_filename": f"{_safe_stem(name)}_mapa.json",
            "markdown": result.markdown,
            "mapping": result.mapping,
            "stats": result.stats,
            "entity_names": ENTITY_NAMES,
            "labels": {k: settings.label_for(k) for k in settings.enabled_entities()},
            "blocks": result.blocks,
            "seconds": result.seconds,
            "warnings": result.warnings,
        }
    )


def _errors(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())


class TextIn(BaseModel):
    text: str
    settings: Dict[str, Any] | None = None


@app.post("/api/anonymize-text")
def api_anonymize_text(payload: TextIn) -> JSONResponse:
    """Anonimizacja wklejonego tekstu; opcjonalnie z niezapisanymi ustawieniami (podgląd)."""
    if payload.settings is not None:
        try:
            settings = Settings.model_validate(payload.settings)
        except ValidationError as e:
            raise HTTPException(422, _errors(e)) from e
    else:
        settings = load_settings()
    if len(payload.text) > 200_000:
        raise HTTPException(413, "Tekst za długi (max 200 000 znaków).")
    result = anonymize_plain_text(payload.text, settings)
    return JSONResponse(
        {"markdown": result.markdown, "mapping": result.mapping, "stats": result.stats, "seconds": result.seconds}
    )


@app.get("/api/settings")
def api_get_settings() -> JSONResponse:
    settings = load_settings()
    with DEFAULT_SETTINGS_PATH.open("r", encoding="utf-8") as f:
        defaults = json.load(f)
    return JSONResponse({"settings": settings.model_dump(mode="json"), "defaults": defaults, "entity_names": ENTITY_NAMES})


@app.put("/api/settings")
def api_put_settings(payload: Dict[str, Any]) -> JSONResponse:
    try:
        settings = Settings.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(422, _errors(e)) from e
    try:
        get_anonymizer(settings)  # walidacja: np. błędny regex w custom recognizer
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Nie można zbudować silnika z tymi ustawieniami: {e}") from e
    save_settings(settings)
    return JSONResponse({"ok": True, "settings": settings.model_dump(mode="json")})


@app.post("/api/settings/reset")
def api_reset_settings() -> JSONResponse:
    settings = reset_settings()
    return JSONResponse({"ok": True, "settings": settings.model_dump(mode="json")})


@app.get("/api/health")
def api_health() -> Dict[str, Any]:
    return {"ok": True, "version": __version__}


def run() -> None:  # pragma: no cover - uruchomienie ręczne
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":  # pragma: no cover
    run()
