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
  Mac-only reason. A lockfile from `pip freeze` is the Day 5 answer.
- Invoke as `.venv/bin/python …` rather than relying on an activated shell.

## Conventions

- Commits: **bare single-line subjects, no trailers, no `Co-Authored-By`.** This repo is
  portfolio-facing and the history should read as one author's.
- `pwd` before any `git` command. An accidental `git init` in `$HOME` has cost an hour before.
- Credentials never in the repo. `SET_YOUR_OWN` placeholders in `.env.example`.
- Code comments and docstrings explain **why**, especially where a simpler option was
  rejected — that reasoning is the portfolio value, not the code.
- Russian for anything a user reads in the CLI; English for README and code.

## Current state

Day 1 and Day 2 both shipped, four commits, tree clean, nothing pushed.

Working: page-aware PDF extraction → encoding repair → citable chunking → local
embeddings → Qdrant vector search, with CLI scripts for indexing and querying.

Not built yet: `POST /ask`, Qdrant in a container, CI, `rag-eval`.

## Two defects already found and fixed — both the same failure class

1. **Font-encoding damage.** Every Cyrillic «к» in the first test document arrived as
   «ĸ» (U+0138). 57 occurrences, zero real «к». Fixed in `app/normalize.py`, context-aware
   so bilingual documents survive, and it **reports** what it changed.
2. **CWD-relative store path.** Indexing from the repo root and querying elsewhere opened
   two different folders; the second was empty and returned nothing *without an error*.
   Fixed by anchoring to the repo in `app/store.py`.

🔑 **Both were silent — wrong behaviour with no error.** That is the failure class to hunt
in this project. Prefer fixing the mechanism over writing down a rule someone must remember.

## The baseline is deliberately weak — do not tune it

Measured, reproducible bit-for-bit across Linux x86_64 and Intel macOS: **0.4549 /
0.4443 / 0.4434**, correct passage at **rank 2**.

🔴 **Do not change the model, `max_chars`, or `top_k` to improve this.** The whole point of
`rag-eval` is to move one variable at a time and show the number responding. Tuning before
the measurement exists destroys the only interesting thing here.

**The real diagnosis:** all three hits share the question's topic, so topical retrieval works.
The model cannot tell a summary from the passage that answers the question. This is an
intent-granularity problem, not a language problem.

## Design decisions already settled

- **Qdrant, not pgvector** — one container, no DB to administer, and it is what Russian
  employers name.
- **Chunk across the document, not per page.** Per-page would give exact page numbers
  free, but 4 of 6 chunks crossed a page break in real documents — per-page chunking would
  have cut two-thirds of them mid-clause. Offsets are tracked and a straddling chunk cites
  a range, «стр. 1–2».
- **`CHUNK_MAX_CHARS=1200`, not 2000.** The model truncates silently at 512 tokens.
  Measured: 2000 chars → up to 627 tokens → 4 of 6 chunks losing their tail. Russian runs
  ~3.45 chars/token here.
- **MiniLM-L12-v2 (384 dims, 0.22 GB)** for CPU speed on Intel. It is similarity-tuned
  rather than retrieval-tuned; `e5-large` is the obvious upgrade to test *with the eval*.

## For `rag-eval`, Days 6–7

- 🔴 **Do not score hit@3.** With ten chunks indexed that is "top 30%" — a metric that
  would read 90% while the system stayed useless. Score the **rank** of the correct chunk,
  or MRR.
- **Write the expected answer per question explicitly, and allow more than one acceptable
  chunk.** Two readers disagreed about which chunk answered the question, and both
  readings were defensible. An eval built on one person's labelling mood measures the
  labeller, not the retriever.
- Needs a genuinely long document. The largest tested so far is five pages; the README
  claims this handles 300-page tender packages and that claim is **currently untested**.
  Any PDF from `zakupki.gov.ru` into `samples/` — already git-ignored.
