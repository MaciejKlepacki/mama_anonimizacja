"""CLI: python -m app.cli plik.docx [-o wynik.md] [--mapa mapa.json]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import anonymize_docx
from .settings import load_settings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Anonimizacja dokumentu Word (.docx) → Markdown (Presidio).")
    ap.add_argument("docx", nargs="+", help="plik(i) .docx")
    ap.add_argument("-o", "--output", help="plik wyjściowy .md (tylko dla jednego pliku); domyślnie obok źródła")
    ap.add_argument("--mapa", help="zapisz mapę placeholderów (JSON) do podanego pliku")
    ap.add_argument("--stdout", action="store_true", help="wypisz Markdown na stdout zamiast do pliku")
    args = ap.parse_args(argv)

    if args.output and len(args.docx) > 1:
        ap.error("-o działa tylko dla jednego pliku wejściowego")

    settings = load_settings()
    for src in args.docx:
        path = Path(src)
        if not path.is_file():
            print(f"Brak pliku: {path}", file=sys.stderr)
            return 2
        result = anonymize_docx(str(path), settings, source_name=path.name)
        if args.stdout:
            sys.stdout.write(result.markdown)
        else:
            out = Path(args.output) if args.output else path.with_name(path.stem + "_anonimizacja.md")
            out.write_text(result.markdown, encoding="utf-8")
            print(f"{path.name} → {out}  ({sum(result.stats.values())} podmian, {result.seconds}s)", file=sys.stderr)
        if args.mapa:
            Path(args.mapa).write_text(json.dumps(result.mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
