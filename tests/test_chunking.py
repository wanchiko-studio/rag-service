"""Chunking: size limits, page-range citations, and not opening mid-word.

The size limit is not cosmetic. The embedding model truncates at 512 tokens with no
error and no warning, so a chunk that is too long loses its tail silently — the third
instance of this project's recurring failure class.
"""

from __future__ import annotations

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
    """The limit that keeps text inside the model's 512-token window."""
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
