"""Prawdziwe pliki .pdf do testów (fikcyjne dane): ta sama decyzja co w make_fixture_pdf.py, złożona w strony.

- decyzja.pdf – kilka stron, linie łamane jak w PDF, numery stron na dole, polskie znaki,
- skan.pdf – strona z samym obrazkiem (bez warstwy tekstowej),
- czesciowy_skan.pdf – strona z tekstem + pusta strona (np. zeskanowany załącznik).
"""

from pathlib import Path

import pymupdf

from tests.make_fixture_pdf import LINES

FONT_SIZE = 11
LINE_H = 15
TOP, LEFT = 72, 60


def _writer(page, lines, start_y=TOP):
    font = pymupdf.Font("helv")  # TextWriter osadza czcionkę z pełnym Unicode (ą, ę, ł, ż…)
    tw = pymupdf.TextWriter(page.rect)
    y = start_y
    for ln in lines:
        tw.append((LEFT, y), ln, font=font, fontsize=FONT_SIZE)
        y += LINE_H
    tw.write_text(page)


def build(path: Path) -> Path:
    """Decyzja: samotne linie z cyfrą w LINES to numery stron → stopka i nowa strona."""
    doc = pymupdf.open()
    page_lines = []
    for ln in LINES + ["5"]:
        if ln.isdigit():
            page = doc.new_page()
            _writer(page, page_lines)
            font = pymupdf.Font("helv")
            tw = pymupdf.TextWriter(page.rect)
            tw.append((page.rect.width / 2, page.rect.height - 40), ln, font=font, fontsize=9)
            tw.write_text(page)
            page_lines = []
        else:
            page_lines.append(ln)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def build_scan(path: Path) -> Path:
    """Strona bez tekstu – tylko szary prostokąt jako obraz (jak skan)."""
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 40, 40), False)
    pix.clear_with(200)
    page.insert_image(page.rect, pixmap=pix)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def build_partial_scan(path: Path) -> Path:
    doc = pymupdf.open()
    _writer(doc.new_page(), ["Pozew wniósł Jan Kowalski, PESEL 44051401359, zamieszkały w Warszawie."])
    doc.new_page()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


if __name__ == "__main__":
    out = Path(__file__).parent / "fixtures"
    print(build(out / "decyzja.pdf"), build_scan(out / "skan.pdf"), build_partial_scan(out / "czesciowy_skan.pdf"))
