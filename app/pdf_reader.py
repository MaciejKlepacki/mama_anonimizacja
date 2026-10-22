"""Czytnik .pdf → zwykły tekst (warstwa tekstowa PDF, lokalnie przez PyMuPDF).

Wynik idzie dalej tą samą ścieżką co wklejony tekst (`pipeline.text_to_blocks`): linia = akapit,
samotne numery stron są usuwane, a połamane linie sklejane w akapity.
Skany (PDF bez warstwy tekstowej) nie są obsługiwane – brak OCR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import List, Union

import pymupdf

from .docx_reader import TextBlock, _can_join

_WS_RE = re.compile(r"[ \t   ]+")


class PdfError(ValueError):
    """Nie da się odczytać tekstu z PDF (uszkodzony, zaszyfrowany albo skan bez warstwy tekstowej)."""


@dataclass
class PdfText:
    text: str
    pages: int
    empty_pages: List[int] = field(default_factory=list)  # numery stron (od 1) bez tekstu – zapewne skany

    @property
    def warnings(self) -> List[str]:
        if not self.empty_pages:
            return []
        nums = ", ".join(str(n) for n in self.empty_pages)
        return [f"Strony PDF bez warstwy tekstowej (skan?) zostały pominięte: {nums}. Sprawdź je ręcznie."]


def _join_lines(lines: List[str]) -> List[str]:
    """Linie jednego bloku PDF → akapity, tą samą regułą co sklejanie linii w .docx z konwersji PDF
    (koniec zdania, nagłówek WIELKIMI literami, punkt listy „a.” / „1)” – nowa linia)."""
    out: List[str] = []
    for ln in lines:
        if out and _can_join(TextBlock("paragraph", out[-1]), TextBlock("paragraph", ln)):
            prev = out[-1]
            hyphen = prev.endswith("-") and not prev.endswith(" -") and ln[:1].islower()
            out[-1] = prev + ("" if hyphen else " ") + ln
        else:
            out.append(ln)
    return out


def read_pdf_text(source: Union[str, bytes, BytesIO]) -> PdfText:
    """Wyciąga tekst z PDF: blok tekstu (akapit wg układu strony) = jedna linia wyniku."""
    try:
        if isinstance(source, BytesIO):
            source = source.getvalue()
        if isinstance(source, (bytes, bytearray)):
            doc = pymupdf.open(stream=bytes(source), filetype="pdf")
        else:
            doc = pymupdf.open(source, filetype="pdf")
    except Exception as e:  # noqa: BLE001 - pymupdf rzuca różne wyjątki
        raise PdfError(f"To nie jest poprawny plik PDF ({e}).") from e
    with doc:
        if doc.needs_pass:
            raise PdfError("PDF jest zabezpieczony hasłem. Zdejmij zabezpieczenie i spróbuj ponownie.")
        paragraphs: List[str] = []
        empty: List[int] = []
        for page in doc:
            found = False
            # (x0, y0, x1, y1, tekst, nr bloku, typ: 0 = tekst, 1 = obraz); sort=True – kolejność czytania
            for b in page.get_text("blocks", sort=True):
                if b[6] != 0:
                    continue
                lines = [_WS_RE.sub(" ", ln).strip() for ln in b[4].replace("\r", "").split("\n")]
                lines = [ln for ln in lines if ln]
                if lines:
                    found = True
                    paragraphs.extend(_join_lines(lines))
            if not found:
                empty.append(page.number + 1)
        pages = doc.page_count
    if not paragraphs:
        raise PdfError(
            "PDF nie zawiera warstwy tekstowej (to prawdopodobnie skan). Rozpoznawanie tekstu (OCR) nie jest "
            "obsługiwane – zrób OCR w innym programie albo wklej tekst ręcznie."
        )
    return PdfText(text="\n".join(paragraphs), pages=pages, empty_pages=empty)
