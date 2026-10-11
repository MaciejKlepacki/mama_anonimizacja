"""Testy: dokument „z konwersji PDF”, ocena pewności, decyzje recenzenta, scalanie, ręczne zaznaczenia."""

from pathlib import Path

import pytest

from app.docx_reader import TextBlock, read_docx
from app.names import name_stem
from app.pipeline import ManualSpan, analyze_document, render

ROOT = Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def pdf_docx():
    path = ROOT / "fixtures" / "decyzja_pdf.docx"
    if not path.exists():
        from tests.make_fixture_pdf import build

        build(path)
    return path


@pytest.fixture(scope="session")
def pdf_state(pdf_docx, settings):
    return analyze_document(str(pdf_docx), settings, source_name="decyzja.docx")


def test_name_stems_unify_inflection():
    assert name_stem("Anny") == name_stem("Anna") == name_stem("Annie") == name_stem("Anną")
    assert name_stem("Habryki") == name_stem("Habryka") == name_stem("Habryce")
    assert name_stem("Kowalskiego") == name_stem("Kowalski") != name_stem("Kowalska") == name_stem("Kowalskiej")
    assert name_stem("Marka") == name_stem("Marek") and name_stem("Pawła") == name_stem("Paweł")


def test_pdf_lines_are_merged(pdf_docx, settings):
    blocks = read_docx(str(pdf_docx), settings.docx)
    texts = [b.text for b in blocks if isinstance(b, TextBlock)]
    # numery stron zniknęły, linie sklejone w zdania
    assert "2" not in texts and "3" not in texts
    assert any("pana Mariusza Habryki, działających" in t for t in texts)
    assert any("pan Piotr Zaręba; pozwolenia" in t for t in texts)
    assert any("Uzasadnienie" == t for t in texts)  # krótki nagłówek nie jest doklejany
    assert not any(t.startswith("b. Granica") and "a. Granica" in t for t in texts)  # punkty listy osobno


def test_pdf_document_default_result(pdf_state):
    r = render(pdf_state)
    md = r.markdown
    by_ph = {m["placeholder"]: m for m in r.mapping}
    # osoby spójne mimo odmiany i podziału między linie
    anna = next(m for m in r.mapping if "Anny Habryki" in m["variants"])
    assert "Anna Habryka" in anna["variants"] and anna["count"] >= 3
    mariusz = next(m for m in r.mapping if "Mariusza Habryki" in m["variants"])
    assert "Mariusz Habryka" in mariusz["variants"] and mariusz["placeholder"] != anna["placeholder"]
    assert "Pani " + anna["placeholder"] + " nie stawiła się" in md
    assert "pan " + mariusz["placeholder"] + " stawił się" in md
    zareba = next(m for m in r.mapping if "Piotr Zaręba" in m["variants"])
    assert "Zaręba" in zareba["variants"]
    for secret in ["Habryk", "Wierzbick", "Zaręb", "Gumniska", "12/3", "48/24", "97/2", "122/1"]:
        assert secret not in md, secret
    # spółka (z formą prawną i bez)
    gum = next(m for m in r.mapping if "Gumniska sp. z o.o." in m["variants"])
    assert "Gumniska" in gum["variants"] and gum["entity_type"] == "ORGANIZATION"
    # organy publiczne, skróty i cytowane orzeczenia zostają
    for keep in ["Prezydenta Miasta Krakowa", "Wojewody Małopolskiego", "Naczelnego Sądu", "Rady Miasta Krakowa",
                 "PZT", "WSA w Krakowie", "lit. a pb", "ZP.1- ZP.6", "KDL.1", "II OSK 1820/17", "Inwestorowi:"]:
        assert keep in md, keep
    # działka nr 98 także w "działką sąsiednią nr 98" i "działek nr 98,122/1"
    p98 = next(m for m in r.mapping if "98" in m["variants"])
    assert p98["count"] >= 3
    # numer decyzji i ulica bez numeru – do sprawdzenia, ale domyślnie anonimizowane
    assert "AU-01-4.6740.1.263.2024.GPA" not in md and "Lasówka" not in md
    assert r.review["todo"] >= 3 and r.review["hints"] >= 2
    todo = [v for v in r.variants.values() if v["st"] == "review"]
    assert any(v["t"] == "ul. Lasówka" for v in todo)
    hints = [v for v in r.variants.values() if v["st"] == "hint"]
    assert any(v["t"] == "PZT" for v in hints) and all(v["p"] is None for v in hints)
    assert all("placeholder" in m for m in r.mapping) and by_ph


def test_decisions_merge_and_manual(pdf_state):
    r0 = render(pdf_state)
    street = next(vid for vid, v in r0.variants.items() if v["t"] == "ul. Lasówka")
    pzt = next(vid for vid, v in r0.variants.items() if v["t"] == "PZT")
    r1 = render(pdf_state, decisions={street: "no", pzt: "yes"})
    assert "ul. Lasówka" in r1.markdown and "PZT" not in r1.markdown
    assert r1.review["todo"] == r0.review["todo"] - 1 and r1.review["decided"] == 2
    # scalenie: "Habryków" (niejednoznaczne nazwisko) → placeholder Anny
    habr = next(vid for vid, v in r0.variants.items() if v["t"] == "Habryków")
    anna_k = r0.variants[next(vid for vid, v in r0.variants.items() if v["t"] == "Anny Habryki")]["k"]
    r2 = render(pdf_state, merges={r0.variants[habr]["k"]: anna_k})
    anna_ph = next(m for m in r2.mapping if "Anny Habryki" in m["variants"])
    assert "Habryków" in anna_ph["variants"]
    # ręczne zaznaczenie pominiętego fragmentu – wszystkie wystąpienia
    r3 = render(pdf_state, manual=[ManualSpan(text="Podgórze", entity_type="LOCATION")])
    assert "Podgórze" not in r3.markdown and "[MIEJSCOWOŚĆ_1]" in r3.markdown
    # ręczne zaznaczenie z typem "inne" i tylko jedno wystąpienie
    item = next(i for i, (_, _, t) in enumerate(pdf_state.items) if "w aktach sprawy" in t)
    start = pdf_state.items[item][2].index("aktach")
    r4 = render(pdf_state, manual=[ManualSpan(text="aktach", entity_type="OTHER", all_occurrences=False, item=item, start=start + 1, end=start + 7)])
    assert "[ZANONIMIZOWANE_DANE_1]" in r4.markdown and r4.markdown.count("[ZANONIMIZOWANE_DANE_1]") == 1


def test_preview_segments_cover_text(pdf_state):
    r = render(pdf_state)
    for b in r.preview:
        if "orig" in b:
            text = pdf_state.items[b["i"]][2]
            assert "".join(s["t"] for s in b["orig"]) == text
            for s in b["orig"]:
                if "v" in s:
                    assert s["v"] in r.variants


def test_pasted_text_is_merged_and_analyzed(settings):
    from app.pipeline import analyze_text, text_to_blocks

    text = """DECYZJA
po rozpatrzeniu odwołania: pani Anny Habryki i pana Mariusza
Habryki, działających przez pełnomocnika: radcę prawnego Tomasza Wierzbickiego;
od decyzji Prezydenta Miasta Krakowa nr 285/6740.1/2025 z 31 marca 2025 r., w przedmiocie
zatwierdzenia projektu i udzielenia Inwestorowi: Gumniska sp. z o.o. pozwolenia na budowę przy
ul. Lasówka w Krakowie, na działkach nr: 12/3, 14 obr. 18 Podgórze; zwanego dalej inwestycją.
2
Od ww. decyzji odwołali się: pani Anna Habryka i pan Mariusz Habryka, działający przez
pełnomocnika: radcę prawnego Tomasza Wierzbickiego – strony postępowania prowadzonego przez
organ I instancji, w terminie przewidzianym w art. 129 § 2 kpa.
Pani Habryka nie stawiła się na rozprawie, pan Habryka stawił się osobiście.
"""
    blocks = text_to_blocks(text, settings)
    texts = [b.text for b in blocks]
    assert any("pana Mariusza Habryki, działających" in t for t in texts)
    r = render(analyze_text(text, settings))
    md = r.markdown
    anna = next(m for m in r.mapping if "Anny Habryki" in m["variants"])
    assert "Anna Habryka" in anna["variants"] and "Pani " + anna["placeholder"] + " nie" in md
    assert "Habryk" not in md and "Gumniska" not in md


def test_api_paste(client):
    c, _ = client
    r = c.post("/api/anonymize-paste", json={"text": "Skarżący Jan Kowalski, zam. ul. Długa 5, wniósł skargę.\nPełnomocnik Kowalskiego.", "job_id": "j1"})
    assert r.status_code == 200, r.text
    j = r.json()
    body = j["markdown"].split("\n---\n", 1)[1]
    assert body.count("[OSOBA_1]") == 2 and j["doc_id"]
    assert c.post("/api/anonymize-paste", json={"text": "   "}).status_code == 400
