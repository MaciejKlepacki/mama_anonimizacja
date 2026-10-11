"""Rendering bloków do Markdown zoptymalizowanego pod wklejenie do czatu z LLM."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .docx_reader import Block, FootnoteBlock, TableBlock, TextBlock
from .settings import OutputSettings

_MD_SPECIAL = re.compile(r"(?<!\\)([*_`#>|])")


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _escape_text(text: str) -> str:
    """Minimalne escapowanie: tylko znaki, które mogłyby zmienić strukturę Markdown."""
    lines = []
    for ln in text.split("\n"):
        if re.match(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>)", ln):
            ln = "\\" + ln.lstrip()
        lines.append(ln)
    return "\n".join(lines)


def render_blocks(blocks: List[Block]) -> str:
    out: List[str] = []
    footnotes: List[FootnoteBlock] = []
    prev_kind: Optional[str] = None
    counters: Dict[int, int] = {}
    for b in blocks:
        if isinstance(b, FootnoteBlock):
            footnotes.append(b)
            continue
        if isinstance(b, TableBlock):
            if not b.rows:
                continue
            if out and out[-1] != "":
                out.append("")
            width = max(len(r) for r in b.rows)
            rows = [r + [""] * (width - len(r)) for r in b.rows]
            header = rows[0]
            out.append("| " + " | ".join(_escape_cell(c) or " " for c in header) + " |")
            out.append("|" + "|".join([" --- "] * width) + "|")
            for r in rows[1:]:
                out.append("| " + " | ".join(_escape_cell(c) or " " for c in r) + " |")
            out.append("")
            prev_kind = "table"
            continue
        if b.kind == "heading":
            if out and out[-1] != "":
                out.append("")
            out.append("#" * (b.level + 1 if b.level < 6 else 6) + " " + b.text.strip())
            out.append("")
        elif b.kind == "list":
            if prev_kind not in ("list",) and out and out[-1] != "":
                out.append("")
            if prev_kind != "list":
                counters = {}
            lvl = max(0, b.level)
            if b.ordered:
                counters[lvl] = counters.get(lvl, 0) + 1
                for deeper in [k for k in counters if k > lvl]:
                    counters.pop(deeper)
                marker = f"{counters[lvl]}."
            else:
                marker = "-"
            indent = "  " * lvl
            text = _escape_text(b.text).replace("\n", "\n" + indent + "  ")
            out.append(f"{indent}{marker} {text}")
        else:
            if prev_kind == "list":
                out.append("")
            text = _escape_text(b.text).replace("\n", "  \n")
            out.append(text)
            out.append("")
        prev_kind = b.kind
    if footnotes:
        if out and out[-1] != "":
            out.append("")
        out.append("### Przypisy")
        out.append("")
        for fn in footnotes:
            out.append(f"[^{fn.id}]: {fn.text}")
        out.append("")
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    return md


def _legend(mapping: List[dict], labels: Dict[str, str], entity_names: Dict[str, str]) -> str:
    by_label: Dict[str, int] = {}
    for m in mapping:
        label = m["placeholder"].strip("[]").rsplit("_", 1)[0]
        by_label[label] = by_label.get(label, 0) + 1
    if not by_label:
        return ""
    lines = ["| Placeholder | Znaczenie | Liczba różnych |", "| --- | --- | --- |"]
    label_to_entity = {v: k for k, v in labels.items()}
    for label, n in by_label.items():
        ent = label_to_entity.get(label, label)
        lines.append(f"| `[{label}_n]` | {entity_names.get(ent, ent)} | {n} |")
    return "\n".join(lines)


ENTITY_NAMES = {
    "PERSON": "osoba (imię i nazwisko)",
    "ADDRESS": "adres",
    "LOCATION": "miejscowość / miejsce",
    "ORGANIZATION": "organizacja",
    "PLOT_NUMBER": "numer działki ewidencyjnej",
    "PL_KW": "numer księgi wieczystej",
    "PL_PESEL": "PESEL",
    "PL_NIP": "NIP",
    "PL_REGON": "REGON",
    "PL_KRS": "numer KRS",
    "PL_ID_CARD": "seria i numer dowodu osobistego",
    "PHONE_NUMBER": "numer telefonu",
    "EMAIL_ADDRESS": "adres e-mail",
    "IBAN_CODE": "numer rachunku bankowego",
    "DATE_TIME": "data",
    "CASE_SIGNATURE": "sygnatura akt",
    "URL": "adres www",
}


def build_markdown(
    blocks: List[Block],
    mapping: List[dict],
    labels: Dict[str, str],
    output: OutputSettings,
    source_name: Optional[str] = None,
) -> str:
    body = render_blocks(blocks)
    parts: List[str] = []
    if output.title:
        parts.append(f"# {output.title.strip()}")
        parts.append("")
    if output.include_intro:
        parts.append(
            "> Dokument zanonimizowany automatycznie. Dane identyfikujące zastąpiono placeholderami "
            "w nawiasach kwadratowych, np. `[OSOBA_1]`. Ten sam placeholder oznacza w całym dokumencie "
            "tę samą osobę lub ten sam obiekt. Traktuj placeholdery jak nazwy własne i nie próbuj ich odgadywać."
        )
        parts.append("")
    if output.include_legend:
        legend = _legend(mapping, labels, ENTITY_NAMES)
        if legend:
            parts.append("**Legenda placeholderów**")
            parts.append("")
            parts.append(legend)
            parts.append("")
    if parts:
        parts.append("---")
        parts.append("")
    parts.append(body)
    return "\n".join(parts)
