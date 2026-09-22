# What I did

**Read in this order:** this file → `tests/` → the implementation. The tests are the
best summary of what the code thinks it is for; the implementation is the least
surprising part once you have those.

---

## Day 5 — reviewing six files an agent sandbox changed

Six files were changed by an agent sandbox on 20 Sept and never read before this review.
Every claim was checked against the old code, the running model and the real document —
not against the code comments. Three held up. One rested on a false premise.

### Why each of these lines is here

**The clamp in `split_spans`.** The chunker overlaps each chunk with the last, then nudges
the start forward to a word boundary so no passage opens mid-word. Below 480 characters
per chunk, that nudge could jump past the end of the previous chunk, and whatever sat in
the gap was indexed nowhere — no error. On 16 000 generated documents the old code lost
real text in 88 % of them; the worst lost 204 characters of words. `min(…, end)` caps the
nudge so a chunk can never start after the last one finished. It matters now, because
fitting the model's 128-token window takes chunks of about 440 characters — under the
threshold. The test is built on a real 213-character failure where the old code dropped
the sentence «Договор оплата заказчик.», and it fails on the old code.

**The 1200 default, and `MAX_TOKENS = 128`.** The reason originally given was wrong: it
said 1200 avoids the model's 512-token cutoff. The cutoff is 128 — I gave the model two
texts identical for their first 146 tokens and different after, and got identical
vectors. 1200 is still the right default, for a different reason: the indexing script
already used 1200 while the preview tool used 2000, so the preview showed chunks the index
never had. Chunk size itself stays at 1200 because it is the first thing rag-eval
measures. `MAX_TOKENS` went from 512 to 128, so the indexer now warns that every chunk is
truncated — which is true. It used to print a green tick.

**`current_collection()`.** The store re-read the storage path and URL on every call but
froze the collection name at import, so setting `QDRANT_COLLECTION` inside a running
process — a test, or an eval switching collections — did nothing and said nothing. It is
now read when used, like the others, and `/health` resolves it once, so the name it
reports is the one it counts and the one `/ask` searches. Honest caveat: `/health` and
`/ask` already agreed before — both were frozen together — so this fixes a setting being
ignored, not a mismatch between them.

**The chunk settings removed from `.env.example`.** It listed chunk size, overlap and
top_k as settings. Nothing ever read them, and nothing loads `.env` at all. Someone
varying chunk size for the eval would have edited the file, seen an unchanged score, and
concluded chunk size does not matter. It now names the real controls, which are
command-line flags. It also corrects the overlap: the file said 500, but the code caps
overlap at a quarter of the chunk, so at 1200 it is 300.

### Withdrawn: the Day 2 diagnosis

**What it said** (README and CLAUDE.md, 18–21 Sept): retrieval found the right topic but
could not tell a summary from the passage that actually answered the question — "an
intent-granularity problem, not a language problem".

**Why it is withdrawn:** the model never read the passage it was said to misjudge.

- The model reads the first 128 tokens of each chunk. The answering passage starts at
  token 161 of its chunk, and the answer itself at token 249. The model's whole view of
  that chunk was its first 405 characters — an opening paragraph that does not address
  the question.
- The chunk scores exactly 0.4443 at both 1200 and 2000 characters: the same first 128
  tokens, so the same vector.
- Two texts that share their first 146 tokens and differ after embed to cosine 1.000000.

**What it does not change:** the scores. 0.4549 / 0.4443 / 0.4434 reproduces exactly,
through the real CLI and recomputed in memory. Only the explanation was wrong.

**How it was missed:** `index_pdf.py` compared chunks against 512, taken from the model's
`config.json` — where 512 is the position table, not the length the tokenizer lets
through — and printed a green tick. The README's "none of this is a truncation artefact"
was written from that tick. Nobody checked 512 against the running model until the
sandbox repeated it in a comment and review was asked for.

### Where I was unsure

1. **At 2000 characters the answering chunk ranks first instead of second.** One question,
   and both sizes truncate, so it is recorded rather than acted on. rag-eval decides.
2. **Truncation is proven; that fixing it fixes the ranking is not.** The README says "the
   measured reason", not "the reason", for that reason.
3. **The sandbox's own test only proves a lost paragraph break.** Kept for its sweep across
   eight sizes; the new test beside it is the one that proves words go missing.

---

## Day 3–5 — container, API, tests, CI

Seven commits: `CLAUDE.md` · container + configurable store · `POST /ask` · tests · CI ·
README corrections · this file.

---

## Decisions, and why

| Decision | Why |
|---|---|
| **`mode: "retrieval-only"` in the response** | You asked for no `answer` field. A discriminator is what makes generation *additive* later — a client branches on `mode` instead of sniffing for a missing key, so Week 3 changes a value rather than a contract. |
| **Embedded stays default; container is opt-in** | A reviewer with no Docker can still run the whole thing. The container is the upgrade, not the entry fee. |
| **Named Docker volume, not a host mount** | A host mount would drop a new directory into the repo and need a `.gitignore` entry, which I was told not to touch. |
| **`describe_mode()` split from `open_store()`** | `/health` can report which store it would open without taking embedded mode's exclusive lock. |
| **Env read *inside* `open_store()`, not at import** | Module-level `os.getenv` freezes the value at first import — works until a test or a late `export` silently does not. |
| **`pytest.ini` with `pythonpath = .`** | Bare `pytest` failed with `No module named 'app'` while `python -m pytest` worked. The README would have said `pytest`, a reviewer would have run it, and a healthy repo would have looked broken. Fixed the mechanism rather than documenting the workaround. |
| **CI on 3.11 + 3.12 only, and the claim narrowed to match** | Your point, and it was right. `CLAUDE.md` and the README now say what is tested instead of what is hoped. |
| **CI parses `docker-compose.yml`** | The one check my machine cannot do. Parsing is not running, and the README says so. |
| **Fake embedder is a hash** | Deterministic and fast, and deliberately carries no semantics, so no test can accidentally imply something about retrieval quality. That is `rag-eval`'s job. |
| **`TestClient` not used as a context manager** | Entering it runs the app lifespan, which opens the *real* store and takes the lock on your actual index. |
| **Empty results → 200, not 404** | "Nothing was close enough" is an answer. `/health`'s point count distinguishes it from "you are querying an empty store". |

**The socket guard is the one I'd defend hardest.** `tests/conftest.py` blocks outbound TCP,
so "no network" is enforced rather than promised. I probed it both ways: a connection to
`huggingface.co` raises, loopback still works. It did not need narrowing or dropping.

---

## Where I was unsure

1. **The model cache weakens the guard locally.** If someone forgets to mock the embedder,
   the model loads from `~/.cache` and the test passes slowly instead of failing. On a cold
   CI runner it fails loudly. So the guard is strongest exactly where it matters — but it is
   not the local tripwire I first assumed.
2. **Loopback is allowed through.** A real service on `127.0.0.1` could be a hidden
   dependency and the guard would not catch it. Blocking loopback breaks `TestClient`. I
   chose the permissive side; it is a judgement call, not an obvious right answer.
3. **`_client` is a module global in `app/api.py`.** Justified by embedded mode allowing
   only one store per process, but it means `dependency_overrides` is the only reason tests
   can avoid touching the real index. A cleaner shape exists.
4. **32 tests may be more than a 40-minute review wants.** `test_api.py` and `test_store.py`
   carry the contract; `test_normalize.py` and `test_chunking.py` are regression guards for
   bugs already fixed. Skim the last two.
5. **Whether this file belongs in a portfolio repo.** It is its own commit so you can drop it
   with one `git revert`.

---

## What I think is wrong in the existing code

1. **`.env.example` had `QDRANT_PATH=qdrant_storage` — a relative path.** That is the exact
   CWD bug fixed on Day 2, waiting to come back the moment anything loads `.env`. Latent,
   not live (see 2). Commented out, with the trap explained.
2. **Nothing reads `.env` at all.** There is no `python-dotenv`. `.env.example` documents
   variables that only take effect if you `export` them yourself. Not wrong exactly, but the
   file reads like it is wired up and it is not. README now says so.
3. **`README` claimed `rag-eval` would score "how often the correct chunk reached the top
   three".** That directly contradicts `CLAUDE.md`, which forbids hit@3 and requires rank or
   MRR — and the README is the one a reviewer reads. Corrected to rank.
4. **`store._next_id()` derives the next id from `count()`.** Delete any points and the
   counter goes backwards, so the next index silently overwrites existing rows. No delete
   path exists today, so it cannot fire — but it is the same silent-wrongness failure class
   as the other two, and it will fire the first time per-document re-indexing is added.
   Left alone: fixing it properly means a real id strategy, which is not tonight's job.
5. **Indexing the same PDF twice duplicates it.** `--reset` is the only deduplication.
   Defensible for now; worth a decision before `rag-eval` starts re-indexing in a loop.

---

## Verified, and not

**Verified:** clean clone into `/tmp`, fresh venv, README followed literally, indexing a PDF
generated for the purpose that had never been indexed before — plus `/health`, `/ask`, and
`pytest` from that same clone. The API returns the identical baseline the CLI does
(`0.4549 / 0.4443 / 0.4434` on the original document), so the HTTP path and the CLI path
agree rather than merely both appearing to work.

**Not verified:** `docker-compose.yml` has never been started — no Docker on this machine.
The README says so rather than implying it works.

**CI, since:** when this was written there was no remote, so CI had never run. Its first
run came when the repo went public on Day 5: green on 3.11 and 3.12, 35 tests each with no
key and no network, and the compose file parsed on both.
