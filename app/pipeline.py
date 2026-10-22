"""Pipeline: .docx (albo .pdf / wklejony tekst) → bloki → analiza (Presidio + ocena pewności) → decyzje człowieka → Markdown + mapa.

Analiza (`analyze_document`) jest kosztowna i wykonywana raz; wynik (`DocState`) trzymamy w pamięci.
Rendering (`render`) jest tani i powtarzany po każdej decyzji recenzenta (OK / nie OK / scal / dodaj ręcznie).
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Union

from .docx_reader import Block, FootnoteBlock, TableBlock, TextBlock, drop_page_numbers, merge_wrapped_lines, read_docx
from .engine import Anonymizer, Span, assign_keys, get_anonymizer
from .markdown import ENTITY_NAMES, build_markdown
from .pdf_reader import read_pdf_text
from .settings import Settings, load_settings

Progress = Optional[Callable[[str, int, int], None]]

# Typy dostępne przy ręcznym zaznaczaniu w podglądzie
MANUAL_ENTITY_TYPES = ["PERSON", "ORGANIZATION", "ADDRESS", "LOCATION", "PLOT_NUMBER", "CASE_SIGNATURE", "DATE_TIME", "OTHER"]
MANUAL_LABELS = {"OTHER": "ZANONIMIZOWANE_DANE"}


@dataclass
class ManualSpan:
    text: str
    entity_type: str
    all_occurrences: bool = True
    item: Optional[int] = None
    start: Optional[int] = None
    end: Optional[int] = None
    id: str = ""


@dataclass
class DocState:
    doc_id: str
    blocks: List[Block]
    items: List[Tuple[int, Optional[Tuple[int, int]], str]]  # (indeks bloku, pozycja w tabeli, tekst)
    spans: List[Span]
    settings: Settings
    source_name: Optional[str] = None
    seconds: float = 0.0
    warnings: List[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)


@dataclass
class Result:
    markdown: str
    mapping: List[dict]
    stats: Dict[str, int]
    blocks: int
    seconds: float
    warnings: List[str] = field(default_factory=list)
    preview: List[dict] = field(default_factory=list)
    variants: Dict[str, dict] = field(default_factory=dict)
    keys: Dict[str, dict] = field(default_factory=dict)
    review: Dict[str, int] = field(default_factory=dict)
    doc_id: str = ""


def _texts(blocks: List[Block]):
    """Iterator (indeks bloku, pozycja, tekst) dla wszystkich fragmentów tekstowych."""
    for bi, b in enumerate(blocks):
        if isinstance(b, (TextBlock, FootnoteBlock)):
            yield bi, None, b.text
        elif isinstance(b, TableBlock):
            for ri, row in enumerate(b.rows):
                for ci, cell in enumerate(row):
                    if cell:
                        yield bi, (ri, ci), cell


# ---------------------------------------------------------------------------
# Analiza
# ---------------------------------------------------------------------------
def analyze_blocks(blocks: List[Block], engine: Anonymizer, progress: Progress = None, propagate: bool = True) -> Tuple[list, List[Span]]:
    items = list(_texts(blocks))
    texts = [t for _, _, t in items]
    spans = engine.analyze_items(texts, progress)
    assign_keys(spans, texts)
    if propagate:
        if progress:
            progress("Szukam powtórzeń wykrytych danych", 0, 1)
        spans = engine.propagate(texts, spans)
    spans.sort(key=lambda s: (s.item, s.start))
    return items, spans


def analyze_document(
    source: Union[str, bytes],
    settings: Optional[Settings] = None,
    source_name: Optional[str] = None,
    progress: Progress = None,
) -> DocState:
    settings = settings or load_settings()
    if progress:
        progress("Czytam dokument Word", 0, 1)
    blocks = read_docx(source, settings.docx)
    return analyze_document_blocks(blocks, settings, source_name, progress)


def text_to_blocks(text: str, settings: Optional[Settings] = None) -> List[Block]:
    """Wklejony tekst (z Worda / PDF): linia = akapit; linie z konwersji PDF sklejamy jak w .docx."""
    settings = settings or load_settings()
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in text.replace("\r", "").split("\n")]
    blocks: List[Block] = [TextBlock("paragraph", ln) for ln in lines if ln]
    if settings.docx.drop_page_numbers:
        blocks = drop_page_numbers(blocks)
    if settings.docx.merge_wrapped_lines:
        blocks = merge_wrapped_lines(blocks)
    return blocks


def analyze_text(text: str, settings: Optional[Settings] = None, source_name: Optional[str] = None, progress: Progress = None) -> DocState:
    settings = settings or load_settings()
    return analyze_document_blocks(text_to_blocks(text, settings), settings, source_name or "tekst", progress)


def analyze_pdf(
    source: Union[str, bytes],
    settings: Optional[Settings] = None,
    source_name: Optional[str] = None,
    progress: Progress = None,
) -> DocState:
    """PDF → tekst (warstwa tekstowa) → ta sama ścieżka co wklejony tekst. Skan bez tekstu → PdfError."""
    settings = settings or load_settings()
    if progress:
        progress("Czytam dokument PDF", 0, 1)
    pdf = read_pdf_text(source)
    state = analyze_text(pdf.text, settings, source_name or "dokument.pdf", progress)
    state.warnings = pdf.warnings + state.warnings
    return state


def analyze_file(
    source: Union[str, bytes],
    settings: Optional[Settings] = None,
    source_name: Optional[str] = None,
    progress: Progress = None,
) -> DocState:
    """.pdf albo .docx – wybór po rozszerzeniu nazwy (lub ścieżki)."""
    name = source_name or (source if isinstance(source, str) else "")
    if name.lower().endswith(".pdf"):
        return analyze_pdf(source, settings, source_name, progress)
    return analyze_document(source, settings, source_name, progress)


def analyze_document_blocks(
    blocks: List[Block], settings: Settings, source_name: Optional[str] = None, progress: Progress = None
) -> DocState:
    t0 = time.perf_counter()
    if progress:
        progress("Ładuję silnik językowy", 0, 1)
    engine = get_anonymizer(settings)
    warnings: List[str] = []
    if not blocks:
        warnings.append("Dokument nie zawiera tekstu (pusty lub tylko grafika).")
    items, spans = analyze_blocks(blocks, engine, progress)
    return DocState(
        doc_id=uuid.uuid4().hex[:12],
        blocks=blocks,
        items=items,
        spans=spans,
        settings=settings,
        source_name=source_name,
        seconds=round(time.perf_counter() - t0, 2),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Rendering z decyzjami
# ---------------------------------------------------------------------------
def _key_id(key: str, index: Dict[str, str]) -> str:
    kid = index.get(key)
    if kid is None:
        kid = f"k{len(index) + 1}"
        index[key] = kid
    return kid


def _manual_spans(state: DocState, manual: List[ManualSpan]) -> List[Span]:
    out: List[Span] = []
    for n, m in enumerate(manual):
        text = (m.text or "").strip()
        if not text or m.entity_type not in MANUAL_ENTITY_TYPES:
            continue
        key = f"MANUAL:{n}:{m.entity_type}:{text.lower()}"
        if m.all_occurrences or m.item is None:
            rx = re.compile(r"(?<!\w)" + r"\s+".join(re.escape(p) for p in text.split()) + r"(?!\w)")
            for i, (_, _, t) in enumerate(state.items):
                for mm in rx.finditer(t):
                    out.append(Span(i, mm.start(), mm.end(), m.entity_type, mm.group(0), "manual", 1.0, "sure", "zaznaczone ręcznie", key))
        elif 0 <= m.item < len(state.items) and m.start is not None and m.end is not None:
            t = state.items[m.item][2]
            s, e = max(0, m.start), min(len(t), m.end)
            if t[s:e] != text:
                # offset z przeglądarki bywa przesunięty – bierzemy wystąpienie najbliższe wskazanemu miejscu
                hits = [mm.start() for mm in re.finditer(re.escape(text), t)]
                if not hits:
                    continue
                s = min(hits, key=lambda h: abs(h - m.start))
                e = s + len(text)
            out.append(Span(m.item, s, e, m.entity_type, t[s:e], "manual", 1.0, "sure", "zaznaczone ręcznie", key))
    return out


def _resolve(spans: List[Span]) -> List[Span]:
    """Ręczne zaznaczenia wygrywają z automatycznymi; poza tym dłuższy fragment wygrywa."""
    ordered = sorted(spans, key=lambda s: (s.item, s.start, 0 if s.source == "manual" else 1, -(s.end - s.start), -s.score))
    out: List[Span] = []
    for s in ordered:
        if out and out[-1].item == s.item and s.start < out[-1].end:
            prev = out[-1]
            if s.source == "manual" and prev.source != "manual":
                out[-1] = s
            elif s.source == prev.source and (s.end - s.start, s.score) > (prev.end - prev.start, prev.score):
                out[-1] = s
            continue
        out.append(s)
    return out


def render(
    state: DocState,
    decisions: Optional[Dict[str, str]] = None,
    merges: Optional[Dict[str, str]] = None,
    manual: Optional[List[ManualSpan]] = None,
) -> Result:
    """Buduje wynik z uwzględnieniem decyzji recenzenta.

    decisions: id wariantu (klucz|tekst) → "yes" | "no";  merges: id klucza → id klucza docelowego;
    manual: ręcznie zaznaczone fragmenty.
    """
    t0 = time.perf_counter()
    decisions = decisions or {}
    merges = merges or {}
    settings = state.settings
    labels: Dict[str, str] = {}
    for et in set(s.entity_type for s in state.spans) | set(MANUAL_ENTITY_TYPES):
        labels[et] = MANUAL_LABELS.get(et) or settings.label_for(et)

    all_spans = list(state.spans) + _manual_spans(state, manual or [])
    key_ids: Dict[str, str] = {}
    for s in sorted(all_spans, key=lambda s: (s.item, s.start)):
        _key_id(s.key, key_ids)

    def canonical(kid: str) -> str:
        seen = set()
        while kid in merges and merges[kid] != kid and kid not in seen:
            seen.add(kid)
            kid = merges[kid]
        return kid

    def vid_of(s: Span) -> str:
        return f"{key_ids[s.key]}|{s.text}"

    def active(s: Span) -> bool:
        d = decisions.get(vid_of(s))
        if d == "yes":
            return True
        if d == "no":
            return False
        return s.status in ("sure", "review")

    # Warianty (klucz + dokładny tekst) – jednostka decyzji recenzenta
    variants: Dict[str, dict] = {}
    for s in all_spans:
        vid = vid_of(s)
        v = variants.get(vid)
        if v is None:
            v = variants[vid] = {
                "k": canonical(key_ids[s.key]), "t": s.text, "e": s.entity_type, "st": s.status, "why": s.reason,
                "d": decisions.get(vid), "n": 0, "src": s.source, "p": None,
            }
        v["n"] += 1
        # najpewniejszy status wśród wystąpień
        rank = {"sure": 0, "review": 1, "hint": 2}
        if rank[s.status] < rank[v["st"]]:
            v["st"], v["why"] = s.status, s.reason

    chosen = _resolve([s for s in all_spans if active(s)])
    chosen_set = {(s.item, s.start, s.end) for s in chosen}

    # Placeholdery wg kolejności pierwszego aktywnego wystąpienia
    placeholders: Dict[str, str] = {}
    counters: Dict[str, int] = {}
    keys: Dict[str, dict] = {}
    for s in chosen:
        kid = canonical(key_ids[s.key])
        if kid not in placeholders:
            label = labels.get(s.entity_type, s.entity_type)
            n = counters.get(label, 0) + 1
            counters[label] = n
            placeholders[kid] = f"[{label}_{n}]"
            keys[kid] = {"e": s.entity_type, "p": placeholders[kid], "variants": [], "count": 0, "review": False}
        k = keys[kid]
        if s.text not in k["variants"]:
            k["variants"].append(s.text)
        k["count"] += 1
        if s.status != "sure" and decisions.get(vid_of(s)) is None:
            k["review"] = True
    for vid, v in variants.items():
        v["p"] = placeholders.get(v["k"])
    # klucze bez aktywnych wystąpień (np. sugestie) – żeby UI znało typ
    for s in all_spans:
        kid = canonical(key_ids[s.key])
        if kid not in keys:
            keys[kid] = {"e": s.entity_type, "p": None, "variants": [], "count": 0, "review": False}

    # Podmiana w tekstach
    by_item: Dict[int, List[Span]] = {}
    for s in chosen:
        by_item.setdefault(s.item, []).append(s)
    replaced: Dict[tuple, str] = {}
    for i, (bi, pos, text) in enumerate(state.items):
        found = sorted(by_item.get(i, []), key=lambda s: s.start)
        if not found:
            continue
        parts, p = [], 0
        for s in found:
            parts.append(text[p : s.start])
            parts.append(placeholders[canonical(key_ids[s.key])])
            p = s.end
        parts.append(text[p:])
        replaced[(bi, pos)] = "".join(parts)

    anon_blocks: List[Block] = []
    for bi, b in enumerate(state.blocks):
        if isinstance(b, TextBlock):
            anon_blocks.append(TextBlock(b.kind, replaced.get((bi, None), b.text), level=b.level, ordered=b.ordered, alignment=b.alignment))
        elif isinstance(b, FootnoteBlock):
            anon_blocks.append(FootnoteBlock(id=b.id, text=replaced.get((bi, None), b.text)))
        elif isinstance(b, TableBlock):
            rows = [[replaced.get((bi, (ri, ci)), c) for ci, c in enumerate(row)] for ri, row in enumerate(b.rows)]
            anon_blocks.append(TableBlock(rows=rows))

    mapping = [
        {"placeholder": k["p"], "entity_type": k["e"], "variants": k["variants"], "count": k["count"], "review": k["review"]}
        for k in keys.values()
        if k["p"]
    ]
    mapping.sort(key=lambda m: (m["placeholder"].rsplit("_", 1)[0], int(m["placeholder"].rstrip("]").rsplit("_", 1)[1])))
    stats: Dict[str, int] = {}
    for s in chosen:
        stats[s.entity_type] = stats.get(s.entity_type, 0) + 1

    md = build_markdown(anon_blocks, mapping, labels, settings.output, state.source_name)

    # Podgląd: segmenty {t, v} (v = id wariantu) – wszystkie fragmenty, także nieaktywne (sugestie / odrzucone)
    seg_spans: Dict[int, List[Span]] = {}
    for s in _resolve(all_spans):
        seg_spans.setdefault(s.item, []).append(s)
    preview = _build_preview(state, seg_spans, vid_of, chosen_set)

    review = {
        "todo": sum(1 for v in variants.values() if v["st"] == "review" and v["d"] is None),
        "hints": sum(1 for v in variants.values() if v["st"] == "hint" and v["d"] is None),
        "decided": sum(1 for v in variants.values() if v["d"] is not None),
    }
    return Result(
        markdown=md,
        mapping=mapping,
        stats=stats,
        blocks=len(state.blocks),
        seconds=round(state.seconds + time.perf_counter() - t0, 2),
        warnings=state.warnings,
        preview=preview,
        variants=variants,
        keys=keys,
        review=review,
        doc_id=state.doc_id,
    )


def _segments(text: str, found: List[Span], vid_of, chosen_set) -> List[dict]:
    segs: List[dict] = []
    pos = 0
    for s in sorted(found, key=lambda s: s.start):
        if s.start < pos:
            continue
        if s.start > pos:
            segs.append({"t": text[pos : s.start]})
        seg = {"t": s.text, "v": vid_of(s), "i": s.item, "s": s.start}
        if (s.item, s.start, s.end) not in chosen_set:
            seg["off"] = True
        segs.append(seg)
        pos = s.end
    if pos < len(text):
        segs.append({"t": text[pos:]})
    return segs


def _build_preview(state: DocState, seg_spans: Dict[int, List[Span]], vid_of, chosen_set) -> List[dict]:
    item_index = {(bi, pos): i for i, (bi, pos, _) in enumerate(state.items)}

    def segs(bi, pos, text):
        i = item_index.get((bi, pos))
        found = seg_spans.get(i, []) if i is not None else []
        return {"i": i, "orig": _segments(text, found, vid_of, chosen_set)}

    out: List[dict] = []
    for bi, b in enumerate(state.blocks):
        if isinstance(b, TextBlock):
            out.append({"kind": b.kind, "level": b.level, "ordered": b.ordered, "alignment": b.alignment, **segs(bi, None, b.text)})
        elif isinstance(b, FootnoteBlock):
            out.append({"kind": "footnote", "id": b.id, **segs(bi, None, b.text)})
        elif isinstance(b, TableBlock):
            rows = [[segs(bi, (ri, ci), c) for ci, c in enumerate(row)] for ri, row in enumerate(b.rows)]
            out.append({"kind": "table", "rows": rows})
    return out


# ---------------------------------------------------------------------------
# Wygodne funkcje (CLI, testy, strona ustawień)
# ---------------------------------------------------------------------------
def anonymize_docx(
    source: Union[str, bytes],
    settings: Optional[Settings] = None,
    source_name: Optional[str] = None,
    progress: Progress = None,
) -> Result:
    state = analyze_document(source, settings, source_name, progress)
    return render(state)


def anonymize_file(
    source: Union[str, bytes],
    settings: Optional[Settings] = None,
    source_name: Optional[str] = None,
    progress: Progress = None,
) -> Result:
    """Jak `anonymize_docx`, ale przyjmuje też .pdf (po rozszerzeniu)."""
    return render(analyze_file(source, settings, source_name, progress))


def anonymize_plain_text(text: str, settings: Optional[Settings] = None) -> Result:
    """Anonimizacja zwykłego tekstu (do testów ustawień w UI)."""
    t0 = time.perf_counter()
    settings = settings or load_settings()
    engine = get_anonymizer(settings)
    paragraphs = [p for p in text.replace("\r", "").split("\n")]
    blocks: List[Block] = [TextBlock("paragraph", p) for p in paragraphs if p.strip()]
    items, spans = analyze_blocks(blocks, engine)
    plain = settings.model_copy(deep=True)
    plain.output.title, plain.output.include_intro, plain.output.include_legend = "", False, False
    state = DocState(doc_id="", blocks=blocks, items=items, spans=spans, settings=plain)
    r = render(state)
    r.seconds = round(time.perf_counter() - t0, 2)
    return r
