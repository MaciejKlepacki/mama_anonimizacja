"""Silnik anonimizacji: Presidio Analyzer (spaCy PL + rozpoznawacze), ocena pewności i spójne klucze.

Wynikiem analizy są obiekty `Span` – wykryte fragmenty z oceną pewności:
  * ``sure``   – pewne, anonimizowane bez pytania,
  * ``review`` – niepewne, anonimizowane domyślnie, ale do potwierdzenia przez człowieka,
  * ``hint``   – sugestia, domyślnie NIE anonimizowana (człowiek może włączyć).
Każdy span ma klucz spójności (`key`): ta sama osoba/obiekt w różnych formach → ten sam klucz.
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NerModelConfiguration, SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import SpacyRecognizer

from .names import LO, UP, gender_hint, is_first_name, name_gender, name_stem, stems
from .recognizers import LANG, build_custom_recognizers, build_deny_list_recognizers, build_polish_recognizers
from .settings import Settings

log = logging.getLogger(__name__)

# Mapowanie etykiet modelu pl_core_news_* na encje Presidio
PL_SPACY_MAPPING = {
    "persName": "PERSON",
    "PER": "PERSON",
    "placeName": "LOCATION",
    "geogName": "LOCATION",
    "LOC": "LOCATION",
    "GPE": "LOCATION",
    "orgName": "ORGANIZATION",
    "ORG": "ORGANIZATION",
    "date": "DATE_TIME",
    "time": "DATE_TIME",
}
NER_ENTITIES = ["PERSON", "LOCATION", "ORGANIZATION", "DATE_TIME"]
NAME_ENTITIES = ("PERSON", "LOCATION", "ORGANIZATION")
SPACY_NAME = "SpacyRecognizer"

# Encje, których wartości propagujemy na cały dokument (2. przebieg)
PROPAGATE_ENTITIES = {
    "PERSON", "ORGANIZATION", "LOCATION", "ADDRESS", "PLOT_NUMBER", "PL_KW", "PL_PESEL", "PL_NIP", "PL_REGON",
    "PL_KRS", "PL_ID_CARD", "PHONE_NUMBER", "EMAIL_ADDRESS", "IBAN_CODE", "CASE_SIGNATURE",
}
CHECKSUM_ENTITIES = {"PL_NIP", "PL_REGON", "PL_PESEL", "PL_ID_CARD", "PL_KW", "IBAN_CODE", "EMAIL_ADDRESS", "PL_KRS"}

CHUNK_CHARS = 4000

# Organy i instytucje publiczne – nie są danymi osobowymi; model NER często oznacza je jako organizacje/osoby.
PUBLIC_BODY = re.compile(
    r"^(?:sąd\w*|sądu|sądem|naczeln\w+|wojewódzk\w+|samorządow\w+|minist\w+|rad[aąęy]|prezydent\w*|wojewod\w+|"
    r"urz[ąę]d\w*|starost\w+|burmistrz\w*|wójt\w*|marszał\w+|gmin[aąęy]|powiat\w*|województw\w+|trybunał\w*|"
    r"izb[aąęy]|inspektor\w*|dyrektor\w*|generaln\w+|główn\w+|krajow\w+|narodow\w+|państwow\w+|okręgow\w+|"
    r"regionaln\w+|prokurat\w+|komend\w+|policj\w+|sejm\w*|senat\w*|komisj\w+|kolegium|zarząd\w*|miast[ao]|"
    r"miejsk\w+|skarb\w*|rzecznik\w*|kancelari\w+\s+(?:prezesa|sejmu|senatu|prezydenta)|"
    r"nsa|wsa|sko|tk|sn|zus|nfz|gus|kio|uokik|knf|gddkia|gunb|pinb|winb|rdoś|gdoś|rzgw|pgw|mpwik|zdm|zdw|zikit)\b",
    re.IGNORECASE,
)
TITLE_BEFORE = re.compile(
    r"(?:\bpani?[aąeiu]?|\bp\.|\bpaństw[oa]|prawn\w+|adw\.|adwokat\w*|mec\.|mecenas\w*|mgr|inż\.|dr|prof\.|"
    r"sędzi\w+|notariusz\w*|pełnomocnik\w*:?|skarżąc\w+:?|uczestni\w+:?|wnioskodawc\w+:?|inwestor\w*:?|"
    r"projektant\w*:?|właściciel\w*:?|świadek:?|świadk\w+:?)\s*$",
    re.IGNORECASE,
)
# Miejscowość jako część nazwy organu: "Prezydent Miasta Krakowa", "WSA w Krakowie", "Sąd Rejonowy w Nowym Sączu"
LOC_INSTITUTION_BEFORE = re.compile(
    r"(?:\b(?:miast[ao]|gmin[aąęy]|powiat\w*|wojewod\w+|starost\w+|prezydent\w*|burmistrz\w*|wójt\w*|marszał\w+)\s*$|"
    r"\b(?:sąd\w*|urz[ąę]d\w*|wsa|nsa|sko|prezydent\w*|wojewod\w+|starost\w+|inspektor\w*|kolegium|izb[aąęy]|"
    r"inspektorat\w*|nadleśnictw\w+|komend\w+|prokuratur\w+|administracyjn\w+|rejonow\w+|okręgow\w+|apelacyjn\w+)"
    r"(?:\s+[^\s]+){0,5}?\s+w\s*$)",
    re.IGNORECASE,
)
DATE_LIKE = re.compile(
    r"\d{1,2}\s+(?:stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|września|października|listopada|grudnia)|"
    r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)
CITED_CASE_BEFORE = re.compile(r"\b(?:por\.|zob\.|wyrok\w*|postanowieni\w+|uchwał\w+|orzeczeni\w+|LEX|Legalis)(?!\w)", re.IGNORECASE)
# Słowa oznaczające rolę w postępowaniu – model NER czasem bierze je za nazwy własne ("Inwestorowi", "Skarżący")
ROLE_WORDS = re.compile(
    r"^(?:inwestor\w*|skarżąc\w+|uczestni\w+|wnioskodawc\w+|pełnomocnik\w*|organ\w*|stron[aąęy]|spółk\w+|projektant\w*|"
    r"właściciel\w*|sąd\w*|odwołując\w+|zamawiając\w+|wykonawc\w+|powód\w*|pozwan\w+|oskarżon\w+|świadek|świadk\w+|"
    r"biegł\w+|sędzi\w+|przewodnicząc\w+|protokolant\w*|inspektor\w*|kierownik\w*|dyrektor\w*|prezes\w*|burmistrz\w*|"
    r"wójt\w*|starost\w+|terenach|teren\w*|obszar\w*|rejon\w*|budynk\w*|działk\w*|decyzj\w+|wyrok\w*|ustaw\w+|rozporządzeni\w+)$",
    re.IGNORECASE,
)
LEGAL_FORM_TAIL = re.compile(
    r"\s*(?:sp(?:ółk\w+|\.)\s*z\s*o\.?\s*o\.?|spółk\w+\s+z\s+ograniczoną\s+odpowiedzialnością|s\.?\s?a\.|spółk\w+\s+akcyjn\w+|"
    r"sp\.\s*j\.|spółk\w+\s+jawn\w+|sp\.\s*k\.|spółk\w+\s+komandytow\w+|s\.k\.a\.|sp\.\s*p\.|spółk\w+\s+partnersk\w+|"
    r"p\.s\.a\.|s\.c\.|spółk\w+\s+cywiln\w+)\s*$",
    re.IGNORECASE,
)
GENERIC_ORG_WORDS = {"firma", "spółka", "przedsiębiorstwo", "zakład", "biuro", "grupa", "polska", "polskie", "nowa", "nowe"}


@dataclass
class Span:
    item: int
    start: int
    end: int
    entity_type: str
    text: str
    source: str = ""
    score: float = 0.0
    status: str = "sure"  # sure | review | hint
    reason: str = ""
    key: str = ""

    def overlaps(self, other: "Span") -> bool:
        return self.item == other.item and self.start < other.end and other.start < self.end


# ---------------------------------------------------------------------------
# Klucze spójności
# ---------------------------------------------------------------------------
def normalize_key(entity_type: str, text: str) -> str:
    """Klucz spójności: ta sama osoba/obiekt w różnych formach → ten sam klucz."""
    t = unicodedata.normalize("NFKC", text).strip()
    if entity_type in NAME_ENTITIES:
        if entity_type == "ORGANIZATION":
            t = re.sub(r"[„”\"'«»]", " ", t)
            t = re.sub(r"\.", " ", t)
        return f"{entity_type}:{' '.join(stems(t))}"
    t = t.lower()
    if entity_type == "ADDRESS":
        t = re.sub(r"\s+", " ", t)
        t = re.sub(r"\b(ul\.|ulic[aąyę]|al\.|ale[ij]\w*|pl\.|plac\w*|os\.|osiedl\w*)\s*", "", t)
        t = re.sub(r"\s*(m\.|lok\.|lokal|mieszk\w*)\s*", "/", t)
        return f"{entity_type}:{' '.join(stems(t))}"
    compact = re.sub(r"[\s\-]", "", t)
    return f"{entity_type}:{compact}"


def assign_keys(spans: List[Span], texts: Optional[List[str]] = None) -> None:
    """Nadaje klucze spójności. Dwie fazy: najpierw pełne nazwy, potem pojedyncze słowa (nazwisko/imię).

    "Kowalski" dostaje klucz "Jana Kowalskiego", jeśli w dokumencie jest dokładnie jedna taka osoba;
    przy kilku osobach o tym nazwisku – osobny klucz i status "review".
    """
    persons_full: Dict[str, List[str]] = {}
    singles: List[Span] = []
    for s in spans:
        if s.entity_type == "PERSON" and len(stems(s.text)) == 1:
            singles.append(s)
            continue
        s.key = normalize_key(s.entity_type, s.text)
        if s.entity_type == "PERSON":
            persons_full.setdefault(s.key, stems(s.text))
    by_last: Dict[str, set] = defaultdict(set)
    by_first: Dict[str, set] = defaultdict(set)
    for k, st in persons_full.items():
        by_last[st[-1]].add(k)
        by_first[st[0]].add(k)
    for s in singles:
        w = stems(s.text)[0]
        base = f"PERSON:{w}"
        cands = by_last.get(w, set())
        if len(cands) == 1:
            s.key = next(iter(cands))
            if s.status == "review":
                s.status = "sure"
            s.reason = "nazwisko osoby rozpoznanej w dokumencie"
            continue
        if len(cands) > 1:
            pick = _pick_by_gender(cands, persons_full, texts[s.item] if texts else "", s.start)
            if pick:
                s.key = pick
                s.status = "review"
                s.reason = "samo nazwisko – kilka osób o tym nazwisku; dopasowano po zwrocie pan/pani"
                continue
            s.key = base
            s.status = "review"
            s.reason = f"samo nazwisko – pasuje do {len(cands)} osób, nie wiadomo której"
            continue
        cands = by_first.get(w, set())
        if len(cands) == 1 and is_first_name(s.text):
            s.key = next(iter(cands))
            if s.status != "hint":
                s.status = "review"
            s.reason = "samo imię – przypisano do osoby o tym imieniu"
            continue
        s.key = base


def _stem_gender(stem: str) -> Optional[str]:
    from .names import FEMALE_STEMS, MALE_STEMS

    if stem in MALE_STEMS and stem not in FEMALE_STEMS:
        return "m"
    if stem in FEMALE_STEMS and stem not in MALE_STEMS:
        return "f"
    return None


def _pick_by_gender(cands: set, persons_full: Dict[str, List[str]], text: str, start: int) -> Optional[str]:
    """Spośród kilku osób o tym samym nazwisku wybierz tę, której płeć imienia pasuje do zwrotu "pan/pani"."""
    g = gender_hint(text, start)
    if not g:
        return None
    matching = [k for k in cands if _stem_gender(k.split(":", 1)[1].split()[0]) == g]
    return matching[0] if len(matching) == 1 else None


# ---------------------------------------------------------------------------
# Silnik
# ---------------------------------------------------------------------------
class Anonymizer:
    """Opakowanie Presidio skonfigurowane dla dokumentów polskich."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.analyzer = self._build_analyzer(settings)
        self.deny_only = settings.deny_only_entities()
        self.entities = settings.enabled_entities() + self.deny_only
        self.labels = {e: settings.label_for(e) for e in self.entities}
        self.nlp = self.analyzer.nlp_engine.nlp[LANG]
        self._lock = threading.Lock()
        self._lemma_cache: Dict[str, Tuple[str, ...]] = {}
        self.set_allow_list(settings.allow_list)

    # ----------------------------------------------------------------- build
    @staticmethod
    def _build_analyzer(settings: Settings) -> AnalyzerEngine:
        ner_conf = NerModelConfiguration(
            model_to_presidio_entity_mapping=PL_SPACY_MAPPING,
            labels_to_ignore=[],
            low_score_entity_names=[],
            default_score=0.85,
        )
        nlp_engine = SpacyNlpEngine(
            models=[{"lang_code": LANG, "model_name": settings.spacy_model}],
            ner_model_configuration=ner_conf,
        )
        registry = RecognizerRegistry(supported_languages=[LANG])
        registry.add_recognizer(SpacyRecognizer(supported_language=LANG, supported_entities=NER_ENTITIES))
        for r in build_polish_recognizers():
            registry.add_recognizer(r)
        for r in build_custom_recognizers(settings.custom_recognizers):
            registry.add_recognizer(r)
        for r in build_deny_list_recognizers(settings.deny_list):
            registry.add_recognizer(r)
        return AnalyzerEngine(
            registry=registry,
            nlp_engine=nlp_engine,
            supported_languages=[LANG],
            default_score_threshold=0.0,
        )

    def set_allow_list(self, items: List[str]) -> None:
        self._allow_list = [re.sub(r"\s+", " ", i.strip()).lower() for i in items if i and i.strip()]
        self._allow_lemmas = [self.lemmas(i) for i in self._allow_list]

    # ---------------------------------------------------------------- lemmas
    def lemmas(self, text: str) -> Tuple[str, ...]:
        """Lematy (małymi literami, bez interpunkcji) – do allow-listy odpornej na odmianę."""
        t = re.sub(r"\s+", " ", text.strip())
        cached = self._lemma_cache.get(t)
        if cached is not None:
            return cached
        with self._lock:
            doc = self.nlp(t)
        out = tuple(
            (tok.lemma_ or tok.text).strip().lower() for tok in doc if re.search(r"\w", tok.text)
        )
        if len(self._lemma_cache) > 5000:
            self._lemma_cache.clear()
        self._lemma_cache[t] = out
        return out

    def _allowed(self, fragment: str) -> bool:
        frag = re.sub(r"\s+", " ", fragment.strip()).lower()
        if not frag:
            return False
        for item in self._allow_list:
            if frag == item or (len(frag) >= 3 and frag in item):
                return True
        if not self._allow_lemmas:
            return False
        lf = self.lemmas(frag)
        if not lf:
            return False
        for li in self._allow_lemmas:
            if not li:
                continue
            if _contains(li, lf) or (len(li) >= 2 and _contains(lf, li)):
                return True
        return False

    # --------------------------------------------------------------- analyze
    def analyze_items(
        self, texts: List[str], progress: Optional[Callable[[str, int, int], None]] = None
    ) -> List[Span]:
        """Analiza listy fragmentów (akapity, komórki). Fragmenty łączone są w większe porcje,
        żeby model widział kontekst, a regexy – całe zdania."""
        if not self.entities:
            return []
        chunks = self._chunks(texts)
        spans: List[Span] = []
        total = len(chunks)
        for ci, (text, offsets) in enumerate(chunks):
            if progress:
                progress("Analizuję tekst", ci, total)
            with self._lock:
                results = self.analyzer.analyze(text=text, language=LANG, entities=self.entities, score_threshold=0.0)
            spans.extend(self._to_spans(text, offsets, results))
        if progress:
            progress("Analizuję tekst", total, total)
        spans = self._postprocess(texts, spans)
        return spans

    @staticmethod
    def _chunks(texts: List[str]) -> List[Tuple[str, List[Tuple[int, int, int]]]]:
        chunks: List[Tuple[str, List[Tuple[int, int, int]]]] = []
        buf: List[str] = []
        offsets: List[Tuple[int, int, int]] = []
        pos = 0
        for i, t in enumerate(texts):
            if buf and pos >= CHUNK_CHARS:
                chunks.append(("\n\n".join(buf), offsets))
                buf, offsets, pos = [], [], 0
            if buf:
                pos += 2
            offsets.append((i, pos, pos + len(t)))
            buf.append(t)
            pos += len(t)
        if buf:
            chunks.append(("\n\n".join(buf), offsets))
        return chunks

    def _to_spans(self, text: str, offsets: List[Tuple[int, int, int]], results: List[RecognizerResult]) -> List[Span]:
        starts = [o[1] for o in offsets]
        out: List[Span] = []
        for r in results:
            if r.score < self.settings.threshold_for(r.entity_type):
                continue
            name = str((r.recognition_metadata or {}).get("recognizer_name", ""))
            if self.deny_only and r.entity_type in self.deny_only and not name.startswith("deny:"):
                continue
            # fragment może przeciąć granicę akapitu – tniemy na części
            i = max(0, bisect_right(starts, r.start) - 1)
            while i < len(offsets) and offsets[i][1] < r.end:
                item, s0, e0 = offsets[i]
                s, e = max(r.start, s0), min(r.end, e0)
                if e > s:
                    frag = text[s:e]
                    lead = len(frag) - len(frag.lstrip())
                    trail = len(frag) - len(frag.rstrip())
                    s, e = s + lead, e - trail
                    if e > s:
                        out.append(Span(item, s - s0, e - s0, r.entity_type, text[s:e], name, float(r.score)))
                i += 1
        return out

    # ----------------------------------------------------------- postprocess
    def _postprocess(self, texts: List[str], spans: List[Span]) -> List[Span]:
        spans = [s for s in spans if self._sane(s)]
        spans = _resolve_overlaps(spans)
        spans = self._merge_adjacent_persons(texts, spans)
        kept: List[Span] = []
        for s in spans:
            if not self._classify(texts[s.item], s):
                continue
            kept.append(s)
        return kept

    @staticmethod
    def _sane(s: Span) -> bool:
        frag = s.text
        if not frag.strip():
            return False
        if s.entity_type in NAME_ENTITIES and not re.search(rf"[{UP}{LO}]{{2,}}", frag):
            return False
        if s.entity_type == "PHONE_NUMBER":
            if not re.fullmatch(r"\+?[\d\s\-()]+", frag) or len(re.sub(r"\D", "", frag)) < 9:
                return False
        return True

    @staticmethod
    def _merge_adjacent_persons(texts: List[str], spans: List[Span]) -> List[Span]:
        """"Jan" + "Kowalski" obok siebie (model podzielił) → jeden fragment."""
        spans.sort(key=lambda s: (s.item, s.start))
        out: List[Span] = []
        for s in spans:
            if out and s.entity_type == "PERSON" and out[-1].entity_type == "PERSON" and out[-1].item == s.item:
                gap = texts[s.item][out[-1].end : s.start]
                if gap != "" and gap.isspace() and "\n" not in gap:
                    prev = out[-1]
                    out[-1] = Span(
                        s.item, prev.start, s.end, "PERSON", texts[s.item][prev.start : s.end],
                        prev.source, max(prev.score, s.score),
                    )
                    continue
            out.append(s)
        return out

    def _classify(self, text: str, s: Span) -> bool:
        """Ustala status/powód fragmentu. Zwraca False, jeśli fragment należy odrzucić."""
        et, src, frag = s.entity_type, s.source, s.text
        if src.startswith("deny:"):
            s.status, s.reason = "sure", "fraza z Twojej listy „zawsze anonimizuj”"
            return True
        if self._allowed(frag):
            return False
        if src.startswith("custom:"):
            s.status = "sure" if s.score >= 0.8 else "review"
            s.reason = f"własny rozpoznawacz „{src[7:]}”"
            return True
        words = frag.split()
        caps = [w for w in words if w[:1].isupper()]
        before = text[max(0, s.start - 80) : s.start]
        if et in NAME_ENTITIES:
            if not caps:
                return False
            if PUBLIC_BODY.match(frag):
                return False
            if src == SPACY_NAME and all(ROLE_WORDS.match(w.strip(".,;:")) for w in words):
                return False
            if src == SPACY_NAME and all(w.isupper() for w in words) and len(frag) <= 6:
                s.status, s.reason = "hint", "skrót wielkimi literami – model uznał za nazwę własną, raczej to oznaczenie (np. PZT, WSA)"
                return True
            if src == "PlPersonTitleRecognizer":
                s.status, s.reason = "sure", "imię i nazwisko (po tytule lub zwrocie „pan/pani”)"
                return True
            if src == "PlCompanyRecognizer":
                s.status, s.reason = "sure", "nazwa spółki (z formą prawną)"
                return True
            if et == "PERSON":
                if len(caps) >= 2:
                    s.status, s.reason = "sure", "imię i nazwisko wg modelu językowego"
                elif is_first_name(words[0]) or TITLE_BEFORE.search(before):
                    s.status, s.reason = "sure", "imię (lub nazwisko po zwrocie „pan/pani”)"
                else:
                    s.status, s.reason = "review", "pojedyncze słowo uznane przez model za osobę – imię, nazwisko czy coś innego?"
                return True
            if et == "ORGANIZATION":
                s.status, s.reason = "review", "organizacja wg modelu językowego – strona postępowania czy instytucja?"
                return True
            if LOC_INSTITUTION_BEFORE.search(text[max(0, s.start - 70) : s.start]):
                return False  # część nazwy organu / sądu
            s.status, s.reason = "review", "miejsce wg modelu językowego"
            return True
        if et == "ADDRESS":
            if src == "PlStreetOnlyRecognizer":
                s.status, s.reason = "review", "nazwa ulicy bez numeru – anonimizować?"
            else:
                s.status, s.reason = "sure", "adres (ulica z numerem lub kod pocztowy z miejscowością)"
            return True
        if et == "PLOT_NUMBER":
            s.status, s.reason = "sure", "numer działki (kontekst „działka nr”)"
            return True
        if et == "CASE_SIGNATURE":
            if CITED_CASE_BEFORE.search(before):
                s.status, s.reason = "hint", "sygnatura cytowanego orzeczenia – domyślnie zostaje"
            else:
                s.status, s.reason = "review", "numer sprawy / decyzji – identyfikuje postępowanie"
            return True
        if et == "PHONE_NUMBER":
            s.status = "sure" if s.score >= 0.6 else "review"
            s.reason = "numer telefonu" if s.status == "sure" else "ciąg cyfr – telefon czy inny numer?"
            return True
        if et in CHECKSUM_ENTITIES:
            s.status, s.reason = "sure", "poprawny format (suma kontrolna)"
            return True
        if et == "DATE_TIME":
            # model NER oznacza też same roczniki ("Dz.U.2025.1619", "w 2024") – bierzemy tylko pełne daty
            if src == SPACY_NAME and not DATE_LIKE.search(frag):
                return False
            s.status, s.reason = "sure", "data"
            return True
        if et == "URL":
            s.status, s.reason = "sure", "adres www"
            return True
        s.status = "sure" if s.score >= 0.7 else "review"
        s.reason = f"rozpoznawacz {src}"
        return True

    # ------------------------------------------------------------ propagate
    def propagate(self, texts: List[str], spans: List[Span]) -> List[Span]:
        extra = self._propagate(texts, spans)
        return extra

    def _propagate(self, texts: List[str], spans: List[Span]) -> List[Span]:
        """Drugi przebieg: wartości już wykryte (i ich odmiany) szukamy w całym dokumencie.

        Dzięki temu np. numer działki "123/4" w komórce tabeli (bez słowa "działka")
        lub nazwisko pominięte przez model w innym akapicie dostaną ten sam placeholder.
        """
        patterns: List[Tuple[re.Pattern, str, str, str, str]] = []  # regex, entity, key, status, reason
        seen = set()
        by_key: Dict[str, List[Span]] = defaultdict(list)
        for s in spans:
            if s.status == "hint":
                continue
            by_key[s.key].append(s)
        surname_owner: Dict[str, set] = defaultdict(set)
        for key, group in by_key.items():
            et = group[0].entity_type
            if et == "PERSON":
                st = stems(group[0].text)
                if len(st) >= 2:
                    surname_owner[st[-1]].add(key)
        for key, group in by_key.items():
            et = group[0].entity_type
            if et not in PROPAGATE_ENTITIES:
                continue
            status = "sure" if all(g.status == "sure" for g in group) else "review"
            for g in group:
                if (key, g.text) in seen:
                    continue
                seen.add((key, g.text))
                if et == "PERSON":
                    patterns.extend(self._person_patterns(g.text, key, status, surname_owner))
                elif et == "ORGANIZATION":
                    patterns.extend(self._org_patterns(g.text, key, status))
                elif et == "PLOT_NUMBER":
                    if "/" not in g.text and len(re.sub(r"\D", "", g.text)) < 3:
                        continue
                    patterns.append((_exact(g.text), et, key, "sure", "ten sam numer działki co wcześniej"))
                elif et in NAME_ENTITIES or et == "ADDRESS":
                    if len(g.text) < 4:
                        continue
                    patterns.append((_exact(g.text, True), et, key, status, "ta sama nazwa co wcześniej"))
                else:
                    if len(g.text) < 5:
                        continue
                    patterns.append((_exact(g.text), et, key, "sure", "ta sama wartość co wcześniej"))
        if not patterns:
            return spans
        extra: List[Span] = []
        dropped: set = set()
        for i, text in enumerate(texts):
            existing = [s for s in spans if s.item == i]
            for rx, et, key, status, reason in patterns:
                for m in rx.finditer(text):
                    cand = Span(i, m.start(), m.end(), et, m.group(0), "known", 0.95, status, reason, key)
                    if et == "PERSON" and key.startswith("AMBIG:"):
                        owners = set(key[6:].split("|"))
                        pick = _pick_by_gender(owners, {}, text, m.start())
                        if pick:
                            cand.key, cand.status, cand.reason = pick, "review", "nazwisko kilku osób – dopasowano po zwrocie pan/pani"
                        else:
                            cand.key = "PERSON:" + name_stem(m.group(0))
                            cand.status, cand.reason = "review", "nazwisko pasuje do kilku osób – sprawdź, o kogo chodzi"
                    if self._allowed(cand.text) or PUBLIC_BODY.match(cand.text):
                        continue
                    if et == "LOCATION" and LOC_INSTITUTION_BEFORE.search(text[max(0, m.start() - 70) : m.start()]):
                        continue
                    if any(cand.overlaps(x) for x in extra if x.item == i):
                        continue
                    clash = [x for x in existing if cand.overlaps(x)]
                    if clash:
                        # niepewny strzał modelu NER (np. "Gumniska" jako miejscowość) ustępuje znanej wartości
                        weak = all(
                            x.source == SPACY_NAME and x.status != "sure" and cand.start <= x.start and cand.end >= x.end
                            for x in clash
                        )
                        if not weak:
                            continue
                        for x in clash:
                            existing.remove(x)
                            dropped.add(id(x))
                    extra.append(cand)
        return [s for s in spans if id(s) not in dropped] + extra

    @staticmethod
    def _person_patterns(text: str, key: str, status: str, surname_owner: Dict[str, set]):
        words = [w.strip(".,;:()\"'„”") for w in text.split()]
        words = [w for w in words if w]
        pieces = []
        for w in words:
            st = name_stem(w)
            if len(st) < 3 or not w[:1].isupper():
                pieces = []
                break
            # wzorzec na rdzeń z oryginalną wielkością liter: Habryk\w{0,5} → Habryki, Habryką, Habryce (c≠k – nie złapie)
            prefix = w[: len(st)] if w[: len(st)].lower() == st else None
            pieces.append((w, st, prefix))
        if not pieces:
            return []
        out = []
        if len(pieces) >= 2 and all(p[2] for p in pieces):
            full = r"\s+".join(rf"{re.escape(p[2])}[{LO}]{{0,5}}" for p in pieces)
            out.append((re.compile(rf"(?<![{UP}{LO}])(?:{full})(?![{LO}])"), "PERSON", key, status, "ta sama osoba (odmiana imienia i nazwiska)"))
            surname = pieces[-1]
            if surname[2] and len(surname[1]) >= 4:
                owners = surname_owner.get(surname[1], set())
                if len(owners) > 1:
                    out.append((re.compile(rf"(?<![{UP}{LO}]){re.escape(surname[2])}[{LO}]{{0,5}}(?![{LO}])"), "PERSON", "AMBIG:" + "|".join(sorted(owners)), "review", "nazwisko kilku osób"))
                else:
                    st = "sure" if status == "sure" else "review"
                    out.append((re.compile(rf"(?<![{UP}{LO}]){re.escape(surname[2])}[{LO}]{{0,5}}(?![{LO}])"), "PERSON", key, st, "nazwisko osoby rozpoznanej w dokumencie"))
        elif len(pieces) == 1 and pieces[0][2] and len(pieces[0][1]) >= 4:
            w, st, prefix = pieces[0]
            out.append((re.compile(rf"(?<![{UP}{LO}]){re.escape(prefix)}[{LO}]{{0,5}}(?![{LO}])"), "PERSON", key, status, "ta sama osoba (odmiana)"))
        return out

    @staticmethod
    def _org_patterns(text: str, key: str, status: str):
        out = [(_exact(text, True), "ORGANIZATION", key, status, "ta sama organizacja")]
        short = LEGAL_FORM_TAIL.sub("", text).strip(" „”\"'")
        if short and short != text:
            words = [w for w in short.split() if w[:1].isupper() and w.lower() not in GENERIC_ORG_WORDS]
            if words and len(short) >= 4:
                out.append((_exact(short, True), "ORGANIZATION", key, "review", "skrócona nazwa spółki (bez formy prawnej)"))
                if len(words) == 1 and len(words[0]) >= 5:
                    st = name_stem(words[0])
                    if len(st) >= 4 and words[0][: len(st)].lower() == st:
                        out.append((
                            re.compile(rf"(?<![{UP}{LO}]){re.escape(words[0][: len(st)])}[{LO}]{{0,4}}(?![{LO}])"),
                            "ORGANIZATION", key, "review", "odmiana skróconej nazwy spółki",
                        ))
        return out


def _exact(text: str, ignore_case: bool = False) -> re.Pattern:
    parts = [re.escape(p) for p in text.split()]
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)", flags)


def _contains(seq: Tuple[str, ...], sub: Tuple[str, ...]) -> bool:
    n = len(sub)
    if n == 0 or n > len(seq):
        return False
    return any(seq[i : i + n] == sub for i in range(len(seq) - n + 1))


def _resolve_overlaps(spans: List[Span]) -> List[Span]:
    """Przy nakładających się fragmentach zostaw dłuższy, a przy równych – wyższy score."""
    # przy równej długości: wzorzec (regex) przed modelem NER, potem wyższy score
    def rank(s: Span):
        return (s.end - s.start, 0 if s.source == SPACY_NAME else 1, s.score)

    ordered = sorted(spans, key=lambda s: (s.item, s.start, -(s.end - s.start), 0 if s.source != SPACY_NAME else 1, -s.score))
    out: List[Span] = []
    for s in ordered:
        if out and out[-1].item == s.item and s.start < out[-1].end:
            if rank(s) > rank(out[-1]):
                out[-1] = s
            continue
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# Cache silnika (budowa modelu spaCy jest kosztowna)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_cached: Optional[Tuple[str, Anonymizer]] = None


def get_anonymizer(settings: Settings) -> Anonymizer:
    global _cached
    sig = settings.engine_signature()
    with _lock:
        if _cached is not None and _cached[0] == sig:
            _cached[1].settings = settings
            _cached[1].set_allow_list(settings.allow_list)
            return _cached[1]
        log.info("Buduję silnik Presidio (model %s)…", settings.spacy_model)
        engine = Anonymizer(settings)
        _cached = (sig, engine)
        return engine
