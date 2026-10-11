"""Nazwy własne po polsku: rdzeń odmiany (do spójnych placeholderów) i lista popularnych imion."""

from __future__ import annotations

import re
from typing import Iterable, List

# Litery polskie
UP = "A-ZĄĆĘŁŃÓŚŹŻ"
LO = "a-ząćęłńóśźż"

_STRIP = ".,;:()\"'„”«»"

# Nazwiska / przymiotniki rodzajowe: Kowalski, Kowalskiego, Kowalska, Kowalskiej → kowalski / kowalska
_GENDERED = re.compile(r"^(.{2,}?)(sk|ck|dzk)(i|iego|iemu|im|a|iej|ą|ę)$")

# Miejscownik / wołacz z alternacją: Habryce → habryk, Piotrze → piotr, Michale → michał, Kocie → kot
_LOC_ALT = [
    ("cie", "t"), ("dzie", "d"), ("rze", "r"), ("dze", "g"), ("ce", "k"), ("le", "ł"),
    ("sze", "ch"), ("nie", "n"), ("sie", "s"), ("zie", "z"), ("ście", "st"),
]

# Zwykłe końcówki fleksyjne (od najdłuższych)
_SUFFIXES = [
    "iego", "iemu", "owie", "ami", "ach", "ego", "emu", "owi", "iem", "ych", "ich", "iej",
    "ym", "im", "om", "ów", "em", "ie", "ia", "ię", "ią", "ii", "iu", "io",
    "ą", "ę", "a", "e", "i", "o", "u", "y",
]
_FLEETING_E = re.compile(rf"^(.{{2,}}[^aeiouyąęó])e([kcłr])$")


def name_stem(word: str) -> str:
    """Przybliżony rdzeń wyrazu nazwy własnej, wspólny dla jego form fleksyjnych.

    Anna/Anny/Annie/Anną → ann; Habryka/Habryki/Habryce → habryk; Kowalskiego/Kowalski → kowalski;
    Kowalskiej/Kowalska → kowalska; Marek/Marka → mark; Paweł/Pawła → pawł; Piotrze/Piotr → piotr.
    """
    w = word.strip(_STRIP).lower()
    if not w:
        return ""
    if "-" in w:
        return "-".join(name_stem(p) for p in w.split("-") if p)
    m = _GENDERED.match(w)
    if m:
        base, mid, end = m.groups()
        return base + mid + ("a" if end in ("a", "iej", "ą", "ę") else "i")
    for suf, repl in _LOC_ALT:
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            w = w[: -len(suf)] + repl
            break
    else:
        for suf in _SUFFIXES:
            if w.endswith(suf) and len(w) - len(suf) >= 2:
                w = w[: -len(suf)]
                break
    m = _FLEETING_E.match(w)
    if m:
        w = m.group(1) + m.group(2)
    if w.endswith("l"):
        w = w[:-1] + "ł"
    return w


def stems(text: str) -> List[str]:
    return [s for s in (name_stem(w) for w in re.split(r"\s+", text.strip())) if s]


# ---------------------------------------------------------------------------
# Popularne imiona (mianownik). Używane do oceny pewności: pojedyncze słowo
# rozpoznane jako osoba jest pewne, jeśli to imię; "Jan Kowalski" jest pewne zawsze.
# ---------------------------------------------------------------------------
MALE_NAMES = """
Adam Adrian Albert Aleksander Alojzy Andrzej Antoni Arkadiusz Artur Bartłomiej Bartosz Benedykt Bernard
Błażej Bogdan Bogusław Bolesław Borys Bronisław Cezary Czesław Damian Daniel Dariusz Dawid Dominik
Edmund Edward Emil Ernest Eugeniusz Fabian Feliks Filip Franciszek Fryderyk Gabriel Gerard Grzegorz
Gustaw Henryk Hieronim Hubert Ignacy Igor Ireneusz Iwo Jacek Jakub Jan Janusz Jarosław Jerzy Jędrzej
Joachim Józef Julian Juliusz Kacper Kajetan Kamil Karol Kazimierz Konrad Konstanty Kornel Krystian
Krzysztof Ksawery Leon Leonard Leszek Lech Lucjan Ludwik Łukasz Maciej Maksymilian Marcel Marcin Marek
Marian Mariusz Mateusz Maurycy Michał Mieczysław Mikołaj Miłosz Mirosław Natan Nikodem Norbert Olaf
Olgierd Oskar Patryk Paweł Piotr Przemysław Radosław Rafał Robert Roman Romuald Ryszard Sebastian
Sergiusz Seweryn Sławomir Stanisław Stefan Sylwester Szczepan Szymon Tadeusz Teodor Tobiasz Tomasz
Tymon Tymoteusz Wacław Waldemar Walenty Wiesław Wiktor Wincenty Witold Władysław Włodzimierz Wojciech
Zbigniew Zdzisław Zenon Zygmunt Aleks Alan Eryk Kuba Nikodem Ryszard Tymoteusz Wawrzyniec Ludomir
"""
FEMALE_NAMES = """
Agata Agnieszka Aleksandra Alicja Alina Amelia Aneta Angelika Anna Antonina Apolonia Barbara Beata
Bernadeta Blanka Bogumiła Bogusława Bożena Bronisława Celina Cecylia Czesława Dagmara Danuta Daria
Dominika Dorota Edyta Eleonora Elżbieta Emilia Ewa Ewelina Felicja Franciszka Gabriela Genowefa Grażyna
Halina Hanna Helena Honorata Ilona Irena Iwona Izabela Jadwiga Janina Joanna Jolanta Józefa Judyta Julia
Julianna Justyna Kamila Karina Karolina Katarzyna Kazimiera Kinga Klara Klaudia Kornelia Krystyna Laura
Lena Leokadia Lidia Liliana Lucyna Ludmiła Łucja Magdalena Maja Malwina Małgorzata Maria Marianna
Marcelina Marlena Marta Martyna Marzena Matylda Melania Michalina Milena Mirosława Monika Natalia Nina
Oliwia Olga Patrycja Paulina Pelagia Regina Renata Roksana Romana Róża Sabina Sandra Stanisława Stefania
Sylwia Teresa Urszula Wanda Weronika Wiesława Wiktoria Wioletta Władysława Zofia Zuzanna Aniela Elwira
Eugenia Ewa Gertruda Jagoda Kalina Klementyna Leonarda Lilia Ludwika Nadia Nikola Otylia Zenobia
"""


def _stem_set(names: Iterable[str]) -> set:
    out = set()
    for n in names:
        out.add(name_stem(n))
    return out


MALE_STEMS = _stem_set(MALE_NAMES.split())
FEMALE_STEMS = _stem_set(FEMALE_NAMES.split())
FIRST_NAME_STEMS = MALE_STEMS | FEMALE_STEMS


def name_gender(word: str):
    """'m' / 'f' dla znanego imienia, inaczej None."""
    st = name_stem(word)
    if st in MALE_STEMS and st not in FEMALE_STEMS:
        return "m"
    if st in FEMALE_STEMS and st not in MALE_STEMS:
        return "f"
    return None


_GENDER_CTX = re.compile(r"(?:\b(?P<f>pani|panią|pannie|panny|panią|skarżąca|uczestniczka|wnioskodawczyni|powódka|pozwana|właścicielka)|"
                         r"\b(?P<m>pan|pana|panu|panem|panie|skarżący|uczestnik|wnioskodawca|powód|pozwany|właściciel))\s*$", re.IGNORECASE)


def gender_hint(text: str, start: int):
    """Płeć wynikająca ze zwrotu przed nazwiskiem ("pani Habryka" → 'f')."""
    m = _GENDER_CTX.search(text[max(0, start - 30):start])
    if not m:
        return None
    return "f" if m.group("f") else "m"


def is_first_name(word: str) -> bool:
    return name_stem(word) in FIRST_NAME_STEMS


def first_name_regex_alternatives() -> str:
    """Alternatywa regex dopasowująca odmienione imiona (Jan, Jana, Janowi…) – do rozpoznawacza osób."""
    stems_ = sorted(FIRST_NAME_STEMS, key=len, reverse=True)
    alts = []
    for s in stems_:
        if len(s) < 3:
            continue
        # rdzeń ma małe litery; w tekście imię zaczyna się wielką literą
        alts.append(s[0].upper() + re.escape(s[1:]))
    return "(?:" + "|".join(alts) + rf")[{LO}]{{0,4}}"
