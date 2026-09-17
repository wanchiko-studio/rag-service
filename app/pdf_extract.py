"""PDF text extraction, page by page.

Ported from `tender-summarizer`, with one deliberate change: that version flattened
the whole document into a single string with «--- Страница N ---» markers inside it.
Here each page is kept as its own record, because every chunk has to be able to say
which page it came from. A citation that cannot be checked is worth nothing.

Does no LLM work. Tender PDFs from zakupki.gov.ru are usually born-digital with a
real text layer, so pdfplumber gets everything. Scanned files have no text layer at
all, and that case is detected and reported rather than passed on as an empty string.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pdfplumber

from app.normalize import NormalizationReport, normalize_text


class PdfExtractionError(Exception):
    """Raised when the file is not a usable PDF."""


@dataclass(slots=True)
class PageText:
    """One page's text layer, plus any tables rendered underneath it."""

    number: int  # 1-based, as a human would cite it
    text: str

    @property
    def characters(self) -> int:
        return len(self.text)


@dataclass(slots=True)
class ExtractedDocument:
    filename: str
    pages: list[PageText]
    normalization: NormalizationReport = field(default_factory=NormalizationReport)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def characters(self) -> int:
        return sum(page.characters for page in self.pages)


# Below this many characters per page we assume there is no real text layer.
MIN_CHARS_PER_PAGE = 20


def extract_pages(data: bytes, *, filename: str = "upload.pdf") -> ExtractedDocument:
    """Pull the text layer out of a PDF, one record per page.

    Tables are extracted separately and appended to their own page, because a
    tender's price and penalty schedule almost always lives in a table, and
    pdfplumber's plain `extract_text` flattens table cells into an unreadable
    run of numbers.
    """
    if not data:
        raise PdfExtractionError("Файл пустой")
    if not data.lstrip()[:5].startswith(b"%PDF-"):
        raise PdfExtractionError(f"{filename} не похож на PDF (нет заголовка %PDF-)")

    pages: list[PageText] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                parts: list[str] = []

                body = (page.extract_text() or "").strip()
                if body:
                    parts.append(body)

                for table in page.extract_tables() or []:
                    rendered = _render_table(table)
                    if rendered:
                        parts.append(f"[Таблица, стр. {index}]\n{rendered}")

                pages.append(PageText(number=index, text="\n\n".join(parts)))
    except PdfExtractionError:
        raise
    except Exception as exc:  # pdfplumber raises a wide variety of errors
        raise PdfExtractionError(f"Не удалось прочитать PDF: {exc}") from exc

    # Repair font-encoding damage before anything downstream sees the text, because
    # embeddings built on corrupted words would all have to be rebuilt afterwards.
    report = NormalizationReport()
    for page in pages:
        page.text, page_report = normalize_text(page.text)
        report.unconditional += page_report.unconditional
        report.contextual += page_report.contextual
        for char, count in page_report.remaining.items():
            report.remaining[char] = report.remaining.get(char, 0) + count

    doc = ExtractedDocument(filename=filename, pages=pages, normalization=report)

    if doc.page_count and doc.characters < MIN_CHARS_PER_PAGE * doc.page_count:
        raise PdfExtractionError(
            "В PDF нет текстового слоя — вероятно, это скан. "
            "Нужен OCR, который в это задание не входит."
        )

    return doc


def extract_pages_from_path(path: str) -> ExtractedDocument:
    """Convenience wrapper for local files; the service itself receives bytes."""
    import os

    with open(path, "rb") as handle:
        return extract_pages(handle.read(), filename=os.path.basename(path))


def _render_table(table: list[list[str | None]]) -> str:
    """Turn a pdfplumber table into pipe-delimited rows the model can parse."""
    rows: list[str] = []
    for row in table:
        cells = [(cell or "").replace("\n", " ").strip() for cell in row]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)
