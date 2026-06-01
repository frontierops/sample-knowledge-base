# Evaluation set

`queries.jsonl` is a golden retrieval set for testing a RAG or search system against this
knowledge base. Each line is a JSON object:

| Field | Meaning |
| --- | --- |
| `id` | Stable query identifier (`q01`…`q30`). |
| `query` | A natural-language question a user might ask. |
| `expected_docs` | Paths (relative to the repo root) of the document(s) that contain the answer. The order is not significant. |
| `answer` | A short reference answer, for grading a generated response. |
| `difficulty` | `easy` (one direct fact), `medium` (some inference or a known multi-doc fact), or `hard` (multi-hop reasoning across several documents). |

## How `expected_docs` is intended to be used

`expected_docs` is the **relevance judgment** for retrieval scoring. When a query lists more than
one document, each listed document independently contains material that supports the answer — a good
retriever should surface at least one, and ideally all, of them. This makes the set usable for both
lenient (hit@k) and strict (full-set recall) scoring.

## Suggested metrics

- **Recall@k** — fraction of `expected_docs` appearing in the top *k* retrieved chunks/documents.
- **Hit@k** — 1 if *any* `expected_doc` appears in the top *k*, else 0. Good for the multi-doc queries.
- **MRR** — mean reciprocal rank of the first relevant document.
- **Answer correctness** — grade a generated answer against the `answer` field (exact match is too
  strict; use an LLM judge or keyword overlap).

## Difficulty mix

| Difficulty | Count | What it tests |
| --- | --- | --- |
| easy | 10 | Direct lookups; a single well-named document answers the query. |
| medium | 10 | Slight inference or facts split across two related documents. |
| hard | 10 | Multi-hop synthesis spanning three or more documents and several hops of reasoning. |

The hard queries deliberately depend on the corpus's cross-references and on subjects described from
more than one document (e.g. the Battle of Yavin appears in `events/battle-of-yavin.md`,
`technology/death-star.md`, and `characters/luke-skywalker.md`).
