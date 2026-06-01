#!/usr/bin/env python3
"""Query the Qdrant collection from the command line — a smoke test for search.

Uses the same OpenAI embedding model as the ingestion pipeline, so query vectors
match the indexed vectors.

Usage:
    python scripts/search.py "who destroyed the Death Star?"
    python scripts/search.py --category planets "ice world rebel base"
    python scripts/search.py --era fall-of-the-jedi "who manipulated both sides?"

Environment:
    OPENAI_API_KEY               (required)
    QDRANT_URL, QDRANT_API_KEY   (required)
    QDRANT_COLLECTION            (default: starwars_kb)
"""
from __future__ import annotations

import argparse
import os
import sys

DEFAULT_COLLECTION = "starwars_kb"
EMBED_MODEL = "text-embedding-3-large"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Search the Qdrant knowledge base.")
    ap.add_argument("query", help="natural-language query")
    ap.add_argument("--collection",
                    default=os.environ.get("QDRANT_COLLECTION") or DEFAULT_COLLECTION)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--category", help="restrict to a category (payload filter)")
    ap.add_argument("--era", help="restrict to an era (payload filter)")
    args = ap.parse_args(argv)

    url = os.environ.get("QDRANT_URL")
    if not url:
        sys.exit("ERROR: QDRANT_URL is not set.")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("ERROR: OPENAI_API_KEY is not set.")

    from openai import OpenAI
    from qdrant_client import QdrantClient, models

    oai = OpenAI()
    vector = oai.embeddings.create(
        model=EMBED_MODEL, input=[args.query]).data[0].embedding

    conditions = []
    if args.category:
        conditions.append(models.FieldCondition(
            key="category", match=models.MatchValue(value=args.category)))
    if args.era:
        conditions.append(models.FieldCondition(
            key="era", match=models.MatchValue(value=args.era)))
    query_filter = models.Filter(must=conditions) if conditions else None

    client = QdrantClient(url=url, api_key=os.environ.get("QDRANT_API_KEY") or None)
    hits = client.query_points(
        collection_name=args.collection, query=vector, limit=args.limit,
        query_filter=query_filter, with_payload=True).points

    if not hits:
        print("No results.")
        return 0
    for i, h in enumerate(hits, 1):
        p = h.payload
        heading = f" › {p['heading']}" if p.get("heading") else ""
        print(f"{i}. [{h.score:.3f}] {p['title']}{heading}  ({p['path']})")
        snippet = " ".join((p.get("text") or "").split())[:200]
        print(f"     {snippet}…\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
