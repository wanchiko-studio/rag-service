"""Turning text into vectors, locally.

Runs `fastembed`, which executes the model through ONNX rather than PyTorch. That
matters here for one concrete reason: the target machine is an Intel Mac with no GPU,
so a 2 GB model would be slow enough to make iteration painful, and PyTorch would add
a quarter of a gigabyte of dependency for no benefit.

MODEL CHOICE, and the honest version of it:

    paraphrase-multilingual-MiniLM-L12-v2   384 dims, 0.22 GB, reads 128 tokens (measured)
    paraphrase-multilingual-mpnet-base-v2   768 dims, 1.00 GB
    intfloat/multilingual-e5-large         1024 dims, 2.24 GB, 512-token window

Only the first row is measured here; the other two are published figures.

What actually runs is fastembed's quantized ONNX build of MiniLM,
`qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q`, not the sentence-transformers
checkpoint itself. Worth knowing before comparing scores against another library.

MiniLM is chosen for size and speed on CPU. It is tuned for sentence *similarity*
rather than *retrieval*, so e5-large would almost certainly score better. That is a
deliberate starting point, not a claim: `rag-eval` measures retrieval accuracy, so the
model can be swapped later and the change in the score shown rather than asserted.

🔑 THE CEILING IS 128 TOKENS, NOT 512, AND IT IS NOT ADVISORY. The model's config says
512, but that is the size of its position table — feed it 512+ tokens untruncated and it
crashes rather than truncating. What decides how much text reaches the vector is the
tokenizer, and it cuts at 128 with no error and no warning. Measured, not read off a
config: two texts that share their first 146 tokens and differ after that embed to
cosine 1.000000. Everything past the cut is discarded.

On this corpus Russian runs 3.46 characters per token, so the cut falls near 440
characters, and a 1200-character chunk loses more than half its text. `count_tokens`
counts with truncation switched off, agrees token-for-token with fastembed's own
tokenizer, and exists so that this stays visible instead of silent.
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
VECTOR_SIZE = 384
# The tokenizer's truncation length as fastembed runs this model — measured, see above.
# Not the 512 in the model's config.json, which is the position table and cannot be
# reached through fastembed at all.
MAX_TOKENS = 128


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
