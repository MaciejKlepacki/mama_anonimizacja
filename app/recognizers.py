"""Polskie rozpoznawacze dla Presidio: działki, adresy, KW, NIP, REGON, KRS, dowód, daty, sygnatury."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

from presidio_analyzer import EntityRecognizer, Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts

LANG = "pl"

# Litery polskie (do wzorców)
UP = "A-ZĄĆĘŁŃÓŚŹŻ"
LO = "a-ząćęłńóśźż"


class RegexGroupRecognizer(EntityRecognizer):
    """Rozpoznawacz regex, który oznacza tylko wybraną grupę dopasowania.

    Standardowy PatternRecognizer oznacza cały match; tutaj np. w zwrocie
    "działka nr 123/4" chcemy oznaczyć wyłącznie "123/4".
    """

    def __init__(
        self,
        supported_entity: str,
        name: str,
        patterns: List[str],
        score: float,
        group: str = "val",
        split_pattern: Optional[str] = None,
        flags: int = re.IGNORECASE | re.UNICODE,
        context: Optional[List[str]] = None,
        validator=None,
    ):
        super().__init__(
            supported_entities=[supported_entity],
            name=name,
            supported_language=LANG,
            context=context,
        )
        self.compiled = [re.compile(p, flags) for p in patterns]
        self.score = score
        self.group = group
        self.split_re = re.compile(split_pattern) if split_pattern else None
        self.validator = validator

    def load(self) -> None:  # pragma: no cover - nic do ładowania
        pass

    def analyze(self, text: str, entities: List[str], nlp_artifacts: NlpArtifacts = None) -> List[RecognizerResult]:
        results: List[RecognizerResult] = []
        entity = self.supported_entities[0]
        if entities and entity not in entities:
            return results
        for rx in self.compiled:
            for m in rx.finditer(text):
                try:
                    g_start, g_end = m.start(self.group), m.end(self.group)
                except IndexError:
                    g_start, g_end = m.start(), m.end()
                if g_start < 0:
                    continue
                spans = [(g_start, g_end)]
                if self.split_re is not None:
                    spans = [
                        (g_start + sm.start(), g_start + sm.end())
                        for sm in self.split_re.finditer(text[g_start:g_end])
                    ]
                for s, e in spans:
                    if e <= s:
                        continue
                    if self.validator is not None and not self.validator(text[s:e]):
                        continue
                    results.append(
                        RecognizerResult(
                            entity_type=entity,
                            start=s,
                            end=e,
                            score=self.score,
                            analysis_explanation=self.build_explanation(self.score, rx.pattern),
                        )
                    )
        return EntityRecognizer.remove_duplicates(results)

    def build_explanation(self, score: float, pattern: str):
        from presidio_analyzer import AnalysisExplanation

        return AnalysisExplanation(
            recognizer=self.name, original_score=score, pattern_name=self.name, pattern=pattern
        )


# --------------------------------------------------------------------------
# Walidatory sum kontrolnych
# --------------------------------------------------------------------------
def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def valid_nip(s: str) -> bool:
    d = _digits(s)
    if len(d) != 10 or d == "0" * 10:
        return False
    w = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    return sum(int(d[i]) * w[i] for i in range(9)) % 11 == int(d[9])


def valid_regon(s: str) -> bool:
    d = _digits(s)
    if len(d) == 9:
        w = [8, 9, 2, 3, 4, 5, 6, 7]
        c = sum(int(d[i]) * w[i] for i in range(8)) % 11 % 10
        return c == int(d[8])
    if len(d) == 14:
        if not valid_regon(d[:9]):
            return False
        w = [2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8]
        c = sum(int(d[i]) * w[i] for i in range(13)) % 11 % 10
        return c == int(d[13])
    return False


def valid_pesel(s: str) -> bool:
    d = _digits(s)
    if len(d) != 11:
        return False
    w = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]
    c = (10 - sum(int(d[i]) * w[i] for i in range(10)) % 10) % 10
    return c == int(d[10])


def valid_id_card(s: str) -> bool:
    s = re.sub(r"\s", "", s).upper()
    if not re.fullmatch(r"[A-Z]{3}\d{6}", s):
        return False
    vals = [ord(ch) - 55 if ch.isalpha() else int(ch) for ch in s]
    w = [7, 3, 1, 7, 3, 1, 7, 3]
    positions = [0, 1, 2, 4, 5, 6, 7, 8]  # pozycja 3 to cyfra kontrolna
    return sum(vals[pos] * w[i] for i, pos in enumerate(positions)) % 10 == vals[3]


# --------------------------------------------------------------------------
# Wzorce
# --------------------------------------------------------------------------
PLOT_NUMBER = r"\d{1,5}(?:/\d{1,5})?"
PLOT_LIST = rf"{PLOT_NUMBER}(?:\s*(?:,|;|i|oraz|a także|-|–)\s*{PLOT_NUMBER})*"
PLOT_CTX = (
    r"(?:działk[aiąęo]\w*|dz\.|nr\s+ewid\w*\.?|nr\s+geod\w*\.?|ewidencyjn\w+)"
    r"(?:\s+(?:gruntow\w+|ewidencyjn\w+|geodezyjn\w+|rolne\w*|budowlan\w+|lasow\w+|nr\.?|numer\w*|o\s+numerze|oznaczon\w+|jako))*"
)
PLOT_PATTERNS = [
    rf"\b{PLOT_CTX}\s*(?:nr\.?|numer\w*)?\s*:?\s*(?P<val>{PLOT_LIST})(?![\d/])",
]

STREET_PREFIX = r"(?:ul\.|ulic[aąyę]|al\.|ale[ij]\w*|pl\.|plac\w*|os\.|osiedl\w*|rondo|skwer\w*|bulwar\w*)"
STREET_WORD = rf"(?:[{UP}0-9][^\s,;:()]*|(?:gen|płk|ppłk|mjr|kpt|por|ks|św|dr|prof|im|bp|abp|marsz|hm|inż|mgr|adm|kard)\.)"
HOUSE_NO = r"\d{1,4}(?:[a-zA-Z](?![\w.]))?(?:\s*(?:/|m\.|lok\.|lokal|mieszk\w*)\s*\d{1,4}(?:[a-zA-Z](?![\w.]))?)?"
ADDRESS_PATTERNS = [
    # ul. Jana Pawła II 5 m. 3 / al. Jerozolimskie 100/12
    rf"(?<![\w.@/-])(?P<val>{STREET_PREFIX}\s+(?:{STREET_WORD}\s+){{1,5}}?{HOUSE_NO})(?![\d/])",
    # 00-950 Warszawa, 05-123 Nowa Wieś Wielka
    rf"\b(?P<val>\d{{2}}-\d{{3}}\s+[{UP}][{LO}{UP}\-]+(?:\s+[{UP}][{LO}{UP}\-]+){{0,2}})\b",
]

KW_PATTERNS = [r"\b(?P<val>[A-Z]{2}\d[A-Z]\s?/\s?\d{8}\s?/\s?\d)\b"]
NIP_PATTERNS = [r"(?<!\d)(?P<val>\d{3}[- ]?\d{3}[- ]?\d{2}[- ]?\d{2}|\d{3}-\d{2}-\d{2}-\d{3})(?!\d)"]
REGON_PATTERNS = [r"(?<!\d)(?P<val>\d{14}|\d{9})(?!\d)"]
KRS_PATTERNS = [r"\bKRS\s*(?:nr|numer)?\s*:?\s*(?P<val>\d{10})\b"]
ID_CARD_PATTERNS = [r"\b(?P<val>[A-Z]{3}\s?\d{6})\b"]
PESEL_PATTERNS = [r"(?<!\d)(?P<val>\d{11})(?!\d)"]

MONTHS = (
    "stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|września|października|listopada|grudnia"
)
DATE_PATTERNS = [
    rf"\b(?P<val>\d{{1,2}}\s+(?:{MONTHS})\s+\d{{4}})(?:\s*r\.)?",
    r"\b(?P<val>\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2}))(?:\s*r\.)?\b",
    r"\b(?P<val>\d{4}-\d{2}-\d{2})\b",
]

CASE_SIGNATURE_PATTERNS = [
    r"\b(?P<val>(?:I{1,3}|IV|V|VI{0,3})\s+(?:SA|SAB|OSK|FSK|GSK|OZ|FZ|GZ|OPS|FPS|GPS|OW|FW|GW|ONP|FNP|GNP|OPP|FPP|GPP)(?:/[A-Z][a-z]{1,2})?\s+\d{1,5}/\d{2})\b",
]

URL_PATTERNS = [r"\b(?P<val>(?:https?://|www\.)[^\s<>\"']+)"]


def build_polish_recognizers() -> List[EntityRecognizer]:
    """Zwraca listę rozpoznawaczy dla języka polskiego (bez modelu NER)."""
    from presidio_analyzer.predefined_recognizers import (
        EmailRecognizer,
        IbanRecognizer,
        PhoneRecognizer,
    )

    recs: List[EntityRecognizer] = [
        RegexGroupRecognizer(
            "PLOT_NUMBER",
            "PlPlotNumberRecognizer",
            PLOT_PATTERNS,
            score=0.85,
            split_pattern=PLOT_NUMBER,
        ),
        RegexGroupRecognizer("ADDRESS", "PlAddressRecognizer", ADDRESS_PATTERNS, score=0.75),
        RegexGroupRecognizer("PL_KW", "PlKwRecognizer", KW_PATTERNS, score=0.9, flags=re.UNICODE),
        RegexGroupRecognizer(
            "PL_NIP",
            "PlNipRecognizer",
            NIP_PATTERNS,
            score=0.6,
            validator=valid_nip,
            context=["nip", "podatnik", "podatkow"],
        ),
        RegexGroupRecognizer(
            "PL_REGON",
            "PlRegonRecognizer",
            REGON_PATTERNS,
            score=0.2,
            validator=valid_regon,
            context=["regon"],
        ),
        RegexGroupRecognizer("PL_KRS", "PlKrsRecognizer", KRS_PATTERNS, score=0.85),
        RegexGroupRecognizer(
            "PL_ID_CARD",
            "PlIdCardRecognizer",
            ID_CARD_PATTERNS,
            score=0.6,
            flags=re.UNICODE,
            validator=valid_id_card,
            context=["dowód", "dowodu", "dowodem", "seria", "serii", "numer", "legitymując"],
        ),
        RegexGroupRecognizer(
            "PL_PESEL",
            "PlPeselRecognizer",
            PESEL_PATTERNS,
            score=0.7,
            validator=valid_pesel,
            context=["pesel"],
        ),
        RegexGroupRecognizer("DATE_TIME", "PlDateRecognizer", DATE_PATTERNS, score=0.6),
        RegexGroupRecognizer(
            "CASE_SIGNATURE", "PlCaseSignatureRecognizer", CASE_SIGNATURE_PATTERNS, score=0.85, flags=re.UNICODE
        ),
        RegexGroupRecognizer("URL", "PlUrlRecognizer", URL_PATTERNS, score=0.6),
        EmailRecognizer(supported_language=LANG, context=["e-mail", "email", "mail", "poczta"]),
        PhoneRecognizer(
            supported_language=LANG,
            supported_regions=("PL",),
            context=["tel", "telefon", "nr", "kom", "fax", "faks"],
        ),
        IbanRecognizer(supported_language=LANG, context=["iban", "konto", "rachunek", "rachunku"]),
    ]
    return recs


def build_custom_recognizers(custom: Iterable) -> List[EntityRecognizer]:
    """Rozpoznawacze z ustawień użytkownika (PatternRecognizer Presidio)."""
    recs: List[EntityRecognizer] = []
    for c in custom:
        if not c.enabled or (not c.patterns and not c.deny_list):
            continue
        patterns = [Pattern(name=f"{c.name}_{i}", regex=p, score=c.score) for i, p in enumerate(c.patterns)]
        recs.append(
            PatternRecognizer(
                supported_entity=c.entity,
                name=f"custom:{c.name}",
                supported_language=LANG,
                patterns=patterns or None,
                deny_list=c.deny_list or None,
                context=c.context or None,
            )
        )
    return recs


def build_deny_list_recognizers(deny_list: dict) -> List[EntityRecognizer]:
    recs: List[EntityRecognizer] = []
    for entity, values in (deny_list or {}).items():
        values = [v for v in values if v and v.strip()]
        if not values:
            continue
        recs.append(
            PatternRecognizer(
                supported_entity=entity,
                name=f"deny:{entity}",
                supported_language=LANG,
                deny_list=values,
                deny_list_score=1.0,
            )
        )
    return recs
