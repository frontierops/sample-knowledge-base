#!/usr/bin/env python3
"""Pure-logic tests for ingest.py.

Run:  python scripts/test_ingest.py
Requires only PyYAML — no OpenAI, no Qdrant, no network. This works because
ingest.py imports the heavy libraries lazily inside the functions that use them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = '''---
title: "Test Doc"
id: test-doc
category: characters
tags: [a, b]
era: age-of-rebellion
related: [foo, bar]
summary: "A summary."
---

# Test Doc

Intro paragraph here.

## First Section

First body.

## Second Section

Second body.
'''


def test_parse_frontmatter():
    meta, body = ingest.parse_frontmatter(SAMPLE)
    assert meta["id"] == "test-doc"
    assert meta["tags"] == ["a", "b"]
    assert body.startswith("# Test Doc")


def test_chunk_body_splits_on_h2():
    _, body = ingest.parse_frontmatter(SAMPLE)
    chunks = ingest.chunk_body(body)
    assert [h for h, _ in chunks] == ["", "First Section", "Second Section"]
    assert chunks[0][1] == "Intro paragraph here."
    assert "First body." in chunks[1][1]


def test_build_chunks_indices():
    chunks = ingest.build_chunks("characters/test-doc.md", SAMPLE)
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert chunks[0].heading == ""


def test_point_ids_unique_and_deterministic():
    a = ingest.build_chunks("characters/test-doc.md", SAMPLE)
    b = ingest.build_chunks("characters/test-doc.md", SAMPLE)
    assert len({c.point_id for c in a}) == 3            # unique per chunk
    assert a[0].point_id == b[0].point_id               # stable across runs
    other = ingest.build_chunks("planets/test-doc.md", SAMPLE)
    assert other[0].point_id != a[0].point_id           # path-sensitive


def test_no_h2_yields_single_chunk():
    text = SAMPLE.split("## First")[0]   # frontmatter + h1 + intro only
    chunks = ingest.build_chunks("characters/x.md", text)
    assert len(chunks) == 1
    assert chunks[0].heading == ""


def test_payload_has_expected_keys():
    c = ingest.build_chunks("characters/test-doc.md", SAMPLE)[1]
    p = c.payload()
    for k in ("doc_id", "title", "category", "era", "tags", "related",
              "summary", "path", "heading", "chunk_index", "text"):
        assert k in p, f"missing payload key: {k}"
    assert p["path"] == "characters/test-doc.md"
    assert p["heading"] == "First Section"


def test_embed_input_prefixes_title_and_heading():
    c = ingest.build_chunks("characters/test-doc.md", SAMPLE)[1]
    assert c.embed_input().startswith("Test Doc — First Section")
    intro = ingest.build_chunks("characters/test-doc.md", SAMPLE)[0]
    assert intro.embed_input().startswith("Test Doc")  # no trailing dash


def test_content_scope_excludes_meta_files():
    files = ingest.iter_content_files(ROOT)
    rels = {f.relative_to(ROOT).as_posix() for f in files}
    assert "README.md" not in rels
    assert all(not r.startswith(("eval/", "scripts/", "docs/")) for r in rels)
    assert len(files) == 63, f"expected 63 content docs, found {len(files)}"


def run():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
