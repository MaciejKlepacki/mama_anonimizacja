import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_mod
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # izolacja pliku ustawień użytkownika
    user_path = tmp_path / "settings.json"
    import app.settings as st

    monkeypatch.setattr(st, "USER_SETTINGS_PATH", user_path)
    monkeypatch.setattr(main_mod, "load_settings", lambda: st.load_settings(user_path))
    monkeypatch.setattr(main_mod, "save_settings", lambda s: st.save_settings(s, user_path))
    monkeypatch.setattr(main_mod, "reset_settings", lambda: st.reset_settings(user_path))
    with TestClient(app) as c:
        yield c, user_path


def test_pages(client):
    c, _ = client
    assert c.get("/").status_code == 200 and "Przeciągnij plik .docx" in c.get("/").text
    assert c.get("/settings").status_code == 200
    assert c.get("/static/style.css").status_code == 200
    assert c.get("/static/../main.py").status_code in (404, 400)
    assert c.get("/api/health").json()["ok"] is True


def test_upload_docx(client, fixture_docx):
    c, _ = client
    with open(fixture_docx, "rb") as f:
        r = c.post("/api/anonymize", files={"file": ("Wyrok przykład.docx", f, "application/octet-stream")})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["filename"] == "Wyrok_przyklad_anonimizacja.md"
    assert "[OSOBA_5]" in j["markdown"] and "Kowalski" not in j["markdown"]
    assert any(m["placeholder"] == "[OSOBA_5]" for m in j["mapping"])
    # podgląd: oryginał zachowuje tekst, wersja zanonimizowana ma placeholdery w tych samych miejscach
    orig = "".join(s["t"] for b in j["preview"] if "orig" in b for s in b["orig"])
    anon = "".join(s["t"] for b in j["preview"] if "anon" in b for s in b["anon"])
    assert "Kowalskiego" in orig and "Kowalski" not in anon and "[OSOBA_" in anon
    assert any(s.get("e") == "PERSON" for b in j["preview"] if "orig" in b for s in b["orig"])


def test_upload_rejects_non_docx(client):
    c, _ = client
    r = c.post("/api/anonymize", files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 400
    r = c.post("/api/anonymize", files={"file": ("x.docx", b"nope", "application/octet-stream")})
    assert r.status_code == 400


def test_settings_roundtrip(client):
    c, user_path = client
    s = c.get("/api/settings").json()["settings"]
    s["entities"]["LOCATION"]["enabled"] = True
    s["allow_list"].append("Mokotów")
    s["custom_recognizers"] = [{"name": "t", "entity": "NR_TESTU", "patterns": [r"T-\d{3}"], "score": 0.9}]
    r = c.put("/api/settings", json=s)
    assert r.status_code == 200, r.text
    assert json.loads(Path(user_path).read_text())["entities"]["LOCATION"]["enabled"] is True
    r = c.post("/api/anonymize-text", json={"text": "Test T-123 w Krakowie, obręb Mokotów"})
    assert "[NR_TESTU_1]" in r.json()["markdown"]
    assert "[MIEJSCOWOŚĆ_1]" in r.json()["markdown"] and "Mokotów" in r.json()["markdown"]
    # błędny regex → 422/400, ustawienia nie nadpisane
    s["custom_recognizers"] = [{"name": "z", "entity": "ZLE", "patterns": ["("]}]
    assert c.put("/api/settings", json=s).status_code in (400, 422)
    r = c.post("/api/settings/reset")
    assert r.status_code == 200 and not user_path.exists()
