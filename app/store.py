"""Storing and searching chunk vectors in Qdrant.

Two modes, one API. `open_store()` picks between them:

    QDRANT_URL unset    -> embedded, a local folder, no server and no container
    QDRANT_URL set      -> that container or remote instance

**Embedded is the default and stays the default.** It needs no Docker, which means a
reviewer can clone this repo and get a working system with nothing but Python. The
container is the upgrade path, not the entry fee.

⚠️ Embedded mode takes an exclusive lock on its folder, so only one process can use
it at a time. Indexing and asking by hand is fine; running the API *and* the CLI is
not. That is the concrete reason to reach for `docker-compose.yml` — not performance,
not scale, just the second process.

⚠️ The two modes are separate stores. Indexing into the folder puts nothing in the
container. Switching `QDRANT_URL` and finding an empty collection is expected, not a
bug — which is why `GET /health` reports which mode it is in and how many points it
can see.

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
FALLBACK_COLLECTION = "tenders"

# Kept for callers that import it, but it is a SNAPSHOT taken at import time. Anything
# that needs the live value must call `current_collection()` instead — see below.
DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", FALLBACK_COLLECTION)


def current_collection(name: str | None = None) -> str:
    """The collection to use, resolved when it is asked for rather than at import.

    🔑 THIS EXISTS BECAUSE THE MODULE USED TO CONTRADICT ITS OWN DOCSTRING. `open_store`
    re-reads QDRANT_PATH and QDRANT_URL at call time, and says in writing why: a
    module-level `os.getenv` freezes the value at first import. QDRANT_COLLECTION was
    frozen exactly that way one line above that warning, so setting it after import
    changed nothing and said nothing. /health and the queries still agreed with each
    other — both kept using `tenders` — so nothing looked wrong.

    Who that actually bites: anything that sets the variable inside a running process.
    Tests do; an eval harness that indexes into a separate collection per experiment
    would. A shell `export` does not — it happens before the process starts, so the
    import already sees it — and nothing in this repo loads `.env` at all.
    """
    return name or os.getenv("QDRANT_COLLECTION") or FALLBACK_COLLECTION


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


def describe_mode(path: str | None = None, url: str | None = None) -> str:
    """Which store `open_store` would open, as a string fit for a log line or /health.

    Separate from `open_store` so the answer can be reported without taking the
    embedded mode's exclusive lock.
    """
    url = url or os.getenv("QDRANT_URL")
    if url:
        return f"container ({url})"
    return f"embedded ({path or os.getenv('QDRANT_PATH') or DEFAULT_PATH})"


def open_store(path: str | None = None, url: str | None = None) -> QdrantClient:
    """Open the vector store: the container if a URL is configured, else the folder.

    Environment is read here rather than at import time so that a test — or anything
    that sets the variable after this module loads — actually takes effect. Module-level
    `os.getenv` freezes the value at the first import, which is the kind of thing that
    works until it silently does not.

    Called with no arguments, this behaves exactly as it did before the container
    existed, so the CLI scripts did not have to change.
    """
    url = url or os.getenv("QDRANT_URL")
    if url:
        return QdrantClient(url=url)
    return QdrantClient(path=path or os.getenv("QDRANT_PATH") or DEFAULT_PATH)


def ensure_collection(
    client: QdrantClient,
    name: str | None = None,
    *,
    reset: bool = False,
) -> None:
    """Create the collection if missing. With `reset`, drop and rebuild it.

    Cosine distance, because these vectors are normalised and only direction carries
    meaning — two passages about penalties should match regardless of length.
    """
    name = current_collection(name)
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
    name: str | None = None,
    *,
    batch_size: int = 32,
) -> int:
    """Embed chunks and store them with the payload needed to cite them later."""
    if not chunks:
        return 0

    name = current_collection(name)
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
    name: str | None = None,
    *,
    top_k: int = 3,
) -> list[SearchHit]:
    """Find the chunks nearest to the question."""
    response = client.query_points(
        collection_name=current_collection(name),
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
