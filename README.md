# mama_anonimizacja

Lokalna aplikacja do anonimizacji dokumentów sądowych: **Word (.docx) / PDF → Markdown** z użyciem
[Microsoft Presidio](https://microsoft.github.io/presidio/) i polskiego modelu spaCy (`pl_core_news_lg`).
Wszystko działa na `localhost`; pliki nie są nigdzie wysyłane ani zapisywane na dysku.

## Co robi

1. Wrzucasz plik `.docx` lub `.pdf` w przeglądarce (http://127.0.0.1:8765) **albo wklejasz tekst** („…albo wklej
   tekst zamiast pliku”) – tekst z PDF-a lub Worda przechodzi przez to samo sklejanie połamanych linii.
   PDF jest czytany lokalnie (PyMuPDF) z warstwy tekstowej i dalej traktowany dokładnie jak wklejony tekst.
   **Skany (PDF bez warstwy tekstowej) nie są obsługiwane** – program pokaże komunikat; zrób najpierw OCR
   w innym programie albo wklej tekst. Strony bez tekstu w PDF-ie mieszanym są pomijane z ostrzeżeniem.
2. Pipeline wykrywa i podmienia dane wrażliwe na spójne placeholdery, domyślnie:
   - imiona i nazwiska → `[OSOBA_1]`, `[OSOBA_2]`, …
   - adresy (ulica + numer, kod pocztowy + miejscowość) → `[ADRES_n]`
   - numery działek ewidencyjnych („działka nr 123/4", „dz. 12, 13/2") → `[DZIAŁKA_n]`
   - numery ksiąg wieczystych, PESEL, NIP, REGON, KRS, dowód osobisty, telefon, e-mail, IBAN
   - organizacje (spółki z formą prawną, np. „Gumniska sp. z o.o.”, także skrócone „Gumniska”),
     numery spraw/decyzji („znak: AU-01-…”, „decyzja nr 285/…”)
   - miejscowości, daty, adresy www (wszystkie rodzaje danych są domyślnie włączone; miejscowość w nazwie
     organu, np. „Prezydent Miasta Krakowa”, „WSA w Krakowie”, zostaje)
3. Każde trafienie ma **ocenę pewności** i w podglądzie jest zaznaczone kolorem:
   - **zielone** – pewne, anonimizowane bez pytania (imię + nazwisko, numery z sumą kontrolną, działki z kontekstem),
   - **pomarańczowe z „?”** – do sprawdzenia: anonimizowane domyślnie, ale człowiek klika **OK** albo **Nie**
     (np. organizacja wg modelu, ulica bez numeru, numer sprawy, samo nazwisko pasujące do kilku osób),
   - **szare** – zostaje w tekście (odrzucone kliknięciem „Nie” albo sugestia typu PZT, WSA, sygnatura
     cytowanego orzeczenia); nadal można kliknąć i zmienić decyzję.
   W okienku można też zmienić typ danych i **scalić** z inną osobą („scal z…”).
   **Marker** (przełącznik obok „Pokaż [OSOBA_1]”): każde zaznaczenie myszą od razu anonimizuje tekst jako
   `[ZANONIMIZOWANE_DANE_n]` (inny odcień zielonego, wszystkie wystąpienia); kliknięcie cofa lub zmienia typ.
   Bez markera zaznaczenie pokazuje pasek wyboru typu (osoba, organizacja, adres…).
4. Wynik to plik Markdown gotowy do wklejenia do czatu z LLM:
   - krótki wstęp objaśniający modelowi placeholdery + legenda,
   - zachowana struktura: nagłówki, listy, tabele, przypisy,
   - jeden placeholder = jedna osoba/obiekt w całym dokumencie, także mimo odmiany
     („Jan Kowalski", „Jana Kowalskiego", „Kowalski" → `[OSOBA_1]`),
   - bez zbędnych pustych linii i formatowania.
5. Osobno dostępna jest **mapa placeholderów** (JSON, tylko lokalnie) – do odczytania odpowiedzi modelu.
6. Podczas przetwarzania (duże dokumenty: kilkadziesiąt sekund) widać pasek postępu z etapem i procentem.

## Instalacja na Windows (ikona na pulpicie)

1. Pobierz repo (Code → Download ZIP) i rozpakuj, np. do `C:\Anonimizacja`.
2. Dwukliknij **`instaluj.bat`** i poczekaj do końca (kilka minut, jednorazowo). Instalator sam doinstaluje
   Pythona (przez `winget`), biblioteki i model językowy.
3. Na pulpicie pojawi się ikona **„Anonimizacja dokumentów”** – dwuklik otwiera osobne okno aplikacji
   (Edge/Chrome w trybie aplikacji). Zamknięcie okna wyłącza program.

### Aktualizacja (gdy program jest już zainstalowany)

Dwukliknij **`aktualizuj.bat`** w folderze programu. Skrypt pobiera najnowszą wersję z GitHuba, nadpisuje
pliki programu, zachowuje `.venv` (biblioteki i model, więc nic nie pobiera ponownie) oraz Twoje
`config\settings.json`, doinstalowuje ewentualne nowe biblioteki i odświeża skrót. Trwa kilkanaście sekund.

Jeśli masz jeszcze wersję bez `aktualizuj.bat`: pobierz ZIP (Code → Download ZIP), rozpakuj i skopiuj
całą zawartość do folderu programu, nadpisując pliki (`.venv` i `config\settings.json` zostaw), a potem
dwukliknij `instaluj.bat` – zrobi tylko brakujące kroki.

Dzienniki: `%LOCALAPPDATA%\mama_anonimizacja\aplikacja.log`. Odinstalowanie: usuń folder i skrót z pulpitu.

## Uruchomienie (ręczne / deweloperskie)

Wymagany Python 3.10+ (testowane na 3.13).

```bash
./run.sh          # Linux / macOS
run.bat           # Windows
```

Skrypt tworzy `.venv`, instaluje zależności, pobiera model `pl_core_news_lg` (~500 MB, jednorazowo)
i uruchamia serwer na http://127.0.0.1:8765. Ręcznie:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download pl_core_news_lg
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

### CLI (bez przeglądarki)

```bash
python -m app.cli wyrok.docx                  # → wyrok_anonimizacja.md obok pliku
python -m app.cli wyrok.docx -o out.md --mapa mapa.json
python -m app.cli *.docx                      # wiele plików
python -m app.cli decyzja.pdf                 # PDF z warstwą tekstową → decyzja_anonimizacja.md
python -m app.cli *.docx *.pdf --mapa mapa.json
```

Kod wyjścia: `2` – brak pliku lub nieobsługiwany format, `3` – PDF bez tekstu (skan), zaszyfrowany lub uszkodzony.

## Ustawienia

Strona **Ustawienia** (http://127.0.0.1:8765/settings) albo plik `config/settings.json`
(nadpisuje `config/default_settings.json`; nie jest commitowany):

- włączanie/wyłączanie encji, etykieta placeholdera, próg pewności,
- **allow-lista** – frazy nigdy nie anonimizowane (domyślnie nazwy sądów, województw),
- **deny-lista** – frazy zawsze anonimizowane, np. `PERSON: Jan Kowalski; Kowalskiego`,
- **własne rozpoznawacze** regex (Presidio `PatternRecognizer`), np. numery decyzji,
- opcje czytania Worda (przypisy, nagłówki/stopki, pogrubione linie jako nagłówki, sklejanie linii
  z konwersji PDF w akapity, usuwanie samotnych numerów stron),
- opcje wyniku (tytuł, wstęp dla modelu, legenda).

Na stronie ustawień jest pole „Test na tekście", które sprawdza bieżące (także niezapisane) ustawienia.

## Jak to działa

```
.docx ──python-docx──▶ bloki (nagłówki/akapity/listy/tabele/przypisy)
.pdf  ──PyMuPDF (warstwa tekstowa, bloki w kolejności czytania)──▶ tekst jak wklejony (linia = akapit)
      ──sklejanie linii z PDF, usuwanie numerów stron──▶ pełne akapity (nazwiska nie są rozcięte)
      ──Presidio Analyzer (spaCy NER pl + rozpoznawacze PL), porcjami po ~4000 znaków──▶ kandydaci
      ──ocena pewności (pewne / do sprawdzenia / sugestia), filtr organów publicznych, skrótów, ról──▶ fragmenty
      ──klucze spójności po rdzeniach odmiany (Anny Habryki = Anna Habryka; Kowalski ≠ Kowalska)──▶ te same osoby
      ──propagacja (2. przebieg): odmiany nazwisk, skrócone nazwy spółek, numery działek w tabelach
      ──decyzje recenzenta (OK / nie OK / typ / scal / ręczne zaznaczenie) ──▶ /api/render
      ──renderer──▶ Markdown + mapa placeholderów
```

Dlaczego nie sam lematyzator spaCy: dla rzadkich nazwisk daje różne lematy dla różnych form
(„Habryka” → „Habryk”, „Habryki” → „Habryka”), więc ta sama osoba dostawała kilka placeholderów.
Rdzeń z `app/names.py` obcina końcówki fleksyjne i normalizuje alternacje (Habryce → habryk).

Ważne pliki:

| Plik | Rola |
| --- | --- |
| `app/recognizers.py` | polskie rozpoznawacze (działki, adresy, ulice, osoby po tytule/imieniu, spółki, KW, NIP, REGON, KRS, dowód, daty, sygnatury i numery decyzji) |
| `app/names.py` | rdzenie odmiany nazw własnych, lista imion (płeć), zwroty pan/pani |
| `app/engine.py` | konfiguracja Presidio, allow-lista (odporna na odmianę), ocena pewności, klucze spójności, propagacja |
| `app/docx_reader.py` | czytanie Worda do bloków |
| `app/pdf_reader.py` | PDF → tekst (PyMuPDF, lokalnie); wykrywa skany bez warstwy tekstowej |
| `app/markdown.py` | rendering Markdown pod LLM |
| `app/pipeline.py` | analiza dokumentu (raz) + rendering z decyzjami recenzenta (wielokrotnie) |
| `app/main.py` | serwer FastAPI + UI (`app/static/`); `/api/anonymize`, `/api/progress/{job}`, `/api/render` |
| `config/default_settings.json` | ustawienia domyślne |

## Testy

```bash
pytest -q
```

Testy używają fikcyjnego wyroku (`tests/make_fixture.py`) oraz fikcyjnej decyzji „z konwersji PDF”
(`tests/make_fixture_pdf.py`: linia = akapit, numery stron luzem, nazwiska rozcięte między linie).
Ta sama decyzja jest składana w prawdziwy wielostronicowy PDF (`tests/make_fixture_pdf_file.py`, generowany
w katalogu tymczasowym), razem z „skanem” bez tekstu i PDF-em częściowo zeskanowanym.

## Ograniczenia

- Automat może coś pominąć (szczególnie nietypowe nazwiska bez imienia lub adresy bez „ul."). **Zawsze
  przejrzyj wynik** – przycisk „Następny do sprawdzenia” prowadzi po niepewnych fragmentach, a pominięty
  tekst można zaznaczyć myszą. Przycisk „Kopiuj” ostrzega, gdy coś zostało niesprawdzone.
- Organy publiczne (sądy, prezydent miasta, wojewoda, rada, ministerstwa) celowo **nie są** anonimizowane.
- Obsługiwane są `.docx` i `.pdf` (stary `.doc` zapisz w Wordzie jako `.docx`).
- PDF: tylko warstwa tekstowa, **bez OCR** – skany trzeba najpierw rozpoznać innym programem. Z PDF-a nie
  odtwarzamy nagłówków, list numerowanych ani tabel (tekst idzie jak wklejony); powtarzające się nagłówki
  i stopki stron zostają w tekście. PDF zabezpieczony hasłem trzeba najpierw odblokować.
- Grafiki, pola formularzy i komentarze Worda są pomijane.
