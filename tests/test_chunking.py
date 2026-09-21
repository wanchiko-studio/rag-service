"""Chunking: size limits, page-range citations, not opening mid-word, not losing text.

The size limit is not cosmetic. The embedding model reads only the first 128 tokens of
a chunk and discards the rest with no error and no warning, so how documents are cut
decides what the model can see at all — the same failure class this project keeps
finding: wrong behaviour that does not complain.
"""

from __future__ import annotations

import random

from app.chunking import chunk_document, split_spans
from app.normalize import NormalizationReport
from app.pdf_extract import ExtractedDocument, PageText


def make_doc(pages: list[str], filename: str = "doc.pdf") -> ExtractedDocument:
    """Build an ExtractedDocument without going near a real PDF."""
    return ExtractedDocument(
        filename=filename,
        pages=[PageText(number=i, text=text) for i, text in enumerate(pages, start=1)],
        normalization=NormalizationReport(),
    )


def test_short_document_is_a_single_chunk():
    chunks = chunk_document(make_doc(["Короткий документ."]), max_chars=1200)

    assert len(chunks) == 1
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 1


def test_every_chunk_respects_max_chars():
    """max_chars is a hard cap — it is the knob rag-eval turns, so it must hold exactly."""
    page = ". ".join(f"Предложение номер {i} про обработку данных" for i in range(200))
    chunks = chunk_document(make_doc([page]), max_chars=600)

    assert len(chunks) > 1
    assert all(chunk.characters <= 600 for chunk in chunks)


def test_chunk_crossing_a_page_break_cites_a_range():
    """Chunking runs across the whole document, so a chunk can span two pages.

    Citing «стр. 1–2» is the honest output. Per-page chunking would give exact single
    page numbers, but it would cut clauses at the page break — which is precisely where
    tender text tends to continue.
    """
    first = "А" * 1100
    second = "Б" * 1100
    chunks = chunk_document(make_doc([first, second]), max_chars=1500)

    spanning = [c for c in chunks if c.page_start != c.page_end]
    assert spanning, "expected at least one chunk to straddle the page break"
    assert spanning[0].citation == "doc.pdf, стр. 1–2"


def test_single_page_chunk_cites_one_page():
    chunks = chunk_document(make_doc(["Только одна страница."]), max_chars=1200)

    assert chunks[0].citation == "doc.pdf, стр. 1"


def test_chunks_do_not_open_mid_word():
    """A retrieved passage beginning «ботка данных» reads as broken to a human, and
    embeds a fragment that starts mid-sentence, which is noisier than it needs to be.
    """
    page = " ".join(f"слово{i}" for i in range(400))
    chunks = chunk_document(make_doc([page]), max_chars=500)

    assert len(chunks) > 1
    for chunk in chunks[1:]:
        assert chunk.text.startswith("слово"), f"opened mid-word: {chunk.text[:20]!r}"


def test_empty_pages_are_skipped_not_counted():
    """A blank page must not shift the page numbers of everything after it."""
    chunks = chunk_document(make_doc(["Первая страница.", "   ", "Третья страница."]))

    assert chunks
    pages_seen = {c.page_start for c in chunks} | {c.page_end for c in chunks}
    assert 2 not in pages_seen


def test_split_spans_rejects_a_nonsense_limit():
    """Fail on a bad argument rather than looping forever or returning nothing."""
    try:
        split_spans("какой-то текст", 0)
    except ValueError:
        return
    raise AssertionError("max_chars=0 should raise ValueError")


def test_no_text_is_lost_between_chunks_at_small_max_chars():
    """Every character of the body lands in at least one chunk, at eight sizes.

    Regression guard. `_align_start` walks forward up to `max(120, overlap // 2)`
    characters looking for a boundary, while the overlap it starts from is
    `min(500, max_chars // 4)`. Below max_chars=480 the first number exceeds the
    second, so the next chunk could begin PAST the end of the previous one.

    What this particular input catches is the mildest form: at max_chars=200 the old
    code skipped the two-character paragraph break between chunks. Its long run has no
    sentence boundaries inside it, so it cannot show words going missing — the test
    below does that.
    """
    body = "Раздел 1. Общие положения.\n\n" + ("A" * 900) + "\n\nРаздел 2. Цена контракта."
    for max_chars in (2000, 1200, 800, 600, 480, 400, 300, 200):
        covered: set[int] = set()
        for start, end in split_spans(body, max_chars):
            covered.update(range(start, end))
        missing = sorted(set(range(len(body))) - covered)
        assert not missing, (
            f"max_chars={max_chars}: {len(missing)} characters in no chunk, "
            f"first at {missing[0]}: {body[missing[0]:missing[0] + 40]!r}"
        )


def _words_lost(body: str, max_chars: int) -> str:
    """Every non-whitespace character that ended up in no chunk, in order."""
    covered: set[int] = set()
    for start, end in split_spans(body, max_chars):
        covered.update(range(start, end))
    return "".join(ch for i, ch in enumerate(body) if i not in covered and not ch.isspace())


def test_no_words_are_lost_between_chunks_below_480():
    """The real form of the gap bug: whole words indexed nowhere.

    Before the clamp, at max_chars=200 this 213-character document came back with a gap
    between two chunks, and the sentence «Договор оплата заказчик.» was in neither of
    them. The fixed-seed sweep underneath covers the other sizes below 480.

    Whitespace is excluded on purpose. The clamped code can still leave a paragraph break
    between two chunks, which costs nothing — but an every-character check would fail
    correct code for it, and a test that fails correct code is a test that gets deleted.
    """
    body = (
        "Пеня товара. \n\n"
        "Оплата пеня цена поставка заказчик пеня цена. Договор срок поставка пеня товара. "
        "Заказчик цена срок пеня поставка. Товара цена поставка оплата товара пеня цена. "
        "Договор оплата заказчик. \n\n"
        "Цена срок."
    )
    assert not _words_lost(body, 200), f"lost: {_words_lost(body, 200)!r}"

    rng = random.Random(1)  # fixed seed: the same 300 documents on every run
    vocabulary = ["поставка", "товара", "срок", "пеня", "оплата", "заказчик", "договор", "цена"]
    for _ in range(300):
        parts = []
        for _ in range(rng.randint(3, 25)):
            words = " ".join(rng.choice(vocabulary) for _ in range(rng.randint(2, 12)))
            parts.append(words.capitalize() + ". ")
            if rng.random() < 0.3:
                parts.append("\n\n")
        document = "".join(parts).strip()
        for max_chars in (200, 300, 400, 479):
            lost = _words_lost(document, max_chars)
            assert not lost, f"max_chars={max_chars}: lost {lost[:60]!r}"
