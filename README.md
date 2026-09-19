# rag-service

Finds the clauses in a messy Russian tender document that answer a question, instead of feeding a model three hundred pages.
Every passage comes back with the file and page it came from, and retrieval accuracy is measured rather than claimed.

**Retrieval only, on purpose.** Nothing here writes an answer yet — `POST /ask` returns the
ranked passages and their scores. Generation needs a model, a model needs a key or a local
runtime, and neither exists in this repo today. An endpoint that cannot fabricate an answer
is a smaller promise than one that might.

---

## Why this exists

A tender package from `zakupki.gov.ru` runs to hundreds of pages. You cannot paste it into a
model, and a model asked "what is the penalty for late delivery?" will either refuse or invent
an answer. Keyword search does not help either: the document says «пеня», the question says
«штраф», and `Ctrl+F` finds nothing.

So the service does the obvious thing instead. It cuts the document into labelled pieces
and finds the two or three that actually answer the question — the short list a model
would eventually be handed, and for now the short list a person reads directly.

The same engine works on any PDF with a text layer — point it at a research paper and it
returns cited passages in exactly the same way.

## How it works

| Step | What happens |
|---|---|
| **Extract** | `pdfplumber` pulls the text layer, page by page. Scanned files have no text layer, and that case is detected and reported rather than passed on as an empty string. |
| **Chunk** | Split on paragraph boundaries with an overlap, so a price never lands in a different piece from its currency. Each piece keeps `source_file` and `page`. |
| **Embed** | Each piece becomes a vector, so «пеня» and «штраф» land near each other. |
| **Store** | Vectors go into Qdrant. By default that is embedded mode — a local folder, no server and no Docker — so a clone runs with nothing but Python. `docker-compose.yml` is there when one process is not enough. |
| **Ask** | The question is embedded the same way and the nearest pieces come back, ranked, scored and cited. No model is called: see the note at the top. |

## Why the citations matter

A result is only trustworthy if you can check it. Every passage carries the file name and
page number it came from, so a wrong one is visible in seconds instead of being discovered
later. Retrieval returns a paragraph, not a sentence — enough to go and verify, not enough
to quote without reading.

## Why the score matters

If retrieval misses the right paragraph, anything built on top of it will answer confidently
from the wrong one. That failure is invisible unless it is measured, so a companion repo
(`rag-eval`) runs a fixed set of questions with known answers and reports **where the correct
chunk ranked** — not merely whether it appeared. Changing the chunk size and re-running shows
whether the number moved.

Rank rather than hit@3 for a concrete reason: with ten chunks indexed, "in the top three"
means "in the top thirty percent", which would read as 90% success while the system stayed
useless.

That measurement is the point of this project. Building a retrieval pipeline is a weekend;
knowing how often it is right is the part that is usually skipped.

## Status

Built in the open, one step per day. Honest state as of the last commit:

- [x] Repository, README, project hygiene
- [x] PDF text extraction with page numbers preserved
- [x] Font-encoding repair, measured rather than assumed — see below
- [x] Paragraph chunking carrying `source_file` and `page`, boundary-aligned at both ends
- [x] Local embeddings and vector search in Qdrant, with a measured baseline — see below
- [x] `POST /ask` returning ranked passages with citations and scores
- [x] Tests that pass with no API key and no network, enforced by a socket guard
- [x] CI on GitHub runners, Python 3.11 and 3.12
- [x] Qdrant in a container — `docker-compose.yml` written, **never run** (see below)
- [ ] Generation: a model that writes an answer from the retrieved passages
- [ ] `rag-eval`: 20 questions, known answers, a printed retrieval score

## The first baseline is weak, and that is recorded on purpose

Retrieval runs. It is not yet good, and the numbers are here rather than hidden.

Asked a Russian question against a five-page bilingual
document split into ten chunks, the passage that answers it
came back **second**. The three scores were **0.4549 / 0.4443 / 0.4434**: a spread of
about one hundredth across the entire top three. A retriever that cannot separate a
right answer from a wrong one by more than that is not ranking, it is guessing politely.

What beat it was not nonsense, which is its own kind of problem. First place went to the
closing recap four pages later, which repeats the advice without ever saying
what to say. Third went to a related passage — right subject, wrong moment.
The model is matching the topic and is blind to the difference between a
summary and the passage that actually answers it.

Worth stating plainly: with ten chunks indexed, "in the top three" means "in the top
thirty percent". That is a low bar, and `rag-eval` needs a harder one — the rank of the
correct chunk, not merely whether it showed up.

Measured on Python 3.12.14, `fastembed==0.8.0`, `onnxruntime==1.23.2`, `max_chars=1200`,
macOS x86_64. Every chunk fits the model window whole — 387 tokens at the largest against
a limit of 512 — so none of this is a truncation artefact.

Three identified causes, in the order they are worth attacking:

1. **The model is tuned for sentence similarity, not retrieval.** `intfloat/multilingual-e5-large`
   is built for this task; MiniLM was chosen for CPU speed on an Intel machine.
2. **Cross-lingual retrieval is the hard case** — a Russian question against largely
   English passages — and this model is mediocre at it.
3. **1200-character chunks dilute the signal.** One relevant sentence surrounded by
   1100 characters of unrelated text drags the vector off-topic.

`fastembed` 0.8.0 uses mean pooling for this model where older versions used the CLS
embedding, and announces it at load time. That is a fourth lever to test, not an
explanation of the above.

None of these are guesses to act on blindly. `rag-eval` exists to change one variable
at a time and show whether the number moved, which is the entire point of the project.

## The source text is damaged, and that had to be fixed first

The first real document this was pointed at had **every** Cyrillic «к» replaced by «ĸ»
(U+0138, the Latin letter kra) — 57 occurrences, zero genuine «к». The PDF's font
encoding was wrong and the extractor faithfully reported what the font claimed.

That is not a cosmetic problem. «обработĸа» and «обработка» are different strings, so
they embed to different vectors, and a search for one will never find the other. Left
in place it would have meant rebuilding the entire index later.

The obvious fix — a Latin→Cyrillic lookup table — is the wrong one: it would convert
every Latin `a`, `e`, `o`, `c` and `p` and destroy the English half of a bilingual
document. So repair is context-aware. Characters that are never legitimate in either
language are always fixed; Latin homoglyphs are only fixed inside a word that is
already mostly Cyrillic.

And it reports rather than assumes. Every extraction returns a count of what was
repaired and a list of any suspicious characters still present, so a new document with
a new kind of damage shows up instead of quietly poisoning the index.

## Quick start

Verified from a clean clone on 19 September 2026, following only these instructions,
against a PDF the author had never indexed before.

🔑 **Python 3.11 or 3.12** — those are the versions CI runs, so those are the versions
claimed. 3.10 and 3.13 should work and have not been tried.

**Not 3.14.** `fastembed` needs `onnxruntime`, and no onnxruntime release publishes a
cp314 wheel, so the install is unsatisfiable rather than merely awkward. On Intel macOS
the ceiling is lower still — onnxruntime stopped shipping x86_64 macOS wheels after
**1.23.2**, which is therefore what pip resolves to there. Nothing is pinned against it,
because the constraint belongs to that machine rather than to the project; this note is
the record.

```bash
git clone <repo-url> && cd rag-service
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Point this at any PDF you have. It needs a real text layer — see Deliberate limits.
python scripts/index_pdf.py path/to/your-document.pdf --reset
python scripts/ask.py "ваш вопрос"
```

The first index downloads the embedding model (~0.22 GB) and caches it on disk. **No API
key is required at any point** — embedding and search both run locally.

`cp .env.example .env` is optional today. Nothing in the repo reads `.env` yet; it
documents the variables the service understands.

### The HTTP API

```bash
uvicorn app.api:app --reload

curl -s localhost:8000/health
curl -s localhost:8000/ask -H 'content-type: application/json' \
     -d '{"question": "какая пеня за просрочку поставки?", "top_k": 3}'
```

Interactive docs at `localhost:8000/docs`. `/health` reports which store it opened and how
many passages are in it — check that first when `/ask` returns nothing, because an empty
index and bad retrieval look identical from the outside.

⚠️ **In embedded mode the API and the CLI cannot run at the same time.** The store takes an
exclusive lock on its folder, so `scripts/ask.py` will fail while `uvicorn` is up, and vice
versa. Stop one, or run the container.

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

32 tests, about a second, **no API key and no network**. That is enforced rather than
promised: `tests/conftest.py` replaces the embedding model with a deterministic fake and
blocks outbound TCP, so a test that tries to reach the internet fails and says why.
Loopback stays open, because the test client needs it.

Installing the dependencies obviously needs the network. Running the tests does not.

### Qdrant in a container

```bash
docker compose up -d
export QDRANT_URL=http://localhost:6333
python scripts/index_pdf.py path/to/your-document.pdf --reset
```

🔴 **This path has never been run.** The machine this was built on has no Docker installed.
The image tag is matched to the client version on purpose (`qdrant-client==1.19.1` ↔
`qdrant/qdrant:v1.19.1`) and CI parses the file, but parsing is not starting. Treat it as a
documented intention until someone runs it.

Note that the two stores are separate: whatever you indexed into the folder is not in the
container. `/health` tells you which one you are talking to.

## Deliberate limits

- **No generation.** `POST /ask` returns passages, not prose. See the note at the top.
- **Scanned PDFs are not supported.** No text layer means nothing to extract; OCR is out of scope.
- **Citations are chunk-level**, so they point at a passage on a page, not at one sentence.
- **Russian source material is the target.** The chunking assumes Russian paragraph and
  sentence conventions, which is where the accuracy work has gone.
- **The largest document ever tested is five pages.** The opening paragraph talks about
  three-hundred-page tender packages because that is the problem being aimed at, not
  because that has been demonstrated. Nothing in the design should care — chunking is
  linear and Qdrant is built for far more — but "should not care" is a prediction, and
  this file tries to keep predictions and measurements apart.
- **The container is unverified.** Written, parsed by CI, never started.

## Licence

MIT.
