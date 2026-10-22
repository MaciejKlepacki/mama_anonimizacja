import json
from pathlib import Path




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
    # podgląd: oryginał zachowuje tekst; warianty niosą typ, status i placeholder
    orig = "".join(s["t"] for b in j["preview"] if "orig" in b for s in b["orig"])
    assert "Kowalskiego" in orig
    marked = [j["variants"][s["v"]] for b in j["preview"] if "orig" in b for s in b["orig"] if "v" in s]
    assert any(v["e"] == "PERSON" and v["st"] == "sure" and v["p"] == "[OSOBA_5]" for v in marked)
    assert j["doc_id"] and "todo" in j["review"]
    # ponowny rendering z decyzją i ręcznym zaznaczeniem
    vid = next(k for k, v in j["variants"].items() if v["t"] == "Jan Kowalski")
    r2 = c.post("/api/render", json={"doc_id": j["doc_id"], "decisions": {vid: "no"}, "manual": [{"text": "Mokotów", "entity_type": "LOCATION"}]})
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    assert "Jan Kowalski" in j2["markdown"] and "[MIEJSCOWOŚĆ_1]" in j2["markdown"] and j2["review"]["decided"] == 1
    assert c.post("/api/render", json={"doc_id": "nope", "decisions": {}}).status_code == 404
    assert c.get("/api/progress/abc").json()["total"] == 1


def test_upload_rejects_non_docx(client):
    c, _ = client
    r = c.post("/api/anonymize", files={"file": ("x.txt", b"tekst", "text/plain")})
    assert r.status_code == 400
    r = c.post("/api/anonymize", files={"file": ("x.docx", b"nope", "application/octet-stream")})
    assert r.status_code == 400
    r = c.post("/api/anonymize", files={"file": ("x.pdf", b"nope", "application/pdf")})
    assert r.status_code == 400
    # nagłówek PDF, ale plik uszkodzony → czytelny błąd, nie 500
    r = c.post("/api/anonymize", files={"file": ("x.pdf", b"%PDF-1.7 broken", "application/pdf")})
    assert r.status_code == 422 and "PDF" in r.json()["detail"]


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
