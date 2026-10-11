"""Generuje przykładowy wyrok (fikcyjne dane) do testów: tests/fixtures/wyrok_przyklad.docx."""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH


def build(path: Path) -> Path:
    doc = Document()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("WYROK").bold = True
    p = doc.add_paragraph("W IMIENIU RZECZYPOSPOLITEJ POLSKIEJ")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("Dnia 12 marca 2024 r.")
    doc.add_paragraph(
        "Wojewódzki Sąd Administracyjny w Warszawie w składzie: Przewodniczący Sędzia WSA Anna Nowak-Wiśniewska, "
        "Sędziowie: Sędzia WSA Piotr Dąbrowski, Asesor WSA Marek Zieliński (spr.), Protokolant Katarzyna Mazur, "
        "po rozpoznaniu na rozprawie w dniu 12 marca 2024 r. sprawy ze skargi Jana Kowalskiego na decyzję "
        "Wojewody Mazowieckiego z dnia 3 stycznia 2024 r. nr WI-II.7840.1.2024 w przedmiocie pozwolenia na budowę"
    )
    doc.add_heading("Uzasadnienie", level=1)
    doc.add_paragraph(
        "Skarżący Jan Kowalski, PESEL 44051401359, zamieszkały przy ul. Długiej 5 m. 3, 00-001 Warszawa, "
        "reprezentowany przez adw. Tomasza Wróbla (tel. 601 234 567, e-mail t.wrobel@kancelaria-przyklad.pl), "
        "wniósł skargę na decyzję Wojewody Mazowieckiego."
    )
    doc.add_paragraph(
        "Inwestycja obejmuje budowę budynku mieszkalnego na działkach nr 123/4 i 125, obręb 0012 Mokotów, "
        "dla których Sąd Rejonowy prowadzi księgę wieczystą KW WA1M/00123456/7. Działka ewidencyjna nr 126/2 "
        "stanowi własność Marii Zielińskiej."
    )
    doc.add_paragraph("Organ ustalił, co następuje:")
    doc.add_paragraph("działka nr 123/4 graniczy z drogą publiczną;", style="List Bullet")
    doc.add_paragraph("uczestnik Kowalski nie wniósł uwag w terminie;", style="List Bullet")
    doc.add_paragraph("pełnomocnik Wróbel złożył wniosek dowodowy.", style="List Bullet")
    table = doc.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    rows = [
        ("Strona", "Adres", "Działka"),
        ("Jan Kowalski", "ul. Długa 5 m. 3, 00-001 Warszawa", "123/4"),
        ("Maria Zielińska", "al. Jerozolimskie 100/12, 02-222 Warszawa", "126/2"),
    ]
    for r, vals in zip(table.rows, rows):
        for c, v in zip(r.cells, vals):
            c.text = v
    doc.add_paragraph(
        "W tym stanie rzeczy Wojewódzki Sąd Administracyjny w Warszawie, na podstawie art. 151 p.p.s.a., "
        "orzekł jak w sentencji. Sprawę zarejestrowano pod sygn. akt II SA/Wa 1234/23."
    )
    doc.add_paragraph("Postanowienia dodatkowe:")
    doc.add_paragraph("Kosztami obciążyć Jana Kowalskiego.", style="List Number")
    doc.add_paragraph("Zwrócić opłatę Marii Zielińskiej.", style="List Number")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


if __name__ == "__main__":
    out = build(Path(__file__).parent / "fixtures" / "wyrok_przyklad.docx")
    print(out)
