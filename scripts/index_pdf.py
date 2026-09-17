"""Index a PDF into the local vector store.

    python scripts/index_pdf.py <path-to.pdf> [--max-chars 1200] [--reset]

Extracts the text, repairs encoding damage, chunks it, embeds each chunk and stores it
with its citation. Reports token counts against the model's limit, because a chunk over
that limit is truncated silently and would otherwise look fine.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.chunking import chunk_document  # noqa: E402
from app.embed import MAX_TOKENS, count_tokens  # noqa: E402
from app.pdf_extract import PdfExtractionError, extract_pages_from_path  # noqa: E402
from app.store import ensure_collection, index_chunks, open_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--max-chars", type=int, default=1200)
    parser.add_argument("--reset", action="store_true", help="drop the collection first")
    args = parser.parse_args()

    try:
        doc = extract_pages_from_path(args.pdf)
    except PdfExtractionError as exc:
        print(f"Не удалось разобрать файл: {exc}")
        return 1

    print(f"Файл:      {doc.filename}  ({doc.page_count} стр., {doc.characters:,} симв.)".replace(",", " "))
    print(f"Кодировка: {doc.normalization.summary()}")

    chunks = chunk_document(doc, max_chars=args.max_chars)
    if not chunks:
        print("Текста не нашлось — индексировать нечего.")
        return 1

    tokens = [count_tokens(chunk.text) for chunk in chunks]
    over = [i for i, count in enumerate(tokens) if count > MAX_TOKENS]

    print(f"Чанков:    {len(chunks)}  (max_chars={args.max_chars})")
    print(f"Токенов:   min {min(tokens)} / среднее {sum(tokens) // len(tokens)} / max {max(tokens)}  (лимит модели {MAX_TOKENS})")
    if over:
        print(f"⚠️  ОБРЕЗАНО БУДЕТ {len(over)} чанков из {len(chunks)} — уменьшите --max-chars")
    else:
        print("✅ Все чанки влезают в окно модели целиком")

    print("\nЗагружаю модель и считаю векторы (первый запуск скачает ~0.22 ГБ)…")
    client = open_store()
    ensure_collection(client, reset=args.reset)
    stored = index_chunks(client, chunks)
    print(f"Записано в Qdrant: {stored} чанков")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
