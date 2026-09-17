"""Turning text into vectors, locally.

Runs `fastembed`, which executes the model through ONNX rather than PyTorch. That
matters here for one concrete reason: the target machine is an Intel Mac with no GPU,
so a 2 GB model would be slow enough to make iteration painful, and PyTorch would add
a quarter of a gigabyte of dependency for no benefit.

MODEL CHOICE, and the honest version of it:

    paraphrase-multilingual-MiniLM-L12-v2   384 dims, 0.22 GB, 512-token window
    paraphrase-multilingual-mpnet-base-v2   768 dims, 1.00 GB, 384-token window
    intfloat/multilingual-e5-large         1024 dims, 2.24 GB, 512-token window

MiniLM is chosen for size and speed on CPU. It is tuned for sentence *similarity*
rather than *retrieval*, so e5-large would almost certainly score better. That is a
deliberate starting point, not a claim: `rag-eval` measures retrieval accuracy, so the
model can be swapped later and the change in the score shown rather than asserted.

🔑 THE 512-TOKEN CEILING IS NOT ADVISORY. Anything longer is silently truncated — no
error, no warning, the tail simply never reaches the vector. On this corpus Russian
runs about 3.45 characters per token, so a 2000-character chunk reaches ~630 tokens
and loses its last fifth. `count_tokens` exists so that stays visible.
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
VECTOR_SIZE = 384
MAX_TOKENS = 512


@lru_cache(maxsize=1)
def _model():
    """Load the model once. First call downloads ~0.22 GB, then it is cached on disk."""
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=MODEL_NAME)


@lru_cache(maxsize=1)
def _tokenizer():
    """The model's own tokenizer, with truncation switched off so counts are honest."""
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(hf_hub_download(MODEL_NAME, "tokenizer.json"))
    tok.no_truncation()
    tok.no_padding()
    return tok


def count_tokens(text: str) -> int:
    """How many tokens this model will see. Above MAX_TOKENS the rest is discarded."""
    return len(_tokenizer().encode(text).ids)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of passages."""
    if not texts:
        return []
    return [vector.tolist() for vector in _model().embed(texts)]


def embed_query(text: str) -> list[float]:
    """Embed a single question.

    Separate from `embed_texts` on purpose. This model needs no query prefix, but
    retrieval-tuned models such as e5 require «query: » and «passage: » markers, and
    when the model is swapped the difference belongs in one place, not scattered.
    """
    return embed_texts([text])[0]
