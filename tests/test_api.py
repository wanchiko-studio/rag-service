"""The HTTP contract: what /ask promises a caller, and what /health admits to.

TestClient is deliberately *not* used as a context manager. Entering it would run the
app's lifespan, which opens the real store — taking the embedded mode's exclusive lock
on a developer's actual index. Skipping lifespan and overriding `get_store` keeps the
tests pointed at the in-memory Qdrant, where they belong.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from app.api import app, get_store
from app.chunking import Chunk
from app.store import ensure_collection, index_chunks


@pytest.fixture
def client(store: QdrantClient) -> TestClient:
    ensure_collection(store)
    index_chunks(
        store,
        [
            Chunk(text="Срок поставки — 30 календарных дней с даты подписания.",
                  source_file="contract.pdf", page_start=1, page_end=1, index=0),
            Chunk(text="Пеня за просрочку поставки составляет 0,1% в день.",
                  source_file="tender.pdf", page_start=4, page_end=5, index=1),
        ],
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_ask_returns_ranked_hits_with_citations_and_scores(client: TestClient):
    """The whole contract in one assertion block."""
    response = client.post("/ask", json={"question": "какая пеня за просрочку?"})
    assert response.status_code == 200

    body = response.json()
    assert body["question"] == "какая пеня за просрочку?"
    assert body["hits"], "expected at least one passage back"

    for position, hit in enumerate(body["hits"], start=1):
        assert hit["rank"] == position  # ranks are 1-based and in order
        assert isinstance(hit["score"], float)
        assert hit["citation"]
        assert hit["text"]


def test_mode_is_declared_so_generation_can_be_added_later(client: TestClient):
    """`mode` is the discriminator that keeps Week 3 additive.

    A client written today branches on this field rather than sniffing for the presence
    of `answer`, so adding generation later changes the value and breaks nobody.
    """
    body = client.post("/ask", json={"question": "вопрос"}).json()

    assert body["mode"] == "retrieval-only"
    assert "answer" not in body  # nothing is generated, and nothing pretends to be


def test_citation_carries_the_page_range(client: TestClient):
    body = client.post("/ask", json={"question": "пеня", "top_k": 2}).json()
    citations = {hit["citation"] for hit in body["hits"]}

    assert any("стр. 4–5" in c for c in citations)


def test_top_k_is_honoured_and_echoed(client: TestClient):
    body = client.post("/ask", json={"question": "вопрос", "top_k": 1}).json()

    assert body["top_k"] == 1
    assert len(body["hits"]) == 1


def test_empty_question_is_rejected(client: TestClient):
    """Better a 422 than embedding the empty string and returning arbitrary neighbours."""
    assert client.post("/ask", json={"question": ""}).status_code == 422


def test_absurd_top_k_is_rejected(client: TestClient):
    assert client.post("/ask", json={"question": "в", "top_k": 9999}).status_code == 422


def test_missing_question_is_rejected(client: TestClient):
    assert client.post("/ask", json={}).status_code == 422


def test_health_reports_mode_and_point_count(client: TestClient):
    """The point count is the field that distinguishes "retrieval is bad" from
    "you are querying an empty store because you switched QDRANT_URL"."""
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["points"] == 2
    assert body["mode"].startswith(("embedded", "container"))


def test_no_results_is_two_hundred_not_four_oh_four(store: QdrantClient):
    """Nothing found is an answer, not a missing resource."""
    ensure_collection(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        response = TestClient(app).post("/ask", json={"question": "что угодно"})
        assert response.status_code == 200
        assert response.json()["hits"] == []
    finally:
        app.dependency_overrides.clear()
