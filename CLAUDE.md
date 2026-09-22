# Working notes for this repo

Context an assistant needs before touching anything here. Read with `README.md` — the
README is written for a reviewer, this file is written for whoever is coding next.

## The plan this belongs to

Week 1 of a 30-day build plan at `../BUILD-PLAN.md`. Ships `rag-service` and `rag-eval`.
Week 1 closes a gap that three September 2026 ads named explicitly: RAG, chunking,
embeddings and reranking.

**A project counts as shipped only when all five hold:** runs from a clean clone
following only the README · README in English, problem in the first two lines · CI green
on GitHub runners with no API key and no network · 45-second demo video · public with
topics set.

## Environment — this cost an evening, do not rediscover it

- **Tested on 3.11 and 3.12 — that is what CI runs.** 3.10 and 3.13 are expected to work
  (every dependency declares support) but nothing has ever run them, so the README does
  not claim them. Narrowing the claim was preferred to widening the matrix: four
  interpreters on a repo whose selling point is a green badge is four chances of a red
  caused by someone else's packaging.
- **Not 3.14, and this one is a fact rather than a policy.** `onnxruntime` publishes no
  cp314 wheel for any release, so `fastembed` cannot install. Unsatisfiable, not
  misconfigured.
- Built on **3.12.14**. `brew install python@3.12` had to **compile CPython from source
  (~25 min)** — there is no bottle for this macOS release on x86_64. Budget that time if
  the venv is ever rebuilt.
- Homebrew's versioned Python formulae are **keg-only**. Use the absolute path:
  `/usr/local/opt/python@3.12/bin/python3.12`.
- Machine is **Intel macOS (x86_64)**, brew prefix `/usr/local`. arm64-only wheels are
  the recurring problem. `onnxruntime` resolves to **1.23.2** — the last release with an
  x86_64 macOS wheel, since 1.24 dropped Intel macOS entirely.
- `requirements.txt` is deliberately **not** pinned against this. Platform resolution
  handles it, and a bare `onnxruntime<1.24` would hold Linux CI back for a
  Mac-only reason. A lockfile is still owed, but **not from `pip freeze` on this Mac**: that
  pins `onnxruntime==1.23.2` for Linux too — the same mistake — while CI's first run
  resolved 1.30.0. It needs per-platform markers (e.g. `uv pip compile --universal`). It
  matters: starlette already warns that TestClient's `httpx` support is deprecated, and
  unpinned, the release that drops it turns CI red with no change to this code.
- Invoke as `.venv/bin/python …` rather than relying on an activated shell.

## Conventions

- Commits: **bare single-line subjects, no trailers, no `Co-Authored-By`.** This repo is
  portfolio-facing and the history should read as one author's.
- Commit email is the **GitHub noreply address**, set repo-local in `.git/config` — never a
  personal address. Set the same address in any new repo before its first commit.
- **Nothing private goes in this repo** — no private documents or quotes from them, and no
  names of people or organisations other than the tools used — in files, comments or
  commit messages. The history is public and permanent.
- `pwd` before any `git` command. An accidental `git init` in `$HOME` has cost an hour before.
- Credentials never in the repo. `SET_YOUR_OWN` placeholders in `.env.example`.
- Code comments and docstrings explain **why**, especially where a simpler option was
  rejected — that reasoning is the portfolio value, not the code.
- Russian for anything a user reads in the CLI; English for README and code.

## Current state

Working: page-aware PDF extraction → encoding repair → citable chunking → local
embeddings → Qdrant vector search; CLI scripts for indexing and querying; `POST /ask`
(retrieval-only) and `GET /health`; a test suite that runs with no key and no network,
enforced by a socket guard; CI on 3.11 + 3.12. `docker-compose.yml` is written and has
never been run.

Not built yet: generation (Week 3), `rag-eval` (Days 6–7).

## Defects found so far — all the same failure class

1. **Font-encoding damage.** Every Cyrillic «к» in the first test document arrived as
   «ĸ» (U+0138). 57 occurrences, zero real «к». Fixed in `app/normalize.py`, context-aware
   so bilingual documents survive, and it **reports** what it changed.
2. **CWD-relative store path.** Indexing from the repo root and querying elsewhere opened
   two different folders; the second was empty and returned nothing *without an error*.
   Fixed by anchoring to the repo in `app/store.py`.
3. **Text between chunks, below 480 characters.** The chunker could start the next chunk
   after the previous one ended; whole sentences were indexed nowhere. Fixed with a clamp
   in `split_spans`, guarded by a test built from a real failing input.
4. **A green tick against the wrong limit.** `index_pdf.py` compared chunks against 512
   tokens; the model reads 128. It reported every chunk as fitting while more than half of
   each was discarded. The check is fixed; the truncation itself deliberately is not.

🔑 **All four were silent — wrong behaviour with no error.** That is the failure class to hunt
in this project. Prefer fixing the mechanism over writing down a rule someone must remember.
Verify numbers against the running system, not against a config file: the 512 came from
`config.json` and was wrong for three days.

## The baseline is deliberately weak — do not tune it

Measured, reproducible bit-for-bit across Linux x86_64 and Intel macOS: **0.4549 /
0.4443 / 0.4434**, correct passage at **rank 2**, `max_chars=1200`. The document it was
measured on is private and cannot be published — rag-eval's corpus replaces it.

🔴 **Do not change the model, `max_chars`, or `top_k` to improve this.** The whole point of
`rag-eval` is to move one variable at a time and show the number responding. Tuning before
the measurement exists destroys the only interesting thing here.

**What is measured:** the model reads only the first 128 tokens of each chunk, about 440
characters. The passage that answers the baseline question starts at token 161 of its
chunk, so it was never embedded — the chunk ranked second on an opening paragraph that
does not answer the question. It scores 0.4443 at both 1200 and 2000 characters because
its first 128 tokens are identical either way.

The earlier diagnosis — an "intent-granularity problem, not a language problem" — is
**withdrawn**: it analysed text the model never read. WHAT-I-DID.md keeps the record.

## Design decisions already settled

- **Qdrant, not pgvector** — one container, no DB to administer, and it is what Russian
  employers name.
- **Chunk across the document, not per page.** Per-page would give exact page numbers
  free, but 4 of 6 chunks crossed a page break in real documents — per-page chunking would
  have cut two-thirds of them mid-clause. Offsets are tracked and a straddling chunk cites
  a range, «стр. 1–2».
- **`max_chars=1200`** — what `index_pdf.py` has always used, now also the library and
  preview default, so `show_chunks.py` finally previews what gets indexed. It does **not**
  fit the model: 128 tokens is ~440 characters at 3.46 chars/token, so every 1200-char
  chunk is truncated. Left alone until rag-eval measures it. (`CHUNK_MAX_CHARS` in
  `.env.example` was never read by anything and is gone; the flags are the real controls.)
- **MiniLM-L12-v2 (384 dims, 0.22 GB)** for CPU speed on Intel — as fastembed runs it, the
  quantized ONNX build `qdrant/…-onnx-Q`, reading 128 tokens. Similarity-tuned rather than
  retrieval-tuned; `e5-large` reads 512 and is the obvious upgrade to test *with the eval*.

## For `rag-eval`, Days 6–7

### Prerequisites — before any code

- 🔴 **There is no corpus.** The only document ever indexed is a private five-page file that
  cannot be published, so it cannot be the eval corpus. Day 6's first step is getting two or
  three genuine tender PDFs from `zakupki.gov.ru` into `samples/` (already git-ignored) —
  not writing code. Twenty questions written against the wrong document measure nothing.
- 🔴 **`--reset` discipline.** Day 7 re-indexes the same documents at other chunk sizes.
  Without `--reset`, `index_pdf.py` **appends** — duplicates compete with each other and
  corrupt exactly the measurement Day 7 exists to produce. Reset on every re-index, or give
  each configuration its own collection (`QDRANT_COLLECTION`, now resolved at call time).
- **The first variable is chunk size against the 128-token window** — ~440 characters fits.
  It is the one cause already measured.

### Scoring rules

- 🔴 **Do not score hit@3.** With ten chunks indexed that is "top 30%" — a metric that
  would read 90% while the system stayed useless. Score the **rank** of the correct chunk,
  or MRR.
- **Write the expected answer per question explicitly, and allow more than one acceptable
  chunk.** Two readers disagreed about which chunk answered the baseline question, and both
  readings were defensible. An eval built on one person's labelling mood measures the
  labeller, not the retriever.
- 🔴 **The questions and their anchors are Abdulrahman's to write.** An eval whose questions
  and answers were both written by an AI measures nothing and cannot be defended.
- Needs a genuinely long document. The largest tested so far is five pages; the README
  claims this handles 300-page tender packages and that claim is **currently untested**.

### Harness design, already decided

- **Question file in TOML**, read with stdlib `tomllib` — available from 3.11, which is
  exactly the CI floor, so the eval file needs no dependency.
- **Labels are verbatim text anchors, never chunk ids.** Chunk ids change the moment
  `max_chars` changes, which is Day 7's whole experiment; an id label would silently point
  at the wrong passage. Any hit containing any anchor counts. Match with whitespace and case
  collapsed, because PDF extraction breaks lines mid-sentence. Copy anchors from
  `scripts/show_chunks.py` output, not a PDF viewer, which shows the unrepaired «ĸ».
- **Black-box over HTTP:** `GET /health` first and refuse an empty index; then `POST /ask`
  with `top_k=20`, **asserting `mode == "retrieval-only"`** on every response.
- **Label errors are reported, not scored.** When the index holds ≤ 20 points, `top_k=20`
  returns all of it, so an anchor that matches nothing is a mislabel, not a retrieval
  failure. List them separately and exit non-zero — an MRR over mislabelled questions
  measures the labeller.
- Refuse to run while any field still reads `SET_YOUR_OWN`.
- `pytest.ini` with `pythonpath = .` (bare `pytest` fails without it); tests on httpx
  `MockTransport` plus the socket guard; CI on 3.11 + 3.12 only.
