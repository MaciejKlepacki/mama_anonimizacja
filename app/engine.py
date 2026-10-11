"""Silnik anonimizacji: Presidio Analyzer (spaCy PL + rozpoznawacze) i spójne placeholdery."""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from presidio_analyzer import AnalyzerEngine, PatternRecognizer, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NerModelConfiguration, SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import SpacyRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from .recognizers import (
    LANG,
    build_custom_recognizers,
    build_deny_list_recognizers,
    build_polish_recognizers,
)
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

_STEM_LEN = 5


NAME_ENTITIES = ("PERSON", "LOCATION", "ORGANIZATION")


def _stem_words(t: str) -> List[str]:
    words = [w.strip(".,;:()\"'") for w in re.split(r"[\s\-]+", t)]
    return [w if len(w) <= 2 else w[:_STEM_LEN] for w in words if w]


def normalize_key(entity_type: str, text: str, lemmatize=None) -> str:
    """Klucz spójności: ta sama osoba/obiekt w różnych formach → ten sam placeholder.

    Dla nazw własnych (osoby, miejscowości, organizacje) używamy lematów spaCy
    ("Jana Kowalskiego" → "jan kowalski"), a bez lematyzatora – przybliżonego
    rdzenia każdego wyrazu. Dla identyfikatorów usuwamy białe znaki i separatory.
    """
    t = unicodedata.normalize("NFKC", text).strip()
    if entity_type in NAME_ENTITIES:
        if lemmatize is not None:
            words = lemmatize(t)
        else:
            words = _stem_words(t.lower())
        return f"{entity_type}:{' '.join(words)}"
    t = t.lower()
    if entity_type in ("ADDRESS",):
        t = re.sub(r"\s+", " ", t)
        t = re.sub(r"\b(ul\.|ulic[aąyę]|al\.|ale[ij]\w*|pl\.|plac\w*|os\.|osiedl\w*)\s*", "", t)
        t = re.sub(r"\s*(m\.|lok\.|lokal|mieszk\w*)\s*", "/", t)
        if lemmatize is not None:  # "Długiej 5" / "Długa 5" → ten sam adres
            t = " ".join(lemmatize(t))
        return f"{entity_type}:{t}"
    compact = re.sub(r"[\s\-]", "", t)
    return f"{entity_type}:{compact}"


@dataclass
class PlaceholderMapper:
    """Przydziela spójne placeholdery ([OSOBA_1], [DZIAŁKA_2], ...)."""

    labels: Dict[str, str]
    counters: Dict[str, int] = field(default_factory=dict)
    by_key: Dict[str, str] = field(default_factory=dict)
    variants: Dict[str, List[str]] = field(default_factory=dict)
    entity_of: Dict[str, str] = field(default_factory=dict)
    hits: Dict[str, int] = field(default_factory=dict)
    lemmatize: Optional[object] = None

    def key(self, entity_type: str, text: str) -> str:
        return normalize_key(entity_type, text, self.lemmatize)

    def placeholder(self, entity_type: str, text: str) -> str:
        key = self.key(entity_type, text)
        ph = self.by_key.get(key)
        if ph is None and entity_type == "PERSON":
            ph = self._match_surname(key)
            if ph is not None:
                self.by_key[key] = ph
        if ph is None:
            label = self.labels.get(entity_type, entity_type)
            n = self.counters.get(label, 0) + 1
            self.counters[label] = n
            ph = f"[{label}_{n}]"
            self.by_key[key] = ph
            self.entity_of[ph] = entity_type
            self.variants[ph] = []
        if text not in self.variants[ph]:
            self.variants[ph].append(text)
        self.hits[ph] = self.hits.get(ph, 0) + 1
        return ph

    def _match_surname(self, key: str) -> Optional[str]:
        """Samo nazwisko ("Kowalski", "Nowak-Wiśniewska") → placeholder pełnej osoby, jeśli jednoznaczny.

        Dopasowanie: lematy nowej encji są końcówką lematów już znanej, dłuższej encji.
        """
        words = key.split(":", 1)[1].split()
        if not words or len(words[-1]) < 3:
            return None
        candidates = set()
        for k, ph in self.by_key.items():
            if not k.startswith("PERSON:"):
                continue
            kw = k.split(":", 1)[1].split()
            if len(kw) > len(words) and kw[-len(words) :] == words:
                candidates.add(ph)
        return next(iter(candidates)) if len(candidates) == 1 else None

    def mapping(self) -> List[dict]:
        out = []
        for ph, variants in self.variants.items():
            out.append(
                {
                    "placeholder": ph,
                    "entity_type": self.entity_of[ph],
                    "variants": variants,
                    "count": self.hits.get(ph, 0),
                }
            )
        return out

    def stats(self) -> Dict[str, int]:
        stats: Dict[str, int] = {}
        for ph, n in self.hits.items():
            et = self.entity_of[ph]
            stats[et] = stats.get(et, 0) + n
        return stats


class Anonymizer:
    """Opakowanie Presidio skonfigurowane dla dokumentów polskich."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.analyzer = self._build_analyzer(settings)
        self.anonymizer = AnonymizerEngine()
        self.deny_only = settings.deny_only_entities()
        self.entities = settings.enabled_entities() + self.deny_only
        self.labels = {e: settings.label_for(e) for e in self.entities}
        self.nlp = self.analyzer.nlp_engine.nlp[LANG]
        self._allow_list = self._prepare_allow_list(settings.allow_list)

    @staticmethod
    def _prepare_allow_list(items: List[str]) -> List[str]:
        return [re.sub(r"\s+", " ", i.strip()).lower() for i in items if i and i.strip()]

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

    # --------------------------------------------------------------- analyze
    def analyze(self, text: str) -> List[RecognizerResult]:
        if not text or not text.strip() or not self.entities:
            return []
        results = self.analyzer.analyze(
            text=text,
            language=LANG,
            entities=self.entities,
            score_threshold=0.0,
        )
        kept = [r for r in results if r.score >= self.settings.threshold_for(r.entity_type)]
        kept = [r for r in kept if self._sane(text, r) and not self._allowed(text[r.start : r.end])]
        if self.deny_only:
            kept = [
                r
                for r in kept
                if r.entity_type not in self.deny_only
                or str((r.recognition_metadata or {}).get("recognizer_name", "")).startswith("deny:")
            ]
        return self._resolve_overlaps(kept)

    def _allowed(self, fragment: str) -> bool:
        frag = re.sub(r"\s+", " ", fragment.strip()).lower()
        for item in self._allow_list:
            if frag == item or (len(frag) >= 3 and frag in item):
                return True
        return False

    def lemmatize(self, text: str) -> List[str]:
        """Lematy nazwy własnej (małymi literami, bez interpunkcji) – do klucza spójności."""
        doc = self.nlp(text)
        out = []
        for tok in doc:
            lemma = (tok.lemma_ or tok.text).strip().lower()
            if not lemma or not re.search(r"\w", lemma):
                continue
            out.append(lemma)
        return out

    @staticmethod
    def _sane(text: str, r: RecognizerResult) -> bool:
        frag = text[r.start : r.end]
        if not frag.strip():
            return False
        # Model NER czasem oznacza same skróty typu "ul." jako geogName.
        if r.entity_type in ("LOCATION", "PERSON", "ORGANIZATION") and not re.search(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{2,}", frag):
            return False
        if r.entity_type == "PHONE_NUMBER":
            # tylko cyfry, spacje, myślniki, nawiasy, "+"; min. 9 cyfr – odrzuca np. numery decyzji "7840.1.2024"
            if not re.fullmatch(r"\+?[\d\s\-()]+", frag) or len(re.sub(r"\D", "", frag)) < 9:
                return False
        return True

    @staticmethod
    def _resolve_overlaps(results: List[RecognizerResult]) -> List[RecognizerResult]:
        """Przy nakładających się encjach zostaw dłuższą, a przy równych – wyższy score."""
        ordered = sorted(results, key=lambda r: (r.start, -(r.end - r.start), -r.score))
        out: List[RecognizerResult] = []
        for r in ordered:
            if out and r.start < out[-1].end:
                prev = out[-1]
                if (r.end - r.start, r.score) > (prev.end - prev.start, prev.score):
                    out[-1] = r
                continue
            out.append(r)
        return out

    # ------------------------------------------------------------- anonymize
    def anonymize_text(
        self,
        text: str,
        mapper: PlaceholderMapper,
        results: Optional[List[RecognizerResult]] = None,
    ) -> Tuple[str, List[RecognizerResult]]:
        if results is None:
            results = self.analyze(text)
        if not results:
            return text, []
        # Numeracja wg kolejności pierwszego wystąpienia
        for r in sorted(results, key=lambda r: r.start):
            mapper.placeholder(r.entity_type, text[r.start : r.end])
        operators = {
            et: OperatorConfig("custom", {"lambda": _make_lambda(mapper, et)}) for et in {r.entity_type for r in results}
        }
        out = self.anonymizer.anonymize(text=text, analyzer_results=results, operators=operators)
        return out.text, results

    def known_value_recognizers(self, values: Dict[str, List[str]]) -> List[PatternRecognizer]:
        """Rozpoznawacze deny-list dla wartości już wykrytych w dokumencie.

        Dzięki temu np. numer działki "123/4" w komórce tabeli (bez słowa "działka")
        lub nazwisko pominięte przez model NER w innym akapicie dostaną ten sam placeholder.
        """
        recs = []
        for entity, vals in values.items():
            vals = sorted({v for v in vals if len(v.strip()) >= 3}, key=len, reverse=True)
            if not vals:
                continue
            recs.append(
                PatternRecognizer(
                    supported_entity=entity,
                    name=f"known:{entity}",
                    supported_language=LANG,
                    deny_list=vals,
                    deny_list_score=0.95,
                    global_regex_flags=re.IGNORECASE | re.MULTILINE | re.DOTALL if entity in NAME_ENTITIES else re.MULTILINE | re.DOTALL,
                )
            )
        return recs

    def analyze_with_known(self, text: str, base: List[RecognizerResult], known: List[PatternRecognizer]) -> List[RecognizerResult]:
        if not known or not text.strip():
            return base
        extra: List[RecognizerResult] = []
        for rec in known:
            extra.extend(rec.analyze(text, rec.supported_entities, None))
        extra = [r for r in extra if not self._allowed(text[r.start : r.end])]
        return self._resolve_overlaps(list(base) + extra)

    def new_mapper(self) -> PlaceholderMapper:
        return PlaceholderMapper(labels=dict(self.labels), lemmatize=self.lemmatize)


def _make_lambda(mapper: PlaceholderMapper, entity_type: str):
    def _f(x: str) -> str:
        return mapper.by_key.get(mapper.key(entity_type, x)) or mapper.placeholder(entity_type, x)

    return _f


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
            _cached[1]._allow_list = Anonymizer._prepare_allow_list(settings.allow_list)
            return _cached[1]
        log.info("Buduję silnik Presidio (model %s)…", settings.spacy_model)
        engine = Anonymizer(settings)
        _cached = (sig, engine)
        return engine
