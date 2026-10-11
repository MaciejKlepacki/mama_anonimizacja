"""Pipeline: .docx → bloki → anonimizacja (Presidio) → Markdown + mapa placeholderów."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from .docx_reader import Block, FootnoteBlock, TableBlock, TextBlock, read_docx
from .engine import Anonymizer, get_anonymizer
from .markdown import build_markdown
from .settings import Settings, load_settings


@dataclass
class Result:
    markdown: str
    mapping: List[dict]
    stats: Dict[str, int]
    blocks: int
    seconds: float
    warnings: List[str] = field(default_factory=list)
    preview: List[dict] = field(default_factory=list)


PROPAGATE_ENTITIES = {
    "PERSON", "PLOT_NUMBER", "PL_KW", "PL_PESEL", "PL_NIP", "PL_REGON", "PL_KRS", "PL_ID_CARD",
    "PHONE_NUMBER", "EMAIL_ADDRESS", "IBAN_CODE", "ADDRESS", "LOCATION", "ORGANIZATION",
}


def _texts(blocks: List[Block]):
    """Iterator (indeks bloku, indeks w bloku, tekst) dla wszystkich fragmentów tekstowych."""
    for bi, b in enumerate(blocks):
        if isinstance(b, (TextBlock, FootnoteBlock)):
            yield bi, None, b.text
        elif isinstance(b, TableBlock):
            for ri, row in enumerate(b.rows):
                for ci, cell in enumerate(row):
                    if cell:
                        yield bi, (ri, ci), cell


def anonymize_blocks(blocks: List[Block], engine: Anonymizer, propagate: bool = True, spans: Optional[dict] = None):
    """Dwa przebiegi: 1) analiza wszystkich fragmentów, 2) propagacja znanych wartości + podmiana.

    Jeśli podano `spans` (dict), trafiają do niego wykryte fragmenty:
    (indeks bloku, pozycja) → [(start, end, typ encji, placeholder)].
    """
    mapper = engine.new_mapper()
    items = list(_texts(blocks))
    analyzed = [(bi, pos, text, engine.analyze(text)) for bi, pos, text in items]

    known: Dict[str, List[str]] = {}
    if propagate:
        for _, _, text, results in analyzed:
            for r in results:
                if r.entity_type in PROPAGATE_ENTITIES or r.entity_type not in engine.settings.entities:
                    known.setdefault(r.entity_type, []).append(text[r.start : r.end])
    known_recs = engine.known_value_recognizers(known) if known else []

    replaced: Dict[tuple, str] = {}
    for bi, pos, text, results in analyzed:
        results = engine.analyze_with_known(text, results, known_recs)
        replaced[(bi, pos)], used = engine.anonymize_text(text, mapper, results)
        if spans is not None and used:
            spans[(bi, pos)] = [
                (r.start, r.end, r.entity_type, mapper.by_key.get(mapper.key(r.entity_type, text[r.start : r.end]), ""))
                for r in sorted(used, key=lambda r: r.start)
            ]

    out: List[Block] = []
    for bi, b in enumerate(blocks):
        if isinstance(b, TextBlock):
            out.append(TextBlock(b.kind, replaced.get((bi, None), b.text), level=b.level, ordered=b.ordered, alignment=b.alignment))
        elif isinstance(b, FootnoteBlock):
            out.append(FootnoteBlock(id=b.id, text=replaced.get((bi, None), b.text)))
        elif isinstance(b, TableBlock):
            rows = [[replaced.get((bi, (ri, ci)), c) for ci, c in enumerate(row)] for ri, row in enumerate(b.rows)]
            out.append(TableBlock(rows=rows))
    return out, mapper


def _segments(text: str, found: List[tuple], anonymized: bool) -> List[dict]:
    """Dzieli tekst na segmenty {t, e, p}; wykryte fragmenty mają typ encji (e) i placeholder (p)."""
    segs: List[dict] = []
    pos = 0
    for start, end, entity, ph in found:
        if start < pos:
            continue
        if start > pos:
            segs.append({"t": text[pos:start]})
        segs.append({"t": ph if anonymized else text[start:end], "e": entity, "p": ph})
        pos = end
    if pos < len(text):
        segs.append({"t": text[pos:]})
    return segs


def build_preview(blocks: List[Block], spans: dict) -> List[dict]:
    """Podgląd obok siebie: dla każdego bloku wersja oryginalna i zanonimizowana z zaznaczeniami."""

    def pair(bi, pos, text):
        found = spans.get((bi, pos), [])
        return {"orig": _segments(text, found, False), "anon": _segments(text, found, True)}

    out: List[dict] = []
    for bi, b in enumerate(blocks):
        if isinstance(b, TextBlock):
            out.append({"kind": b.kind, "level": b.level, "ordered": b.ordered, "alignment": b.alignment, **pair(bi, None, b.text)})
        elif isinstance(b, FootnoteBlock):
            out.append({"kind": "footnote", "id": b.id, **pair(bi, None, b.text)})
        elif isinstance(b, TableBlock):
            rows = [[pair(bi, (ri, ci), c) for ci, c in enumerate(row)] for ri, row in enumerate(b.rows)]
            out.append({"kind": "table", "rows": rows})
    return out


def anonymize_docx(
    source: Union[str, bytes],
    settings: Optional[Settings] = None,
    source_name: Optional[str] = None,
) -> Result:
    t0 = time.perf_counter()
    settings = settings or load_settings()
    engine = get_anonymizer(settings)
    blocks = read_docx(source, settings.docx)
    warnings: List[str] = []
    if not blocks:
        warnings.append("Dokument nie zawiera tekstu (pusty lub tylko grafika).")
    spans: dict = {}
    anon_blocks, mapper = anonymize_blocks(blocks, engine, spans=spans)
    md = build_markdown(anon_blocks, mapper.mapping(), engine.labels, settings.output, source_name)
    return Result(
        markdown=md,
        mapping=mapper.mapping(),
        stats=mapper.stats(),
        blocks=len(blocks),
        seconds=round(time.perf_counter() - t0, 2),
        warnings=warnings,
        preview=build_preview(blocks, spans),
    )


def anonymize_plain_text(text: str, settings: Optional[Settings] = None) -> Result:
    """Anonimizacja zwykłego tekstu (do testów ustawień w UI)."""
    t0 = time.perf_counter()
    settings = settings or load_settings()
    engine = get_anonymizer(settings)
    paragraphs = [p for p in text.replace("\r", "").split("\n")]
    blocks: List[Block] = [TextBlock("paragraph", p) for p in paragraphs if p.strip()]
    anon_blocks, mapper = anonymize_blocks(blocks, engine)
    md = "\n\n".join(b.text for b in anon_blocks if isinstance(b, TextBlock))
    return Result(
        markdown=md,
        mapping=mapper.mapping(),
        stats=mapper.stats(),
        blocks=len(blocks),
        seconds=round(time.perf_counter() - t0, 2),
    )
