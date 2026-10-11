import pytest

from app.pipeline import anonymize_plain_text
from app.recognizers import valid_id_card, valid_nip, valid_pesel, valid_regon


def test_checksums():
    assert valid_pesel("44051401359")
    assert not valid_pesel("44051401358")
    assert valid_nip("526-10-40-828")
    assert valid_nip("5261040828")
    assert not valid_nip("5261040829")
    assert valid_regon("000331501")  # 9 cyfr
    assert not valid_regon("010939460")
    assert valid_id_card("ABA300000")
    assert not valid_id_card("ABA300001")


def _anon(engine, text):
    r = anonymize_plain_text(text, engine.settings)
    return r.markdown, r


@pytest.mark.parametrize(
    "text, expected_fragment",
    [
        ("Nieruchomość stanowi działkę nr 123/4 obręb Mokotów.", "działkę nr [DZIAŁKA_1] obręb"),
        ("na działkach nr 123/4 i 125 oraz 7", "nr [DZIAŁKA_1] i [DZIAŁKA_2] oraz [DZIAŁKA_3]"),
        ("Działka ewidencyjna nr 126/2 stanowi", "nr [DZIAŁKA_1] stanowi"),
        ("dz. nr 55/12, obręb 0005", "dz. nr [DZIAŁKA_1], obręb"),
        ("zamieszkały przy ul. Długiej 5 m. 3, 00-001 Warszawa", "przy [ADRES_1], [ADRES_2]"),
        ("al. Jerozolimskie 100/12 w Warszawie", "[ADRES_1] w [MIEJSCOWOŚĆ_1]"),
        ("ul. 3 Maja 7 lok. 2", "[ADRES_1]"),
        ("księga wieczysta KW WA1M/00123456/7", "KW [KW_1]"),
        ("PESEL 44051401359", "PESEL [PESEL_1]"),
        ("NIP 526-10-40-828", "NIP [NIP_1]"),
        ("REGON 000331501", "REGON [REGON_1]"),
        ("KRS 0000123456", "KRS [KRS_1]"),
        ("dowód osobisty seria ABA 300000", "seria [DOWÓD_1]"),
        ("tel. 601 234 567", "tel. [TELEFON_1]"),
        ("e-mail jan@przyklad.pl", "e-mail [EMAIL_1]"),
        ("rachunek PL61109010140000071219812874", "rachunek [IBAN_1]"),
    ],
)
def test_polish_recognizers(engine, text, expected_fragment):
    out, _ = _anon(engine, text)
    assert expected_fragment in out, out


def test_decision_number_is_not_phone(engine):
    out, r = _anon(engine, "decyzja nr WI-II.7840.1.2024 z dnia 3 stycznia 2024 r.")
    assert "TELEFON" not in out
    assert "[SYGNATURA_1]" in out and r.review["todo"] == 1  # numer decyzji – do potwierdzenia


def test_dates_on_by_default_signatures_to_review(engine):
    out, r = _anon(engine, "w dniu 5 maja 2024 r., sygn. akt II SA/Wa 1234/23")
    assert "[DATA_1]" in out and "[SYGNATURA_1]" in out
    assert r.review["todo"] == 1  # sygnatura własnej sprawy – do potwierdzenia
    s = engine.settings.model_copy(deep=True)
    s.entities["DATE_TIME"].enabled = False
    assert "5 maja 2024" in anonymize_plain_text("w dniu 5 maja 2024 r.", s).markdown
    out, r = _anon(engine, "por. wyrok NSA z 5 maja 2024 r., sygn. akt II OSK 1234/23")
    assert "II OSK 1234/23" in out and r.review["hints"] == 1  # cytowane orzeczenie – tylko sugestia


def test_allow_list_keeps_courts_and_voivodes(engine):
    out, _ = _anon(engine, "Wojewódzki Sąd Administracyjny w Warszawie uchylił decyzję Wojewody Mazowieckiego.")
    assert "Wojewódzki Sąd Administracyjny" in out
    assert "Mazowieckiego" in out
    assert "[OSOBA" not in out


def test_consistent_placeholders_across_inflection(engine):
    out, mapper = _anon(
        engine,
        "Skarżący Jan Kowalski wniósł skargę. Pełnomocnik Jana Kowalskiego nie stawił się. "
        "Sąd wezwał Kowalskiego. Uczestniczka Maria Zielińska i pełnomocnik Marii Zielińskiej.",
    )
    assert out.count("[OSOBA_1]") == 3, out
    assert out.count("[OSOBA_2]") == 2, out
    assert "[OSOBA_3]" not in out
    m = {x["placeholder"]: x["variants"] for x in mapper.mapping}
    assert set(m["[OSOBA_1]"]) == {"Jan Kowalski", "Jana Kowalskiego", "Kowalskiego"}


def test_email_domain_pl_is_not_address(engine):
    out, _ = _anon(engine, "e-mail anna@kancelaria.pl. Nieruchomość stanowi działkę nr 123/4.")
    assert "[EMAIL_1]" in out and "[DZIAŁKA_1]" in out and "ADRES" not in out


def test_year_only_is_not_a_date(engine):
    out, _ = _anon(engine, "ustawy z dnia 7 lipca 1994 r. (t.j. Dz.U.2025.1619) oraz decyzji z 2024 roku")
    assert "[DATA_1]" in out and "Dz.U.2025.1619" in out and "z 2024 roku" in out
