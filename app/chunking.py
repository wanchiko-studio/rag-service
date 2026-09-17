"""Splitting a document into pieces small enough to search, labelled well enough to cite.

Ported from `tender-summarizer`. The splitting rules are unchanged and they still matter:

1. Split on paragraph boundaries, never mid-sentence, so a price and its currency
   cannot land in different chunks.
2. Overlap consecutive chunks slightly, so a clause that straddles a boundary is
   complete in at least one of them.

What is new here is the labelling. Every chunk records which file and which page(s)
it came from, so an answer can cite a source the reader can go and check.

A design note worth keeping, because it is the obvious question:
chunking each page separately would give exact page numbers for free, but tender
clauses routinely straddle a page break, and cutting there would split exactly the
sentences that matter. So the document is joined and split as one body, character
offsets are tracked, and each chunk resolves its own page span afterwards. A chunk
that crosses a boundary cites a range — «стр. 11–12» — which is honest rather than
convenient.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.pdf_extract import ExtractedDocument

OVERLAP_CHARS = 500
PAGE_SEPARATOR = "\n\n"


@dataclass(slots=True)
class Chunk:
    """A searchable piece of a document, carrying enough to cite itself."""

    text: str
    source_file: str
    page_start: int
    page_end: int
    index: int

    @property
    def citation(self) -> str:
        if self.page_start == self.page_end:
            return f"{self.source_file}, стр. {self.page_start}"
        return f"{self.source_file}, стр. {self.page_start}–{self.page_end}"

    @property
    def characters(self) -> int:
        return len(self.text)


def split_spans(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Split `text` into (start, end) spans of at most `max_chars`.

    Returns offsets rather than strings so the caller can map each piece back to
    the page it came from. The boundary preference is blank line, then newline,
    then sentence end.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if not text:
        return []
    if len(text) <= max_chars:
        return [(0, len(text))]

    spans: list[tuple[int, int]] = []
    start = 0
    overlap = min(OVERLAP_CHARS, max_chars // 4)

    while start < len(text):
        end = min(start + max_chars, len(text))

        if end < len(text):
            window_floor = start + int(max_chars * 0.5)
            boundary = text.rfind("\n\n", window_floor, end)
            if boundary == -1:
                boundary = text.rfind("\n", window_floor, end)
            if boundary == -1:
                boundary = text.rfind(". ", window_floor, end)
            if boundary != -1:
                end = boundary

        if text[start:end].strip():
            spans.append((start, end))

        if end >= len(text):
            break

        # The end of a chunk lands on a boundary, but the start of the next one is
        # just `end - overlap`, which lands wherever it lands — mid-word, in practice.
        # A retrieved passage that opens «he claim they care about» reads as broken,
        # and embedding a fragment that starts mid-sentence is noisier than it needs
        # to be. So walk forward to the nearest real boundary.
        start = _align_start(text, max(end - overlap, start + 1), max(120, overlap // 2))

    return spans


def _align_start(text: str, pos: int, limit: int) -> int:
    """Nudge `pos` forward to the next sensible boundary, at most `limit` chars.

    Prefers a paragraph break, then a line break, then a sentence end, and failing
    all three simply steps past the partial word so a chunk never opens mid-word.
    Only ever moves forward, so the caller's loop always makes progress.
    """
    if pos <= 0 or pos >= len(text):
        return pos
    if text[pos - 1].isspace():
        return pos  # already at a boundary

    window = text[pos : pos + limit]
    for separator in ("\n\n", "\n", ". "):
        offset = window.find(separator)
        if offset != -1:
            return pos + offset + len(separator)

    offset = window.find(" ")
    if offset != -1:
        return pos + offset + 1

    return pos


def chunk_document(
    doc: ExtractedDocument,
    *,
    max_chars: int = 2000,
) -> list[Chunk]:
    """Turn an extracted document into labelled, citable chunks."""
    body, page_ranges = _join_pages(doc)

    chunks: list[Chunk] = []
    for position, (start, end) in enumerate(split_spans(body, max_chars)):
        piece = body[start:end].strip()
        if not piece:
            continue
        first, last = _pages_for_span(start, end, page_ranges)
        chunks.append(
            Chunk(
                text=piece,
                source_file=doc.filename,
                page_start=first,
                page_end=last,
                index=position,
            )
        )
    return chunks


def _join_pages(doc: ExtractedDocument) -> tuple[str, list[tuple[int, int, int]]]:
    """Join pages into one body, recording (page_number, start, end) for each."""
    parts: list[str] = []
    ranges: list[tuple[int, int, int]] = []
    cursor = 0

    for page in doc.pages:
        if not page.text.strip():
            continue
        parts.append(page.text)
        ranges.append((page.number, cursor, cursor + len(page.text)))
        cursor += len(page.text) + len(PAGE_SEPARATOR)

    return PAGE_SEPARATOR.join(parts), ranges


def _pages_for_span(
    start: int, end: int, ranges: list[tuple[int, int, int]]
) -> tuple[int, int]:
    """Which page(s) a character span overlaps."""
    touched = [
        number
        for number, page_start, page_end in ranges
        if start < page_end and end > page_start
    ]
    if not touched:
        return (0, 0)  # empty document; caller decides what that means
    return (min(touched), max(touched))
