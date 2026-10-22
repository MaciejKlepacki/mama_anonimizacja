"""Testy: wejście .pdf (warstwa tekstowa → ta sama ścieżka co wklejony tekst), skany, CLI i upload."""

import json

import pytest

from app import cli
from app.docx_reader import TextBlock
from app.pdf_reader import PdfError, read_pdf_text
from app.pipeline import analyze_file, analyze_pdf, render, text_to_blocks
from tests.make_fixture_pdf_file import build, build_partial_scan, build_scan


@pytest.fixture(scope="session")
def pdf_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("pdf")
    build(d / "decyzja.pdf")
    build_scan(d / "skan.pdf")
    build_partial_scan(d / "czesciowy_skan.pdf")
    return d


@pytest.fixture(scope="session")
def pdf_file_state(pdf_dir, settings):
    return analyze_pdf(str(pdf_dir / "decyzja.pdf"), settings, source_name="decyzja.pdf")


def test_read_pdf_text_paragraphs(pdf_dir, settings):
    pdf = read_pdf_text(str(pdf_dir / "decyzja.pdf"))
    assert pdf.pages == 4 and pdf.empty_pages == [] and pdf.warnings == []
    lines = pdf.text.split("\n")
    # polskie znaki i nazwiska rozcięte między linie PDF są sklejone w jeden akapit
    assert any("pana Mariusza Habryki, działających" in ln for ln in lines)
    assert any("pan Piotr Zaręba; pozwolenia" in ln for ln in lines)
    assert "Uzasadnienie" in lines and "DECYZJA" in lines  # nagłówki osobno
    assert any(ln.startswith("a. Granica") for ln in lines) and any(ln.startswith("b. Granica") for ln in lines)
    # dalej jak wklejony tekst: numery stron znikają
    texts = [b.text for b in text_to_blocks(pdf.text, settings) if isinstance(b, TextBlock)]
    assert not any(t in ("2", "3", "4", "5") for t in texts)


def test_read_pdf_from_bytes(pdf_dir):
    data = (pdf_dir / "decyzja.pdf").read_bytes()
    assert read_pdf_text(data).text == read_pdf_text(str(pdf_dir / "decyzja.pdf")).text


def test_pdf_anonymized_like_docx(pdf_file_state):
    r = render(pdf_file_state)
    md = r.markdown
    anna = next(m for m in r.mapping if "Anny Habryki" in m["variants"])
    mariusz = next(m for m in r.mapping if "Mariusza Habryki" in m["variants"])
    assert anna["placeholder"] != mariusz["placeholder"] and anna["count"] >= 3
    assert "Pani " + anna["placeholder"] + " nie stawiła się" in md
    for secret in ["Habryk", "Wierzbick", "Zaręb", "Gumniska", "12/3", "48/24", "97/2", "122/1", "Lasówka"]:
        assert secret not in md, secret
    for keep in ["Prezydenta Miasta Krakowa", "Wojewody Małopolskiego", "WSA w Krakowie", "II OSK 1820/17"]:
        assert keep in md, keep


def test_analyze_file_dispatch(pdf_dir, fixture_docx, settings):
    s_pdf = analyze_file((pdf_dir / "czesciowy_skan.pdf").read_bytes(), settings, source_name="Pozew.PDF")
    assert s_pdf.source_name == "Pozew.PDF"
    s_docx = analyze_file(str(fixture_docx), settings)
    assert any(isinstance(b, TextBlock) and b.text == "WYROK" for b in s_docx.blocks)


def test_scanned_pdf_fails_clearly(pdf_dir, settings):
    with pytest.raises(PdfError, match="OCR"):
        read_pdf_text(str(pdf_dir / "skan.pdf"))
    with pytest.raises(PdfError, match="OCR"):
        analyze_pdf(str(pdf_dir / "skan.pdf"), settings)


def test_partially_scanned_pdf_warns(pdf_dir, settings):
    state = analyze_pdf(str(pdf_dir / "czesciowy_skan.pdf"), settings, source_name="pozew.pdf")
    assert any("bez warstwy tekstowej" in w and "2" in w for w in state.warnings)
    md = render(state).markdown
    assert "Kowalski" not in md and "44051401359" not in md


def test_broken_and_encrypted_pdf(tmp_path):
    with pytest.raises(PdfError):
        read_pdf_text(b"%PDF-1.7 to nie jest PDF")
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "tajne")
    enc = tmp_path / "haslo.pdf"
    doc.save(enc, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    with pytest.raises(PdfError, match="hasłem"):
        read_pdf_text(str(enc))


def test_cli_pdf(pdf_dir, tmp_path, monkeypatch, settings, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    out, mapa = tmp_path / "wynik.md", tmp_path / "mapa.json"
    assert cli.main([str(pdf_dir / "decyzja.pdf"), "-o", str(out), "--mapa", str(mapa)]) == 0
    md = out.read_text(encoding="utf-8")
    assert "[OSOBA_1]" in md and "Habryk" not in md
    assert any("Anny Habryki" in m["variants"] for m in json.loads(mapa.read_text(encoding="utf-8")))
    assert cli.main([str(pdf_dir / "skan.pdf"), "--stdout"]) == 3
    assert "OCR" in capsys.readouterr().err
    other = tmp_path / "notatka.txt"
    other.write_text("x", encoding="utf-8")
    assert cli.main([str(other)]) == 2


def test_upload_pdf(client, pdf_dir):
    c, _ = client
    with open(pdf_dir / "decyzja.pdf", "rb") as f:
        r = c.post("/api/anonymize", files={"file": ("Decyzja.pdf", f, "application/pdf")})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["filename"] == "Decyzja_anonimizacja.md"
    assert "Habryk" not in j["markdown"] and j["doc_id"] and j["preview"]
    # ponowny rendering z decyzją recenzenta działa tak samo jak dla .docx
    r2 = c.post("/api/render", json={"doc_id": j["doc_id"], "decisions": {}, "manual": [{"text": "Podgórze", "entity_type": "LOCATION"}]})
    assert r2.status_code == 200 and "Podgórze" not in r2.json()["markdown"]
    with open(pdf_dir / "skan.pdf", "rb") as f:
        r3 = c.post("/api/anonymize", files={"file": ("skan.pdf", f, "application/pdf")})
    assert r3.status_code == 422 and "OCR" in r3.json()["detail"]
