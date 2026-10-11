import json

from app.docx_reader import TableBlock, TextBlock, read_docx
from app.pipeline import anonymize_docx, anonymize_plain_text
from app.settings import CustomRecognizer, Settings


def test_read_docx_structure(fixture_docx):
    blocks = read_docx(str(fixture_docx))
    kinds = [getattr(b, "kind") for b in blocks]
    assert "heading" in kinds and "list" in kinds and "table" in kinds
    headings = [b for b in blocks if isinstance(b, TextBlock) and b.kind == "heading"]
    assert any(h.text == "Uzasadnienie" and h.level == 1 for h in headings)
    assert any(h.text == "WYROK" for h in headings)  # pogrubione + wyśrodkowane
    table = next(b for b in blocks if isinstance(b, TableBlock))
    assert table.rows[0] == ["Strona", "Adres", "Działka"]
    ordered = [b for b in blocks if isinstance(b, TextBlock) and b.kind == "list" and b.ordered]
    assert len(ordered) == 2


def test_docx_to_markdown(fixture_docx, settings):
    r = anonymize_docx(str(fixture_docx), settings, source_name="wyrok.docx")
    md = r.markdown
    # dane wrażliwe zniknęły
    for secret in ["Kowalski", "Zielińsk", "Wróbl", "Wróbel", "Nowak", "Dąbrowski", "Mazur", "44051401359",
                   "Długa", "Długiej", "Jerozolimskie", "123/4", "126/2", "WA1M", "601 234 567", "kancelaria-przyklad"]:
        assert secret not in md, secret
    # kontekst instytucjonalny został
    assert "Wojewódzki Sąd Administracyjny w Warszawie" in md
    assert "Wojewody Mazowieckiego" in md
    # spójność: skarżący ma jeden placeholder w akapicie, liście i tabeli
    assert md.count("[OSOBA_5]") >= 4
    # tabela: numer działki bez kontekstu w komórce też podmieniony (propagacja)
    assert "| [OSOBA_5] | [ADRES_1], [ADRES_2] | [DZIAŁKA_1] |" in md
    # "ul. Długiej 5 m. 3" (akapit) i "ul. Długa 5 m. 3" (tabela) → ten sam adres (lematyzacja)
    assert next(m for m in r.mapping if m["placeholder"] == "[ADRES_1]")["count"] == 2
    # struktura markdown
    assert md.startswith("# Dokument (zanonimizowany)")
    assert "## Uzasadnienie" in md
    assert "\n- działka nr [DZIAŁKA_1] graniczy" in md
    assert "\n1. Kosztami obciążyć [OSOBA_5].\n2. Zwrócić opłatę [OSOBA_7]." in md
    assert "| Strona | Adres | Działka |\n| --- | --- | --- |" in md
    assert "**Legenda placeholderów**" in md
    assert "\n\n\n" not in md
    assert r.stats["PERSON"] >= 10 and r.stats["PLOT_NUMBER"] >= 5
    json.dumps(r.mapping)  # serializowalne


def test_output_options(fixture_docx, settings):
    s = settings.model_copy(deep=True)
    s.output.include_intro = False
    s.output.include_legend = False
    s.output.title = ""
    md = anonymize_docx(str(fixture_docx), s).markdown
    assert not md.startswith("#  ") and "Legenda" not in md and "> Dokument" not in md
    assert md.startswith("### WYROK")


def test_custom_recognizer_and_deny_list(settings):
    s = settings.model_copy(deep=True)
    s.custom_recognizers = [
        CustomRecognizer(name="nr decyzji", entity="NR_DECYZJI", label="DECYZJA",
                         patterns=[r"\b[A-Z]{1,4}-[A-Z]{1,4}\.\d{3,5}\.\d{1,4}\.\d{4}\b"], score=0.7)
    ]
    s.deny_list = {"ORGANIZATION": ["Spółka Przykładowa"]}
    r = anonymize_plain_text("Decyzja nr WI-II.7840.1.2024 wydana dla Spółka Przykładowa sp. z o.o.", s)
    assert "[DECYZJA_1]" in r.markdown and "[ORGANIZACJA_1]" in r.markdown, r.markdown


def test_entity_can_be_disabled(settings):
    s = settings.model_copy(deep=True)
    s.entities["PLOT_NUMBER"].enabled = False
    r = anonymize_plain_text("działka nr 123/4 należy do Jana Kowalskiego", s)
    assert "123/4" in r.markdown and "[OSOBA_1]" in r.markdown


def test_settings_validation():
    import pytest

    with pytest.raises(ValueError):
        CustomRecognizer(name="x", entity="X", patterns=["("])
    with pytest.raises(ValueError):
        Settings.model_validate({"entities": {"PERSON": {"label": "[ZLE]"}}})
