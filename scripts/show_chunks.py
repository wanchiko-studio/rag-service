"""Eyeball the chunker on a real document.

    python scripts/show_chunks.py <path-to.pdf> [--max-chars 2000] [--show 3]

Prints what was extracted, how it was cut, and the first few chunks with their
citations — so you can see whether the paragraph boundaries actually hold on real
Russian text, rather than trusting that they do.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.chunking import chunk_document  # noqa: E402
from app.pdf_extract import PdfExtractionError, extract_pages_from_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--max-chars", type=int, default=2000)
    parser.add_argument("--show", type=int, default=3, help="how many chunks to print")
    args = parser.parse_args()

    try:
        doc = extract_pages_from_path(args.pdf)
    except PdfExtractionError as exc:
        print(f"Не удалось разобрать файл: {exc}")
        return 1

    empty = [p.number for p in doc.pages if not p.text.strip()]

    print(f"Файл:     {doc.filename}")
    print(f"Страниц:  {doc.page_count}")
    print(f"Символов: {doc.characters:,}".replace(",", " "))
    if empty:
        print(f"Пустые страницы (нет текста): {empty}")

    chunks = chunk_document(doc, max_chars=args.max_chars)
    if not chunks:
        print("\nЧанков нет — в документе не нашлось текста.")
        return 1

    sizes = [c.characters for c in chunks]
    crossing = [c for c in chunks if c.page_start != c.page_end]

    print(f"\nЧанков:   {len(chunks)}  (max_chars={args.max_chars})")
    print(f"Размеры:  min {min(sizes)} / среднее {sum(sizes) // len(sizes)} / max {max(sizes)}")
    print(f"На стыке страниц: {len(crossing)} из {len(chunks)}")

    print(f"\n{'=' * 72}")
    for chunk in chunks[: args.show]:
        print(f"[{chunk.index}] {chunk.citation}   ({chunk.characters} симв.)")
        print("-" * 72)
        print(chunk.text[:700])
        if chunk.characters > 700:
            print(f"… ещё {chunk.characters - 700} символов")
        print(f"{'=' * 72}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
