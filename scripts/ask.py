"""Ask a question and see which passages come back.

    python scripts/ask.py "какой срок выполнения работ?" [--top-k 3]

Retrieval only — no model is asked to write an answer yet. That is deliberate: if the
right passage is not in this list, no amount of prompting downstream will save the
answer. This is the part `rag-eval` will put a number on.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import open_store, search  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--chars", type=int, default=600, help="how much of each chunk to print")
    args = parser.parse_args()

    client = open_store()
    hits = search(client, args.question, top_k=args.top_k)

    if not hits:
        print("Ничего не найдено — возможно, коллекция пуста. Сначала запустите index_pdf.py")
        return 1

    print(f"Вопрос: {args.question}\n")
    for rank, hit in enumerate(hits, start=1):
        print(f"{'=' * 72}")
        print(f"#{rank}   score {hit.score:.4f}   {hit.citation}")
        print("-" * 72)
        body = hit.text.strip()
        print(body[: args.chars])
        if len(body) > args.chars:
            print(f"… ещё {len(body) - args.chars} символов")
    print("=" * 72)

    print(
        "\nScore — косинусная близость: 1.0 это идентичный текст, ~0.5 слабое совпадение.\n"
        "Смотрите не на число, а на то, действительно ли в этих отрывках есть ответ."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
