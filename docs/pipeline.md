# Qdrant ingestion pipeline

This repo ships a small pipeline that embeds the knowledge base and upserts it
into a [Qdrant](https://qdrant.tech/) collection so it can be searched. A GitHub
Action runs it automatically; you can also run it locally.

## How it works

```
push to main ─▶ GitHub Action ─▶ scripts/ingest.py
                                     │
   1. walk the 7 content folders (characters/, planets/, factions/,
      technology/, events/, species/, concepts/)
   2. parse YAML frontmatter + body
   3. chunk each document on its ## (H2) headings
   4. embed each chunk with OpenAI (text-embedding-3-large, 3072-dim)
   5. build points: UUID5(path#chunk_index) + vector + payload
   6. ensure the collection exists (create if missing)
   7. upsert all points
   8. orphan cleanup: delete points whose source no longer exists
                                     │
                                     ▼
                           Qdrant Cloud collection
```

**Embedding is done in the runner**, not by Qdrant. The runner calls OpenAI's
`text-embedding-3-large` model ($0.13 per 1M tokens) to turn each chunk into a
3072-dim vector, then upserts the vectors into Qdrant. This whole corpus is only
~20k tokens, so a full run still costs a fraction of a cent. This needs an
`OPENAI_API_KEY` in addition to the Qdrant connection.

### What gets indexed

Only the seven content folders are embedded. `README.md`, `eval/`, `scripts/`,
`docs/`, and `.github/` are excluded (see `CONTENT_DIRS` in `scripts/ingest.py`),
so the index stays pure knowledge-base content.

### Chunking

Each document is split on its `##` headings. The text before the first heading
becomes an "intro" chunk. Short stub documents with no `##` become a single
chunk. The text fed to the embedder is prefixed with the document title and the
section heading for better retrieval; the raw chunk is stored in the payload.

### Point payload

Each point carries the source frontmatter so it can be filtered and cited:

```jsonc
{
  "doc_id": "darth-vader", "title": "Darth Vader", "category": "characters",
  "era": "reign-of-the-empire", "tags": ["sith", "empire"], "related": [...],
  "summary": "...", "path": "characters/darth-vader.md",
  "heading": "From Jedi to Sith", "chunk_index": 1, "text": "<the chunk>"
}
```

`category`, `era`, and `tags` are usable as Qdrant payload filters.

### Idempotency

Point IDs are `UUID5(namespace, "{path}#{chunk_index}")`, so editing a document
updates its points in place instead of creating duplicates. After upserting the
full current set, the script deletes any points in the collection that are not in
this run — handling renames and deletions. Re-running with no changes is a no-op.

## Setup

### 1. Create a Qdrant Cloud cluster

Sign up at [cloud.qdrant.io](https://cloud.qdrant.io), create a (free-tier is
fine) cluster, and copy its **URL** and an **API key**.

### 2. Get an OpenAI API key

Create a key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys).
Embedding this corpus costs a fraction of a cent per run.

### 3. Add GitHub repository secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
| --- | --- |
| `OPENAI_API_KEY` | your OpenAI API key (`sk-...`) |
| `QDRANT_URL` | your cluster URL, e.g. `https://xxxx.cloud.qdrant.io:6333` |
| `QDRANT_API_KEY` | your Qdrant API key |

The collection name defaults to `starwars_kb` (set in the workflow as
`QDRANT_COLLECTION`).

### 4. Run it

- **Automatically:** push a change to any content file on `main`.
- **Manually:** Actions → *Ingest knowledge base into Qdrant* → **Run workflow**.

## Running locally

### Install

Use a virtual environment (recommended on macOS to avoid the system-Python
"externally-managed-environment" error):

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Test without any keys

```bash
python scripts/ingest.py --dry-run   # parse + chunk only, no embedding/network
python scripts/test_ingest.py        # pure-logic unit tests (needs only PyYAML)
```

### Fully local end-to-end (OpenAI key + Docker, no Qdrant Cloud)

`QDRANT_API_KEY` is optional and only needed for Qdrant Cloud, so a local Docker
Qdrant works with just an OpenAI key:

```bash
docker run -p 6333:6333 qdrant/qdrant
export OPENAI_API_KEY="sk-..."
export QDRANT_URL="http://localhost:6333"
python scripts/ingest.py
python scripts/search.py "who destroyed the Death Star?"
python scripts/search.py --category planets "ice world rebel base"
```

### Against Qdrant Cloud

```bash
export OPENAI_API_KEY="sk-..."
export QDRANT_URL="https://xxxx.cloud.qdrant.io:6333"
export QDRANT_API_KEY="..."
python scripts/ingest.py
python scripts/search.py "who manipulated both sides of the Clone Wars?"
```

## Changing the embedding model

The model and its vector size are defined together at the top of
`scripts/ingest.py` (`EMBED_MODEL`, `VECTOR_SIZE`), and `EMBED_MODEL` is mirrored
in `scripts/search.py`. The default is `text-embedding-3-large` (3072-dim);
`text-embedding-3-small` is 1536-dim.

A collection's vector dimensions are fixed at creation, so if you switch to a
model with a different dimension you must rebuild the collection. Update both
files, then either re-ingest with `--recreate` (drops and rebuilds the existing
collection):

```bash
python scripts/ingest.py --recreate
```

or point `QDRANT_COLLECTION` at a new collection name. Without one of these, the
ingest script refuses to write wrong-sized vectors into the existing collection.
