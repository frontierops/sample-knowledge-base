# Galactic Knowledge Base

A sample, Star Wars–themed knowledge base intended as **test data for retrieval-augmented
generation (RAG) and search systems**. The corpus is canon-grounded so that the companion
evaluation set (`eval/queries.jsonl`) has verifiable answers.

## What's in here

| Folder | Contents |
| --- | --- |
| `characters/` | People and droids — Luke Skywalker, Darth Vader, Yoda, Leia, etc. |
| `planets/` | Worlds and their geography, climate, and significance. |
| `factions/` | Governments and organizations — the Empire, Rebel Alliance, Jedi Order, Sith. |
| `technology/` | Ships, weapons, and machines — lightsabers, the Death Star, the *Millennium Falcon*. |
| `events/` | Wars and battles — the Clone Wars, Order 66, the Battle of Yavin. |
| `species/` | Sentient species — Wookiees, Twi'leks, Hutts, Ewoks. |
| `concepts/` | Abstract subjects — the Force, the Jedi Code, the Rule of Two. |
| `eval/` | A golden query set mapping questions to the documents that answer them. |

## Document anatomy

Every document carries YAML frontmatter, then a Markdown body. Bodies vary in length on
purpose — short stubs (~80–150 words), standard articles (~300–500), and deep-dives
(~800–1200) — to exercise chunking and recall at different granularities.

```yaml
---
title: "Darth Vader"          # human-readable title
id: darth-vader               # stable slug, matches the filename
category: characters          # one of the folder names
tags: [sith, empire, force-user]   # free-form retrieval tags
era: reign-of-the-empire      # controlled vocabulary, see below
related: [obi-wan-kenobi, galactic-empire, the-force]   # ids of related docs
summary: "One-line abstract usable as a snippet or reranker signal."
---
```

## Era vocabulary

The `era` field uses a controlled vocabulary so it can be used as a metadata filter:

| Era id | Span |
| --- | --- |
| `old-republic` | The ancient Republic, millennia before the films. |
| `high-republic` | The Republic at its height, ~200 years before the Clone Wars. |
| `fall-of-the-jedi` | The prequel era and the Clone Wars. |
| `reign-of-the-empire` | From the Empire's founding to the Battle of Yavin. |
| `age-of-rebellion` | The Galactic Civil War, roughly the original trilogy. |
| `new-republic` | The era after the Empire's defeat at Endor. |
| `rise-of-the-first-order` | The sequel era. |

Documents that span multiple eras use the era in which the subject is most significant.

## Cross-references

Bodies link liberally to related documents with relative paths
(e.g. `[Obi-Wan Kenobi](../characters/obi-wan-kenobi.md)`). A few subjects are described
from more than one document on purpose — for example, the Battle of Yavin appears in
`events/battle-of-yavin.md`, `technology/death-star.md`, and
`characters/luke-skywalker.md` — to test ranking and de-duplication.

## Using the evaluation set

`eval/queries.jsonl` contains one JSON object per line:

```json
{"id": "q01", "query": "What is Darth Vader's birth name?", "expected_docs": ["characters/darth-vader.md"], "answer": "Anakin Skywalker", "difficulty": "easy"}
```

`expected_docs` lists the document(s) a correct retriever should surface. See
`eval/README.md` for scoring notes.

## Searching this knowledge base (Qdrant pipeline)

This repo includes a pipeline that embeds the content and loads it into a
[Qdrant](https://qdrant.tech/) vector database so it can be searched. Embeddings
are created with OpenAI's `text-embedding-3-large` model. A GitHub Action runs it
automatically on push; you can also run it locally. Full details are in
[`docs/pipeline.md`](docs/pipeline.md).

### Install

Use a virtual environment (recommended on macOS — avoids the system-Python
"externally-managed-environment" error):

```bash
cd sample-knowledge-base
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Run locally

**No keys needed — just check parsing/chunking:**

```bash
python scripts/ingest.py --dry-run   # parse + chunk only, no embedding/network
python scripts/test_ingest.py        # unit tests
```

**Fully local end-to-end — only an OpenAI key + Docker** (no Qdrant Cloud account):

```bash
docker run -p 6333:6333 qdrant/qdrant        # start a local Qdrant
export OPENAI_API_KEY="sk-..."
export QDRANT_URL="http://localhost:6333"    # no QDRANT_API_KEY needed locally
python scripts/ingest.py                     # embed + upsert
python scripts/search.py "who destroyed the Death Star?"
python scripts/search.py --category planets "ice world rebel base"
```

**Against Qdrant Cloud** — add the cluster URL and key:

```bash
export OPENAI_API_KEY="sk-..."
export QDRANT_URL="https://xxxx.cloud.qdrant.io:6333"
export QDRANT_API_KEY="..."
python scripts/ingest.py && python scripts/search.py "who manipulated both sides of the Clone Wars?"
```

The ingest is idempotent — re-running updates changed chunks and removes deleted
ones, so it's safe to run repeatedly while you test.
