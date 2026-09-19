# What I did, Day 3–5

**Read in this order:** this file → `tests/` → the implementation. The tests are the
best summary of what the code thinks it is for; the implementation is the least
surprising part once you have those.

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
CI is committed but has never run, because there is no remote. Both are stated as such in
the README rather than implied to work.
