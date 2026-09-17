# rag-service

Answers questions about messy Russian tender documents by retrieving the relevant clauses instead of feeding a model three hundred pages.
Every answer cites the file and page it came from, and retrieval accuracy is measured rather than claimed.

---

## Why this exists

A tender package from `zakupki.gov.ru` runs to hundreds of pages. You cannot paste it into a
model, and a model asked "what is the penalty for late delivery?" will either refuse or invent
an answer. Keyword search does not help either: the document says «пеня», the question says
«штраф», and `Ctrl+F` finds nothing.

So the service does the obvious thing instead. It cuts the document into labelled pieces,
finds the two or three that actually answer the question, and hands only those to the model.

The same engine works on any set of PDFs — point it at a folder of research papers and it
answers with citations in exactly the same way.

## How it works

| Step | What happens |
|---|---|
| **Extract** | `pdfplumber` pulls the text layer, page by page. Scanned files have no text layer, and that case is detected and reported rather than passed on as an empty string. |
| **Chunk** | Split on paragraph boundaries with an overlap, so a price never lands in a different piece from its currency. Each piece keeps `source_file` and `page`. |
| **Embed** | Each piece becomes a vector, so «пеня» and «штраф» land near each other. |
| **Store** | Vectors go into Qdrant, running locally in Docker. |
| **Ask** | The question is embedded the same way, the nearest pieces are retrieved, and the model answers from those — returning the answer *and* the chunks it used. |

## Why the citations matter

The answer is only trustworthy if you can check it. Every response carries the file name and
page number of each chunk it used, so a wrong answer is visible in seconds instead of being
discovered later. The retrieval returns a paragraph, not a sentence — enough to go and verify,
not enough to quote without reading.

## Why the score matters

If retrieval misses the right paragraph, the model will answer confidently from the wrong one.
That failure is invisible unless it is measured, so a companion repo (`rag-eval`) runs a fixed
set of questions with known answers and prints how often the correct chunk reached the top
three. Changing the chunk size and re-running shows whether the number moved.

That measurement is the point of this project. Building a retrieval pipeline is a weekend;
knowing how often it is right is the part that is usually skipped.

## Status

Built in the open, one step per day. Honest state as of the last commit:

- [x] Repository, README, project hygiene
- [x] PDF text extraction with page numbers preserved
- [x] Font-encoding repair, measured rather than assumed — see below
- [x] Paragraph chunking carrying `source_file` and `page`, boundary-aligned at both ends
- [x] Local embeddings and vector search in Qdrant, with a measured baseline — see below
- [ ] Qdrant in a container instead of embedded mode
- [ ] `POST /ask` returning an answer plus the chunks used
- [ ] CI running green with no API key and no network access
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

Indexing and search run today. The HTTP service does not exist yet — see Status.

🔑 **Python 3.10–3.13.** Not 3.14: `fastembed` needs `onnxruntime`, and no onnxruntime
release publishes a cp314 wheel. On Intel macOS the ceiling is lower still — onnxruntime
stopped shipping x86_64 macOS wheels after **1.23.2**, which is therefore what pip
resolves to here. Nothing is pinned, because the constraint belongs to the machine rather
than to the project; this note is the record.

```bash
git clone <repo-url> && cd rag-service
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/index_pdf.py path/to/document.pdf --reset
python scripts/ask.py "ваш вопрос"
```

The first index downloads the embedding model (~0.22 GB) and caches it on disk. No API
key is required — embedding and search both run locally, which is also what will let CI
go green with no key and no network.

`cp .env.example .env` matters only once the answering step lands; retrieval needs no key.

## Deliberate limits

- **Scanned PDFs are not supported.** No text layer means nothing to extract; OCR is out of scope.
- **Citations are chunk-level**, so they point at a passage on a page, not at one sentence.
- **Russian source material is the target.** The chunking assumes Russian paragraph and
  sentence conventions, which is where the accuracy work has gone.

## Licence

MIT.
