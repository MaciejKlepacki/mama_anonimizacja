# mama_anonimizacja

Lokalna aplikacja do anonimizacji dokumentów sądowych (Word → Markdown) z użyciem [Microsoft Presidio](https://microsoft.github.io/presidio/).

## Cel

1. Użytkownik wrzuca plik `.docx` do aplikacji działającej na `localhost`.
2. Pipeline wykrywa i anonimizuje dane wrażliwe, domyślnie:
   - imiona i nazwiska,
   - adresy,
   - numery działek ewidencyjnych,
   - (konfigurowalnie) kolejne encje obsługiwane przez Presidio.
3. Wynikiem jest plik Markdown zoptymalizowany pod wklejenie do czatu z LLM.

## Status

Repozytorium zainicjowane. Implementacja w toku.
