"""Shared fixtures: a fake embedder, an in-memory store, and a network blocker.

The hard requirement these exist to satisfy: **the suite must pass with no API key and
no network access.** That is not a preference — it is what makes CI meaningful. A test
suite that quietly reaches the internet is a suite that goes red when someone else's
service has a bad day, and green for reasons it cannot explain.

Three things make that true here:

1. `fake_embedder` replaces the real model. Loading MiniLM would download 0.22 GB.
2. `store` is `QdrantClient(":memory:")` — real vector search, no server, no disk.
3. `_no_network` blocks outbound TCP, so the rule is *enforced* rather than trusted.

🔑 THE PATCH TARGET IS `app.store`, NOT `app.embed`. `app/store.py` does
`from app.embed import embed_query, embed_texts`, which binds those functions into its
own namespace at import time. Patching `app.embed.embed_query` afterwards rebinds the
name in `app.embed` and leaves `app.store` still pointing at the original — the patch
applies, the test passes, and the real model downloads anyway. Verified explicitly:
`app.store.embed_query is app.embed.embed_query` is True before patching.
"""

from __future__ import annotations

import hashlib
import socket
import struct

import pytest
from qdrant_client import QdrantClient

from app.embed import VECTOR_SIZE

# --------------------------------------------------------------------------- network


class NetworkAccessAttempted(RuntimeError):
    """Raised instead of opening a socket, so the failure names its own cause."""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly on any outbound TCP connection.

    Scoped to `socket.socket.connect` rather than the whole socket module: the point is
    to catch a model download or an API call, not to forbid the loopback machinery that
    a local test harness may legitimately use. Connections to localhost are allowed
    through for that reason — nothing on 127.0.0.1 can be a hidden dependency on an
    external service.

    If this fixture ever has to be deleted, say so in the README rather than leaving it
    in a weakened state: "no network" would then be documentation backed by CI running
    on a sandboxed runner, which is weaker than a local assertion and should not be
    described as if it were the same thing.
    """
    real_connect = socket.socket.connect

    def guard(self: socket.socket, address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) and address else None
        if host in {"127.0.0.1", "::1", "localhost"}:
            return real_connect(self, address, *args, **kwargs)
        raise NetworkAccessAttempted(
            f"The tests must run with no network. Something tried to reach {address!r}. "
            "If this is a model download, the embedder is not mocked — patch "
            "app.store.embed_texts / app.store.embed_query, not app.embed.*"
        )

    monkeypatch.setattr(socket.socket, "connect", guard)


# -------------------------------------------------------------------------- embedder


def fake_vector(text: str) -> list[float]:
    """A deterministic stand-in for a real embedding.

    Requirements are narrow: same text must give the same vector, different text must
    give a different one, and the width must match VECTOR_SIZE or Qdrant rejects it.
    It carries no semantics, so these tests can prove the plumbing — store, retrieve,
    cite, rank — and say nothing about retrieval quality. Quality is `rag-eval`'s job,
    and pretending a hash could measure it would be worse than not measuring at all.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Stretch the 32-byte digest to VECTOR_SIZE floats in [-1, 1).
    raw = (digest * (VECTOR_SIZE // len(digest) + 1))[:VECTOR_SIZE]
    return [(byte - 128) / 128.0 for byte in struct.unpack(f"{VECTOR_SIZE}B", raw)]


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the real model out everywhere `app.store` will look for it."""
    monkeypatch.setattr("app.store.embed_texts", lambda texts: [fake_vector(t) for t in texts])
    monkeypatch.setattr("app.store.embed_query", lambda text: fake_vector(text))


# ----------------------------------------------------------------------------- store


@pytest.fixture
def store() -> QdrantClient:
    """A real Qdrant, held in memory. Same API as the folder and the container."""
    client = QdrantClient(":memory:")
    try:
        yield client
    finally:
        client.close()
