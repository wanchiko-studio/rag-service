"""Storing and searching chunk vectors in Qdrant.

Runs Qdrant in **embedded mode** — `QdrantClient(path=...)` keeps everything in a
local folder with no server and no container. The target machine has no Docker, and
waiting on a Docker Desktop install would have cost the evening that built this.

The API is identical to the server version, so moving to a container later is a
one-line change:

    QdrantClient(path="qdrant_storage")      # embedded, today
    QdrantClient(url="http://localhost:6333")  # container, later

⚠️ Embedded mode takes an exclusive lock on its folder, so only one process can use
it at a time. That is fine for indexing and asking from the command line, and it is
exactly why the eventual FastAPI service will want the container instead.

🔑 THE STORE PATH IS ANCHORED TO THE REPO, NOT TO THE WORKING DIRECTORY. A relative
default would mean indexing from the repo root and asking from anywhere else opened
two different folders — and the second one would be empty, so the query would return
nothing and report no error. A wrong answer that does not complain is the same failure
class as the font-encoding damage, and it gets the same treatment: fixed here, rather
than written down as a rule someone has to remember. An explicit QDRANT_PATH still wins.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from app.chunking import Chunk
from app.embed import VECTOR_SIZE, embed_query, embed_texts

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_PATH = os.getenv("QDRANT_PATH") or os.path.join(_REPO_ROOT, "qdrant_storage")
DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "tenders")


@dataclass(slots=True)
class SearchHit:
    """One retrieved chunk, with everything needed to cite and judge it."""

    score: float
    text: str
    source_file: str
    page_start: int
    page_end: int

    @property
    def citation(self) -> str:
        if self.page_start == self.page_end:
            return f"{self.source_file}, стр. {self.page_start}"
        return f"{self.source_file}, стр. {self.page_start}–{self.page_end}"


def open_store(path: str = DEFAULT_PATH) -> QdrantClient:
    return QdrantClient(path=path)


def ensure_collection(
    client: QdrantClient,
    name: str = DEFAULT_COLLECTION,
    *,
    reset: bool = False,
) -> None:
    """Create the collection if missing. With `reset`, drop and rebuild it.

    Cosine distance, because these vectors are normalised and only direction carries
    meaning — two passages about penalties should match regardless of length.
    """
    exists = client.collection_exists(name)
    if exists and reset:
        client.delete_collection(name)
        exists = False
    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=VECTOR_SIZE, distance=models.Distance.COSINE
            ),
        )


def index_chunks(
    client: QdrantClient,
    chunks: list[Chunk],
    name: str = DEFAULT_COLLECTION,
    *,
    batch_size: int = 32,
) -> int:
    """Embed chunks and store them with the payload needed to cite them later."""
    if not chunks:
        return 0

    stored = 0
    start_id = _next_id(client, name)

    for offset in range(0, len(chunks), batch_size):
        batch = chunks[offset : offset + batch_size]
        vectors = embed_texts([chunk.text for chunk in batch])
        client.upsert(
            collection_name=name,
            points=[
                models.PointStruct(
                    id=start_id + offset + position,
                    vector=vector,
                    payload={
                        "text": chunk.text,
                        "source_file": chunk.source_file,
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "chunk_index": chunk.index,
                    },
                )
                for position, (chunk, vector) in enumerate(zip(batch, vectors))
            ],
        )
        stored += len(batch)

    return stored


def search(
    client: QdrantClient,
    question: str,
    name: str = DEFAULT_COLLECTION,
    *,
    top_k: int = 3,
) -> list[SearchHit]:
    """Find the chunks nearest to the question."""
    response = client.query_points(
        collection_name=name,
        query=embed_query(question),
        limit=top_k,
        with_payload=True,
    )
    hits: list[SearchHit] = []
    for point in response.points:
        payload = point.payload or {}
        hits.append(
            SearchHit(
                score=point.score,
                text=payload.get("text", ""),
                source_file=payload.get("source_file", "?"),
                page_start=int(payload.get("page_start", 0)),
                page_end=int(payload.get("page_end", 0)),
            )
        )
    return hits


def _next_id(client: QdrantClient, name: str) -> int:
    """Continue numbering so indexing a second document does not overwrite the first."""
    try:
        return client.count(collection_name=name, exact=True).count
    except Exception:
        return 0
