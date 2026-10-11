"""Uruchamia aplikację jak zwykły program: serwer w tle + osobne okno (Edge/Chrome w trybie aplikacji).

Po zamknięciu okna serwer wyłącza się sam. Używane przez skrót na pulpicie (pythonw -m app.launcher).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
URL = f"http://{HOST}:{PORT}/"
ROOT = Path(__file__).resolve().parent.parent
IDLE_TIMEOUT = 120  # s bez sygnału życia ze strony → wyłączamy serwer (gdy nie znamy procesu okna)


def _data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    d = base / "mama_anonimizacja"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _redirect_output(data_dir: Path) -> None:
    """pythonw nie ma konsoli (stdout/stderr = None) – piszemy do pliku dziennika."""
    log = data_dir / "aplikacja.log"
    if log.exists() and log.stat().st_size > 1_000_000:
        log.unlink()
    f = open(log, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = f
    print(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---")


def _healthy() -> bool:
    try:
        with urllib.request.urlopen(URL + "api/health", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def _find_browser() -> str | None:
    """Edge lub Chrome (obsługują tryb --app, czyli okno bez paska adresu)."""
    candidates: list[str] = []
    if sys.platform == "win32":
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if not base:
                continue
            candidates += [
                os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
            ]
    elif sys.platform == "darwin":
        candidates += [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    else:
        candidates += [shutil.which(n) or "" for n in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser")]
    return next((c for c in candidates if c and os.path.exists(c)), None)


def _open_window(data_dir: Path) -> subprocess.Popen | None:
    browser = _find_browser()
    if browser is None:
        webbrowser.open(URL)
        return None
    # osobny profil → okno aplikacji jest własnym procesem, na którego zamknięcie możemy poczekać
    cmd = [
        browser,
        f"--app={URL}",
        f"--user-data-dir={data_dir / 'okno'}",
        "--window-size=1280,900",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    return subprocess.Popen(cmd)


def main() -> None:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    data_dir = _data_dir()
    if sys.stdout is None or sys.stderr is None:
        _redirect_output(data_dir)

    if _healthy():  # aplikacja już działa – tylko pokaż okno
        _open_window(data_dir)
        return

    import uvicorn

    from app import main as app_main

    server = uvicorn.Server(uvicorn.Config(app_main.app, host=HOST, port=PORT, log_config=None))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if _healthy():
            break
        if not thread.is_alive():
            print("Serwer nie wystartował (czy port %d jest zajęty?)" % PORT)
            return
        time.sleep(0.2)

    started = time.time()
    proc = _open_window(data_dir)
    try:
        if proc is not None:
            proc.wait()
        if proc is None or time.time() - started < 5:
            # przeglądarka przekazała okno innemu procesowi – czekamy na brak sygnału życia ze strony
            app_main.STATE["last_ping"] = time.time()
            while time.time() - app_main.STATE["last_ping"] < IDLE_TIMEOUT and thread.is_alive():
                time.sleep(2)
    finally:
        server.should_exit = True
        thread.join(5)


if __name__ == "__main__":
    main()
