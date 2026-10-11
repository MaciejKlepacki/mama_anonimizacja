"""Serwer lokalny (FastAPI): upload .docx → analiza → przegląd decyzji → Markdown; ustawienia; test na tekście."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from . import __version__
from .engine import get_anonymizer
from .markdown import ENTITY_NAMES
from .pipeline import MANUAL_ENTITY_TYPES, MANUAL_LABELS, DocState, ManualSpan, Result, analyze_document, analyze_text, anonymize_plain_text, render
from .settings import DEFAULT_SETTINGS_PATH, Settings, load_settings, reset_settings, save_settings

log = logging.getLogger("mama_anonimizacja")
STATIC_DIR = Path(__file__).parent / "static"
MAX_UPLOAD_MB = 50
MAX_DOCS = 6

STATE: Dict[str, Any] = {"ready": False, "error": None, "last_ping": time.time()}
DOCS: "OrderedDict[str, DocState]" = OrderedDict()
PROGRESS: Dict[str, Dict[str, Any]] = {}
_docs_lock = threading.Lock()


def _warm_up() -> None:
    try:
        get_anonymizer(load_settings())
        log.info("Silnik Presidio gotowy.")
    except Exception as e:  # pragma: no cover - diagnostyka
        log.exception("Nie udało się zbudować silnika: %s", e)
        STATE["error"] = str(e)
    STATE["ready"] = True


@asynccontextmanager
async def _lifespan(_: FastAPI):
    """Załaduj model spaCy w tle: serwer odpowiada od razu, a pierwszy upload nie czeka na model."""
    threading.Thread(target=_warm_up, daemon=True).start()
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


def _store(state: DocState) -> None:
    with _docs_lock:
        DOCS[state.doc_id] = state
        while len(DOCS) > MAX_DOCS:
            DOCS.popitem(last=False)


def _get_doc(doc_id: str) -> DocState:
    with _docs_lock:
        state = DOCS.get(doc_id)
    if state is None:
        raise HTTPException(404, "Dokument nie jest już w pamięci (wczytaj plik ponownie).")
    return state


def _payload(result: Result, name: str, settings: Settings) -> Dict[str, Any]:
    labels = {k: settings.label_for(k) for k in settings.enabled_entities()}
    labels.update({k: MANUAL_LABELS.get(k) or settings.label_for(k) for k in MANUAL_ENTITY_TYPES})
    names = dict(ENTITY_NAMES)
    names["OTHER"] = "zanonimizowane dane (zaznaczone ręcznie)"
    return {
        "doc_id": result.doc_id,
        "filename": f"{_safe_stem(name)}_anonimizacja.md",
        "mapping_filename": f"{_safe_stem(name)}_mapa.json",
        "markdown": result.markdown,
        "mapping": result.mapping,
        "stats": result.stats,
        "entity_names": names,
        "labels": labels,
        "manual_types": MANUAL_ENTITY_TYPES,
        "blocks": result.blocks,
        "seconds": result.seconds,
        "warnings": result.warnings,
        "preview": result.preview,
        "variants": result.variants,
        "keys": result.keys,
        "review": result.review,
    }


@app.post("/api/anonymize")
async def api_anonymize(file: UploadFile = File(...), job_id: Optional[str] = Form(None)) -> JSONResponse:
    name = file.filename or "dokument.docx"
    if not name.lower().endswith(".docx"):
        raise HTTPException(400, "Obsługiwane są tylko pliki .docx (Word). Zapisz .doc jako .docx.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Plik jest większy niż {MAX_UPLOAD_MB} MB.")
    if not data[:2] == b"PK":
        raise HTTPException(400, "To nie jest poprawny plik .docx.")
    settings = load_settings()
    job = job_id if job_id and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", job_id) else None
    t0 = time.time()

    def progress(stage: str, done: int, total: int) -> None:
        if job:
            PROGRESS[job] = {"stage": stage, "done": done, "total": total, "seconds": round(time.time() - t0, 1)}

    try:
        state = await run_in_threadpool(analyze_document, data, settings, name, progress)
        progress("Buduję wynik", 0, 1)
        result = render(state)
    except Exception as e:  # noqa: BLE001
        log.exception("Błąd anonimizacji")
        raise HTTPException(500, f"Błąd przetwarzania dokumentu: {e}") from e
    finally:
        if job:
            PROGRESS.pop(job, None)
    _store(state)
    return JSONResponse(_payload(result, name, settings))


class PasteIn(BaseModel):
    text: str
    job_id: Optional[str] = None
    name: Optional[str] = None


@app.post("/api/anonymize-paste")
async def api_anonymize_paste(payload: PasteIn) -> JSONResponse:
    """Wklejony tekst (z Worda / PDF) zamiast pliku – ten sam przebieg i podgląd co dla .docx."""
    if not payload.text.strip():
        raise HTTPException(400, "Wklej jakiś tekst.")
    if len(payload.text) > 2_000_000:
        raise HTTPException(413, "Tekst za długi (max 2 000 000 znaków).")
    settings = load_settings()
    job = payload.job_id if payload.job_id and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", payload.job_id) else None
    name = (payload.name or "tekst") + ".txt"
    t0 = time.time()

    def progress(stage: str, done: int, total: int) -> None:
        if job:
            PROGRESS[job] = {"stage": stage, "done": done, "total": total, "seconds": round(time.time() - t0, 1)}

    try:
        state = await run_in_threadpool(analyze_text, payload.text, settings, name, progress)
        result = render(state)
    except Exception as e:  # noqa: BLE001
        log.exception("Błąd anonimizacji tekstu")
        raise HTTPException(500, f"Błąd przetwarzania tekstu: {e}") from e
    finally:
        if job:
            PROGRESS.pop(job, None)
    _store(state)
    return JSONResponse(_payload(result, name, settings))


@app.get("/api/progress/{job_id}")
def api_progress(job_id: str) -> Dict[str, Any]:
    return PROGRESS.get(job_id) or {"stage": "Wysyłam plik", "done": 0, "total": 1, "seconds": 0}


class ManualIn(BaseModel):
    text: str
    entity_type: str
    all_occurrences: bool = True
    item: Optional[int] = None
    start: Optional[int] = None
    end: Optional[int] = None


class RenderIn(BaseModel):
    doc_id: str
    decisions: Dict[str, str] = {}
    merges: Dict[str, str] = {}
    manual: List[ManualIn] = []
    filename: Optional[str] = None


@app.post("/api/render")
def api_render(payload: RenderIn) -> JSONResponse:
    """Ponowny rendering po decyzjach recenzenta (OK / nie OK / scalenie / ręczne zaznaczenie)."""
    state = _get_doc(payload.doc_id)
    decisions = {k: v for k, v in payload.decisions.items() if v in ("yes", "no")}
    manual = [ManualSpan(**m.model_dump()) for m in payload.manual if m.entity_type in MANUAL_ENTITY_TYPES]
    try:
        result = render(state, decisions, payload.merges, manual)
    except Exception as e:  # noqa: BLE001
        log.exception("Błąd renderowania")
        raise HTTPException(500, f"Błąd budowania wyniku: {e}") from e
    return JSONResponse(_payload(result, payload.filename or state.source_name or "dokument.docx", state.settings))


@app.delete("/api/doc/{doc_id}")
def api_forget(doc_id: str) -> Dict[str, Any]:
    with _docs_lock:
        DOCS.pop(doc_id, None)
    return {"ok": True}


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
        {"markdown": result.markdown, "mapping": result.mapping, "stats": result.stats, "seconds": result.seconds, "review": result.review}
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
    return {"ok": True, "version": __version__, "ready": STATE["ready"], "error": STATE["error"]}


@app.get("/api/ping")
def api_ping() -> Dict[str, Any]:
    """Sygnał życia z otwartej strony (launcher wyłącza serwer, gdy okno zniknie)."""
    STATE["last_ping"] = time.time()
    return {"ok": True}


def run() -> None:  # pragma: no cover - uruchomienie ręczne
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":  # pragma: no cover
    run()
