#!/usr/bin/env python3
"""Embed the Star Wars knowledge base and upsert it into Qdrant.

Embedding is done with OpenAI's text-embedding-3-large model (3072-dim).
The script is idempotent: stable point IDs mean edits update in place, and points
whose source document no longer exists are deleted after each run ("orphan cleanup").

Only the knowledge-base content folders are embedded — README, eval/, scripts/,
docs/ and CI config are deliberately excluded so the index stays pure content.

Usage:
    python scripts/ingest.py              # embed + upsert to Qdrant Cloud
    python scripts/ingest.py --dry-run    # parse + chunk only, no embed/network

Environment (for a real run):
    OPENAI_API_KEY      OpenAI API key (used to create the embeddings)
    QDRANT_URL          Qdrant Cloud cluster URL
    QDRANT_API_KEY      Qdrant API key
    QDRANT_COLLECTION   collection name (default: starwars_kb)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

# --- configuration ---------------------------------------------------------

# Only these folders are embedded. Everything else (README, eval/, scripts/,
# docs/, .github/) is excluded so the index contains only knowledge content.
CONTENT_DIRS = [
    "characters", "planets", "factions",
    "technology", "events", "species", "concepts",
]

DEFAULT_COLLECTION = "starwars_kb"
EMBED_MODEL = "text-embedding-3-large"   # OpenAI; 3072-dim (higher quality)
VECTOR_SIZE = 3072
EMBED_BATCH = 128                        # inputs per OpenAI embeddings request

# Fixed namespace so UUID5 point IDs are identical across runs and machines.
NAMESPACE = uuid.UUID("6f8d7a52-3e2b-4c1a-9b0e-2a7c1d9f4e30")

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)
H2_RE = re.compile(r"^##\s+(.*)$", re.M)


# --- data types ------------------------------------------------------------

@dataclass
class Chunk:
    path: str          # repo-relative posix path, e.g. "characters/yoda.md"
    chunk_index: int   # 0 is the intro (pre-first-heading) chunk
    heading: str       # "" for the intro chunk, else the H2 text
    text: str          # raw chunk body, stored verbatim in the payload
    meta: dict         # parsed frontmatter

    @property
    def point_id(self) -> str:
        """Deterministic ID so re-runs update in place rather than duplicate."""
        return str(uuid.uuid5(NAMESPACE, f"{self.path}#{self.chunk_index}"))

    def embed_input(self) -> str:
        """Text actually fed to the embedder: title + heading give context."""
        title = self.meta.get("title", "")
        prefix = f"{title} — {self.heading}".strip(" —")
        return f"{prefix}\n{self.text}".strip()

    def payload(self) -> dict:
        m = self.meta
        return {
            "doc_id": m.get("id"),
            "title": m.get("title"),
            "category": m.get("category"),
            "era": m.get("era"),
            "tags": m.get("tags", []),
            "related": m.get("related", []),
            "summary": m.get("summary"),
            "path": self.path,
            "heading": self.heading,
            "chunk_index": self.chunk_index,
            "text": self.text,
        }


# --- pure logic (unit-tested, no network, no heavy deps) -------------------

def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("missing YAML frontmatter")
    meta = yaml.safe_load(m.group(1)) or {}
    return meta, m.group(2).strip()


def _strip_h1(body: str) -> str:
    """Drop a leading '# Title' line; it duplicates the frontmatter title."""
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def chunk_body(body: str) -> list[tuple[str, str]]:
    """Split a doc body into (heading, text) chunks on H2 boundaries.

    Text before the first H2 becomes an intro chunk with heading "".
    A doc with no H2 yields a single intro chunk.
    """
    body = _strip_h1(body)
    matches = list(H2_RE.finditer(body))
    chunks: list[tuple[str, str]] = []
    if not matches:
        if body.strip():
            chunks.append(("", body.strip()))
        return chunks
    intro = body[: matches[0].start()].strip()
    if intro:
        chunks.append(("", intro))
    for i, mt in enumerate(matches):
        start = mt.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunks.append((mt.group(1).strip(), body[start:end].strip()))
    return chunks


def build_chunks(path: str, text: str) -> list[Chunk]:
    meta, body = parse_frontmatter(text)
    return [
        Chunk(path=path, chunk_index=i, heading=heading, text=section, meta=meta)
        for i, (heading, section) in enumerate(chunk_body(body))
    ]


def iter_content_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for d in CONTENT_DIRS:
        files.extend(sorted((root / d).glob("*.md")))
    return files


def load_all_chunks(root: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for fp in iter_content_files(root):
        rel = fp.relative_to(root).as_posix()
        chunks.extend(build_chunks(rel, fp.read_text(encoding="utf-8")))
    return chunks


# --- embedding + Qdrant (heavy deps, imported lazily) ----------------------

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts with OpenAI, batching and preserving input order."""
    from openai import OpenAI
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("ERROR: OPENAI_API_KEY is not set.")
    client = OpenAI()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        resp = client.embeddings.create(
            model=EMBED_MODEL, input=texts[start:start + EMBED_BATCH])
        # Each item carries an explicit index; sort to be order-safe.
        vectors.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return vectors


def embed_chunks(chunks: list[Chunk]) -> list[list[float]]:
    return embed_texts([c.embed_input() for c in chunks])


def get_client():
    from qdrant_client import QdrantClient
    url = os.environ.get("QDRANT_URL")
    if not url:
        sys.exit("ERROR: QDRANT_URL is not set.")
    # API key is optional: Qdrant Cloud needs one; a local Qdrant (Docker) does not.
    return QdrantClient(url=url, api_key=os.environ.get("QDRANT_API_KEY") or None)


def ensure_collection(client, name: str, recreate: bool = False) -> None:
    from qdrant_client import models
    existing = {c.name for c in client.get_collections().collections}
    if recreate and name in existing:
        client.delete_collection(name)
        existing.discard(name)
        print(f"Dropped existing collection '{name}' (--recreate).")
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=VECTOR_SIZE, distance=models.Distance.COSINE),
        )
        print(f"Created collection '{name}' (size={VECTOR_SIZE}, cosine).")
        return
    dim = client.get_collection(name).config.params.vectors.size
    if dim != VECTOR_SIZE:
        sys.exit(f"ERROR: collection '{name}' has dim {dim}, expected {VECTOR_SIZE}. "
                 "Re-run with --recreate to rebuild it, or use a new collection name.")


def upsert_points(client, name: str, chunks, vectors) -> list[str]:
    from qdrant_client import models
    points = [
        models.PointStruct(id=c.point_id, vector=v, payload=c.payload())
        for c, v in zip(chunks, vectors)
    ]
    client.upsert(collection_name=name, points=points)
    return [p.id for p in points]


def cleanup_orphans(client, name: str, current_ids) -> int:
    """Delete points in the collection that are not part of this run."""
    from qdrant_client import models
    current = set(current_ids)
    stale, offset = [], None
    while True:
        records, offset = client.scroll(
            collection_name=name, with_payload=False, with_vectors=False,
            limit=256, offset=offset)
        stale.extend(r.id for r in records if str(r.id) not in current)
        if offset is None:
            break
    if stale:
        client.delete(collection_name=name,
                      points_selector=models.PointIdsList(points=stale))
    return len(stale)


# --- entrypoint ------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Embed the knowledge base into Qdrant.")
    ap.add_argument("--root", default=".", help="repo root containing the content folders")
    ap.add_argument("--collection",
                    default=os.environ.get("QDRANT_COLLECTION", DEFAULT_COLLECTION))
    ap.add_argument("--dry-run", action="store_true",
                    help="parse + chunk only; no embedding or network")
    ap.add_argument("--recreate", action="store_true",
                    help="drop and rebuild the collection (use when changing the model/dimensions)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    chunks = load_all_chunks(root)
    n_docs = len({c.path for c in chunks})
    print(f"Parsed {n_docs} documents into {len(chunks)} chunks.")

    if args.dry_run:
        for cat, n in sorted(Counter(c.meta.get("category") for c in chunks).items()):
            print(f"  {cat}: {n} chunks")
        print("Dry run complete (no embedding, no Qdrant calls).")
        return 0

    print(f"Embedding {len(chunks)} chunks with {EMBED_MODEL} ...")
    vectors = embed_chunks(chunks)

    client = get_client()
    ensure_collection(client, args.collection, recreate=args.recreate)
    ids = upsert_points(client, args.collection, chunks, vectors)
    print(f"Upserted {len(ids)} points into '{args.collection}'.")
    deleted = cleanup_orphans(client, args.collection, ids)
    print(f"Removed {deleted} orphaned points.")
    print(f"Collection now holds {client.count(collection_name=args.collection).count} points.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
