"""HTTP access to the retriever.

    uvicorn app.api:app --reload
    curl -s localhost:8000/health
    curl -s localhost:8000/ask -H 'content-type: application/json' \
         -d '{"question": "какая пеня за просрочку поставки?"}'

🔑 RETRIEVAL ONLY, ON PURPOSE. This endpoint does not write an answer, because there
is no model behind it yet and inventing one would mean inventing an API key. What it
returns is the ranked passages, their scores and their citations — which is the part
that can actually be checked, and the part `rag-eval` will put a number on. Generation
lands in Week 3, against a local model, where it can be run without a secret.

Saying «мы ничего не выдумываем» is easy. Shipping an endpoint whose contract makes it
impossible to fabricate an answer is the version an employer can verify in ten seconds.

THE RESPONSE SHAPE IS BUILT SO GENERATION IS ADDITIVE. `mode` is the discriminator:
today every response says "retrieval-only". When a model is wired in, responses gain an
`answer` object and `mode` becomes "generated". Nothing that reads `hits` today breaks,
and a client can branch on `mode` instead of guessing from the presence of a field.

⚠️ In embedded mode the store holds an exclusive lock on its folder, so this API and
the CLI scripts cannot run at the same time. `docker compose up -d` plus QDRANT_URL is
the way to have both.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient

from app.store import (
    SearchHit,
    current_collection,
    describe_mode,
    ensure_collection,
    open_store,
    search,
)

DEFAULT_TOP_K = 3
MAX_TOP_K = 20

# Populated at startup. Module-level rather than passed around because the embedded
# store's exclusive lock means there can only ever be one of these per process anyway.
_client: QdrantClient | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Open the store once for the life of the process, and close it on the way out.

    Opening per request would be wrong in both modes: embedded would fight its own
    lock, and the container would pay a connection setup on every question.
    """
    global _client
    _client = open_store()
    ensure_collection(_client)
    try:
        yield
    finally:
        if _client is not None:
            _client.close()
            _client = None


app = FastAPI(
    title="rag-service",
    version="0.3.0",
    summary="Retrieves the passages that answer a question, with citations and scores.",
    lifespan=lifespan,
)


def get_store() -> QdrantClient:
    """The store, as a dependency so tests can substitute an in-memory one."""
    if _client is None:  # pragma: no cover - only reachable outside the lifespan
        raise HTTPException(status_code=503, detail="Хранилище не открыто")
    return _client


# --------------------------------------------------------------------------- models


class AskRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=1000,
        description="Вопрос на любом языке — поиск векторный, не по ключевым словам.",
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        ge=1,
        le=MAX_TOP_K,
        description="Сколько отрывков вернуть.",
    )


class Hit(BaseModel):
    """One retrieved passage: enough to judge it and enough to go and check it."""

    rank: int = Field(description="1 — ближайший.")
    score: float = Field(description="Косинусная близость. ~0.5 — слабое совпадение.")
    citation: str = Field(description="Готовая ссылка, например «file.pdf, стр. 4–5».")
    source_file: str
    page_start: int
    page_end: int
    text: str

    @classmethod
    def from_search_hit(cls, hit: SearchHit, rank: int) -> "Hit":
        # citation is derived in store.SearchHit so the API and the CLI cannot drift
        # into formatting page ranges two different ways.
        return cls(
            rank=rank,
            score=hit.score,
            citation=hit.citation,
            source_file=hit.source_file,
            page_start=hit.page_start,
            page_end=hit.page_end,
            text=hit.text,
        )


class AskResponse(BaseModel):
    question: str
    mode: Literal["retrieval-only"] = Field(
        default="retrieval-only",
        description=(
            "Что содержит ответ. Сейчас всегда «retrieval-only»: модель не вызывается, "
            "текст ответа не генерируется. Появится «generated» — появится и поле answer."
        ),
    )
    top_k: int
    hits: list[Hit]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    mode: str = Field(description="«embedded (…)» или «container (…)».")
    collection: str
    points: int = Field(description="Сколько отрывков проиндексировано. 0 — индекс пуст.")


# --------------------------------------------------------------------------- routes


@app.get("/health", response_model=HealthResponse)
def health(client: QdrantClient = Depends(get_store)) -> HealthResponse:
    """Is it up, which store is it on, and does that store actually have anything in it?

    The point count is here because the most likely failure in this system is not a
    crash — it is querying an empty collection after switching between embedded and
    container mode, which otherwise returns "no results" and looks like bad retrieval.

    The collection name is resolved once, so the name reported and the collection
    counted are guaranteed to be the same one — the same name `/ask` resolves to.
    """
    collection = current_collection()
    return HealthResponse(
        status="ok",
        mode=describe_mode(),
        collection=collection,
        points=client.count(collection_name=collection, exact=True).count,
    )


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, client: QdrantClient = Depends(get_store)) -> AskResponse:
    """Return the passages nearest to the question, ranked, cited and scored.

    An empty result is a legitimate answer — it means nothing was indexed, or nothing
    was close enough — so it returns 200 with an empty list rather than a 404. The
    caller can tell the two apart with /health.
    """
    hits = search(client, request.question, top_k=request.top_k)
    return AskResponse(
        question=request.question,
        top_k=request.top_k,
        hits=[Hit.from_search_hit(hit, rank) for rank, hit in enumerate(hits, start=1)],
    )
