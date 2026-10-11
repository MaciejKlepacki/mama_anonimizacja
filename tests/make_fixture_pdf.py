"""Fikcyjna decyzja „z konwersji PDF”: każda linia to osobny akapit, numery stron luzem, nazwiska rozbite między linie."""

from pathlib import Path

from docx import Document

LINES = """DECYZJA
Na podstawie art. 138 § 1 pkt 1 ustawy z dnia 14 czerwca 1960 r. – Kodeks
postępowania administracyjnego (t.j. Dz.U.2025.1619) – zwanej dalej kpa i art. 82
ust. 3 ustawy z dnia 7 lipca 1994 r. – Prawo budowlane – zwanej
dalej pb, po rozpatrzeniu odwołania: pani Anny Habryki i pana Mariusza
Habryki, działających przez pełnomocnika: radcę prawnego Tomasza Wierzbickiego;
od decyzji Prezydenta Miasta Krakowa nr 285/6740.1/2025 z 31 marca 2025 r.,
znak: AU-01-4.6740.1.263.2024.GPA, w przedmiocie zatwierdzenia projektu
zagospodarowania terenu oraz projektu architektoniczno-budowlanego i udzielenia
Inwestorowi: Gumniska sp. z o.o., w imieniu której działa pełnomocnik: pan Piotr
Zaręba; pozwolenia na budowę dla zamierzenia budowlanego pn.: budowa
budynku mieszkalnego wielorodzinnego z garażem podziemnym, WLZ od budynku do
złącza ZK, murami oporowymi przy ul. Lasówka w Krakowie, na
działkach nr: 12/3, 14, 15 obr. 18 Podgórze; zwanego dalej inwestycją
– utrzymuje się zaskarżoną decyzję w mocy.
Uzasadnienie
Po rozpatrzeniu wniosku spółki: Gumniska, w imieniu której działa pełnomocnik,
z 23 grudnia 2024 r., Prezydent Miasta Krakowa zatwierdził projekt.
2
Od ww. decyzji odwołali się: pani Anna Habryka i pan Mariusz Habryka,
działający przez pełnomocnika: radcę prawnego Tomasza Wierzbickiego – strony
postępowania prowadzonego przez organ I instancji.
Prezydent Miasta Krakowa przesłał odwołanie do Wojewody Małopolskiego.
Zgodnie z art. 35 ust. 1 pkt 1 lit. a pb organ sprawdza zgodność projektu. W opisie
projektu zagospodarowania terenu, dalej PZT (pkt 4 opisu PZT), wskazano wartość.
a. Granica z działką nr 98 – teren tej działki położony jest niżej. Odprowadza on
wodę w kierunku działek nr 98,122/1 i 48/24.
b. Granica z działką nr 48/24 – wzdłuż tej granicy zaprojektowano wodościek.
3
Zakaz lokalizacji miejsc parkingowych w Terenach: ZP.1- ZP.6, R/ZP.1, WS.1,
KDL.1, KDZT.1 i G.1.
W orzecznictwie ugruntował się pogląd (por. Wojewódzki Sąd Administracyjny, dalej
WSA w Krakowie, II SA/Kr 493/24, LEX nr 3728411). Wyrok Naczelnego Sądu
Administracyjnego z 15 lutego 2018 r., sygn. akt II OSK 1820/17.
Pani Anna Habryka i pan Mariusz Habryka są właścicielami działki nr 97/2
(dokument w aktach sprawy), zabudowanej budynkiem mieszkalnym jednorodzinnym
przy ulicy Golikówka. Przekrój B-B pomija granicę z działką sąsiednią nr 98.
Uchwała nr XII/191/19 Rady Miasta Krakowa z dnia 27 marca 2019 r. w sprawie
miejscowego planu zagospodarowania przestrzennego obszaru „Rejon ulicy Koszykarskiej”.
4
Pełnomocnik Habryków wniósł o uchylenie decyzji. Zaręba złożył oświadczenie.
Pani Habryka nie stawiła się na rozprawie, pan Habryka stawił się osobiście.
Mając powyższe na uwadze orzeczono jak w sentencji.""".split("\n")


def build(path: Path) -> Path:
    doc = Document()
    for ln in LINES:
        doc.add_paragraph(ln)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


if __name__ == "__main__":
    print(build(Path(__file__).parent / "fixtures" / "decyzja_pdf.docx"))
