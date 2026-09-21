"""Indexing and retrieval against a real Qdrant, held in memory.

What this proves is the plumbing: a chunk goes in with its page labels, comes back with
them intact, and the citation renders correctly. It says nothing about whether the right
chunk came back first — the embedder here is a hash. Ranking quality is `rag-eval`'s
job, and a test that pretended otherwise would be measuring its own fixture.
"""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient

from app.chunking import Chunk
from app.store import (
    DEFAULT_COLLECTION,
    SearchHit,
    current_collection,
    describe_mode,
    ensure_collection,
    index_chunks,
    search,
)


def make_chunks(*texts: str) -> list[Chunk]:
    return [
        Chunk(text=text, source_file="doc.pdf", page_start=i, page_end=i, index=i - 1)
        for i, text in enumerate(texts, start=1)
    ]


def test_index_then_search_returns_the_chunk(store: QdrantClient):
    ensure_collection(store)
    stored = index_chunks(store, make_chunks("пеня за просрочку поставки"))

    assert stored == 1

    hits = search(store, "пеня за просрочку поставки", top_k=1)
    assert len(hits) == 1
    assert hits[0].text == "пеня за просрочку поставки"
    assert hits[0].source_file == "doc.pdf"


def test_citation_metadata_survives_the_round_trip(store: QdrantClient):
    """The point of the whole payload: an answer you can go and check."""
    ensure_collection(store)
    index_chunks(
        store,
        [Chunk(text="условия оплаты", source_file="tender.pdf", page_start=11, page_end=12, index=0)],
    )

    hit = search(store, "условия оплаты", top_k=1)[0]
    assert hit.page_start == 11
    assert hit.page_end == 12
    assert hit.citation == "tender.pdf, стр. 11–12"


def test_top_k_limits_the_result_count(store: QdrantClient):
    ensure_collection(store)
    index_chunks(store, make_chunks("один", "два", "три", "четыре", "пять"))

    assert len(search(store, "один", top_k=2)) == 2
    assert len(search(store, "один", top_k=5)) == 5


def test_second_document_does_not_overwrite_the_first(store: QdrantClient):
    """Point ids continue rather than restarting, or indexing twice silently truncates."""
    ensure_collection(store)
    index_chunks(store, make_chunks("первый документ"))
    index_chunks(store, make_chunks("второй документ"))

    assert store.count(collection_name=DEFAULT_COLLECTION, exact=True).count == 2


def test_reset_empties_the_collection(store: QdrantClient):
    ensure_collection(store)
    index_chunks(store, make_chunks("старые данные"))

    ensure_collection(store, reset=True)

    assert store.count(collection_name=DEFAULT_COLLECTION, exact=True).count == 0


def test_indexing_nothing_is_not_an_error(store: QdrantClient):
    """An empty or scanned PDF reaches here as zero chunks. Report it, do not raise."""
    ensure_collection(store)
    assert index_chunks(store, []) == 0


def test_searching_an_empty_collection_returns_nothing(store: QdrantClient):
    """No results is a legitimate answer, distinguishable via /health's point count."""
    ensure_collection(store)
    assert search(store, "что угодно") == []


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [(4, 4, "f.pdf, стр. 4"), (4, 5, "f.pdf, стр. 4–5")],
)
def test_citation_formats_single_page_and_range(start: int, end: int, expected: str):
    hit = SearchHit(score=0.5, text="t", source_file="f.pdf", page_start=start, page_end=end)
    assert hit.citation == expected


def test_describe_mode_reports_url_over_path(monkeypatch: pytest.MonkeyPatch):
    """QDRANT_URL wins, and /health has to say so — switching modes silently swaps
    which store you are querying, and the empty one answers with silence."""
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    assert describe_mode().startswith("container")

    monkeypatch.delenv("QDRANT_URL")
    assert describe_mode().startswith("embedded")


def test_collection_name_is_read_when_used_not_at_import(
    store: QdrantClient, monkeypatch: pytest.MonkeyPatch
):
    """A QDRANT_COLLECTION set after import must take effect — and be the one used.

    The name used to be frozen at import while the path and URL were re-read at call
    time, so setting it inside a running process changed nothing and said nothing.
    Checking the helper alone is not enough: this proves indexing and search both
    follow it, so what gets written is what gets read.
    """
    monkeypatch.setenv("QDRANT_COLLECTION", "tenders_eval")
    assert current_collection() == "tenders_eval"
    assert current_collection("explicit") == "explicit"  # an explicit name still wins

    ensure_collection(store)
    index_chunks(store, make_chunks("пеня за просрочку"))
    assert store.collection_exists("tenders_eval")
    assert not store.collection_exists("tenders")
    assert search(store, "пеня за просрочку"), "searched somewhere other than it wrote"

    monkeypatch.delenv("QDRANT_COLLECTION")
    assert current_collection() == "tenders"
