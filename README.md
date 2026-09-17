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
- [ ] Embeddings into Qdrant, local, in Docker
- [ ] `POST /ask` returning an answer plus the chunks used
- [ ] CI running green with no API key and no network access
- [ ] `rag-eval`: 20 questions, known answers, a printed retrieval score

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

Not yet runnable — see Status. The intended shape:

```bash
git clone <repo-url> && cd rag-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # fill in your own provider key
docker compose up -d        # Qdrant, locally
```

## Deliberate limits

- **Scanned PDFs are not supported.** No text layer means nothing to extract; OCR is out of scope.
- **Citations are chunk-level**, so they point at a passage on a page, not at one sentence.
- **Russian source material is the target.** The chunking assumes Russian paragraph and
  sentence conventions, which is where the accuracy work has gone.

## Licence

MIT.
