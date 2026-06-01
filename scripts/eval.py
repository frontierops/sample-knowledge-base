#!/usr/bin/env python3
"""Evaluate retrieval quality against Qdrant using the eval/queries.jsonl golden set.

For each query it embeds the question, searches Qdrant, collapses the retrieved
chunks into a ranked list of unique documents, and scores that against the
query's expected_docs. Reports Recall@k, Hit@k, and MRR — overall and by
difficulty — and lists the queries that missed.

Metrics are computed at DOCUMENT granularity (expected_docs are document paths),
so the script over-fetches chunks and de-duplicates them to unique documents
before scoring.

Prerequisite: the knowledge base must already be ingested (run scripts/ingest.py).

Usage:
    python scripts/eval.py              # k=5 against the default collection
    python scripts/eval.py --k 3
    python scripts/eval.py --show-all   # print every query, not just misses

Environment:
    OPENAI_API_KEY, QDRANT_URL   (required)
    QDRANT_API_KEY               (Qdrant Cloud only)
    QDRANT_COLLECTION            (default: starwars_kb)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest  # noqa: E402  — reuse embedding + client config (DRY)

QUERIES_PATH = Path(__file__).resolve().parent.parent / "eval" / "queries.jsonl"
DIFFICULTIES = ["easy", "medium", "hard"]


# --- pure logic (unit-testable, no network) --------------------------------

def load_queries(path: Path) -> list[dict]:
    queries = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                queries.append(json.loads(line))
    return queries


def ranked_unique_docs(hits) -> list[str]:
    """Collapse retrieved chunk hits into unique doc paths, preserving rank order."""
    seen, docs = set(), []
    for h in hits:
        path = h.payload.get("path")
        if path and path not in seen:
            seen.add(path)
            docs.append(path)
    return docs


def score_query(expected: list[str], retrieved_docs: list[str], k: int) -> dict:
    """Compute Hit@k, Recall@k, and reciprocal rank for one query."""
    exp = set(expected)
    topk = retrieved_docs[:k]
    hit = any(d in exp for d in topk)
    recall = len([d for d in topk if d in exp]) / len(exp) if exp else 0.0
    rr, first_rank = 0.0, None
    for i, d in enumerate(retrieved_docs, 1):   # first relevant doc, anywhere
        if d in exp:
            rr, first_rank = 1.0 / i, i
            break
    return {"hit": hit, "recall": recall, "rr": rr, "first_rank": first_rank}


def aggregate(rows: list[dict], k: int) -> tuple | None:
    n = len(rows)
    if not n:
        return None
    return (
        sum(r["recall"] for r in rows) / n,
        sum(1 for r in rows if r["hit"]) / n,
        sum(r["rr"] for r in rows) / n,
        n,
    )


# --- runner ----------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate retrieval against Qdrant.")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--collection",
                    default=os.environ.get("QDRANT_COLLECTION", ingest.DEFAULT_COLLECTION))
    ap.add_argument("--show-all", action="store_true",
                    help="print every query result, not just misses")
    args = ap.parse_args(argv)

    queries = load_queries(QUERIES_PATH)
    if not queries:
        sys.exit("No queries found in eval/queries.jsonl")

    # Embed all questions in one batched call (reuses the ingest embedder).
    vectors = ingest.embed_texts([q["query"] for q in queries])

    client = ingest.get_client()
    fetch = max(args.k * 5, 25)   # over-fetch chunks, then collapse to unique docs

    rows = []
    for q, vec in zip(queries, vectors):
        hits = client.query_points(
            collection_name=args.collection, query=vec,
            limit=fetch, with_payload=True).points
        s = score_query(q["expected_docs"], ranked_unique_docs(hits), args.k)
        s.update(id=q["id"], query=q["query"],
                 difficulty=q.get("difficulty", "?"), expected=q["expected_docs"])
        rows.append(s)

    overall = aggregate(rows, args.k)
    print(f"\nRetrieval eval @k={args.k}  ({overall[3]} queries) — "
          f"collection '{args.collection}'")
    print(f"  Recall@{args.k}: {overall[0]:.2f}   "
          f"Hit@{args.k}: {overall[1]:.2f}   MRR: {overall[2]:.2f}\n")
    for d in DIFFICULTIES:
        a = aggregate([r for r in rows if r["difficulty"] == d], args.k)
        if a:
            print(f"  {d:<6} ({a[3]:>2}): Recall@{args.k} {a[0]:.2f}  "
                  f"Hit@{args.k} {a[1]:.2f}  MRR {a[2]:.2f}")

    misses = [r for r in rows if not r["hit"]]
    shown = rows if args.show_all else misses
    if shown:
        header = "All queries:" if args.show_all else f"\nMisses ({len(misses)}):"
        print("\n" + header)
        for r in shown:
            mark = "✓" if r["hit"] else "✗"
            where = (f"best expected at rank {r['first_rank']}"
                     if r["first_rank"] else "no expected doc retrieved")
            print(f"  {mark} {r['id']}  \"{r['query']}\"")
            if not r["hit"] or args.show_all:
                print(f"       expected {r['expected']} — {where}")
    else:
        print("\nNo misses. 🎉")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
