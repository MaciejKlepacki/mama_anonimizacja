# mama_anonimizacja

Lokalna aplikacja do anonimizacji dokumentów sądowych: **Word (.docx) → Markdown** z użyciem
[Microsoft Presidio](https://microsoft.github.io/presidio/) i polskiego modelu spaCy (`pl_core_news_lg`).
Wszystko działa na `localhost`; pliki nie są nigdzie wysyłane ani zapisywane na dysku.

## Co robi

1. Wrzucasz plik `.docx` w przeglądarce (http://127.0.0.1:8765).
2. Pipeline wykrywa i podmienia dane wrażliwe na spójne placeholdery, domyślnie:
   - imiona i nazwiska → `[OSOBA_1]`, `[OSOBA_2]`, …
   - adresy (ulica + numer, kod pocztowy + miejscowość) → `[ADRES_n]`
   - numery działek ewidencyjnych („działka nr 123/4", „dz. 12, 13/2") → `[DZIAŁKA_n]`
   - numery ksiąg wieczystych, PESEL, NIP, REGON, KRS, dowód osobisty, telefon, e-mail, IBAN
   - opcjonalnie (wyłączone domyślnie): miejscowości, organizacje, daty, sygnatury akt, adresy www
3. Wynik to plik Markdown gotowy do wklejenia do czatu z LLM:
   - krótki wstęp objaśniający modelowi placeholdery + legenda,
   - zachowana struktura: nagłówki, listy, tabele, przypisy,
   - jeden placeholder = jedna osoba/obiekt w całym dokumencie, także mimo odmiany
     („Jan Kowalski", „Jana Kowalskiego", „Kowalski" → `[OSOBA_1]`),
   - bez zbędnych pustych linii i formatowania.
4. Osobno dostępna jest **mapa placeholderów** (JSON, tylko lokalnie) – do odczytania odpowiedzi modelu.

## Uruchomienie

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
```

## Ustawienia

Strona **Ustawienia** (http://127.0.0.1:8765/settings) albo plik `config/settings.json`
(nadpisuje `config/default_settings.json`; nie jest commitowany):

- włączanie/wyłączanie encji, etykieta placeholdera, próg pewności,
- **allow-lista** – frazy nigdy nie anonimizowane (domyślnie nazwy sądów, województw),
- **deny-lista** – frazy zawsze anonimizowane, np. `PERSON: Jan Kowalski; Kowalskiego`,
- **własne rozpoznawacze** regex (Presidio `PatternRecognizer`), np. numery decyzji,
- opcje czytania Worda (przypisy, nagłówki/stopki, pogrubione linie jako nagłówki),
- opcje wyniku (tytuł, wstęp dla modelu, legenda).

Na stronie ustawień jest pole „Test na tekście", które sprawdza bieżące (także niezapisane) ustawienia.

## Jak to działa

```
.docx ──python-docx──▶ bloki (nagłówki/akapity/listy/tabele/przypisy)
      ──Presidio Analyzer (spaCy NER pl + rozpoznawacze PL)──▶ encje
      ──propagacja znanych wartości (2. przebieg)──▶ encje także bez kontekstu (np. „123/4" w tabeli)
      ──Presidio Anonymizer + spójne placeholdery (lematyzacja)──▶ bloki zanonimizowane
      ──renderer──▶ Markdown + mapa placeholderów
```

Ważne pliki:

| Plik | Rola |
| --- | --- |
| `app/recognizers.py` | polskie rozpoznawacze (działki, adresy, KW, NIP, REGON, KRS, dowód, daty, sygnatury) |
| `app/engine.py` | konfiguracja Presidio, allow-lista, spójne placeholdery |
| `app/docx_reader.py` | czytanie Worda do bloków |
| `app/markdown.py` | rendering Markdown pod LLM |
| `app/pipeline.py` | cały przebieg |
| `app/main.py` | serwer FastAPI + UI (`app/static/`) |
| `config/default_settings.json` | ustawienia domyślne |

## Testy

```bash
pytest -q
```

Testy używają fikcyjnego wyroku generowanego przez `tests/make_fixture.py`.

## Ograniczenia

- Automat może coś pominąć (szczególnie nietypowe nazwiska lub adresy bez „ul."). **Zawsze przejrzyj
  wynik** przed wklejeniem do czatu; pole wyniku jest edytowalne.
- Obsługiwany jest tylko `.docx` (stary `.doc` zapisz w Wordzie jako `.docx`).
- Grafiki, pola formularzy i komentarze Worda są pomijane.
