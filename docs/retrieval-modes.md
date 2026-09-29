# Retrieval Modes

Trace has four retrieval modes. `adaptive` is what `search` runs.

| Mode | Best use | Avoid when |
| --- | --- | --- |
| `bm25` | Exact identifiers, config keys, error codes, filenames, and known terms. Fastest by a wide margin. | The user paraphrases or doesn't know the document's vocabulary. |
| `semantic` | Paraphrases and conceptual lookups when exact terms are missing. A lexical boost re-ranks the top 50 vector candidates so exact titles, aliases, and terms surface. | You need deterministic exact-token behavior. |
| `hybrid` | BM25 and semantic ranking fused per document with reciprocal-rank fusion (semantic weight 0.4). | Latency matters more than the last few MRR points on keyword-dense queries. |
| `adaptive` | Default. BM25 alone when its top document scores at least 1.3x the runner-up, otherwise `hybrid`. One BM25 match also fuses, since it is often a paraphrase sharing one word with some page. | You are debugging one method in isolation. |

## How BM25 ranks a file

BM25 scores chunks, then rolls them up per file:

- best chunk score, plus a saturating bonus for several strong chunks;
- a metadata boost when query terms appear in the title, aliases, path, or heading breadcrumb;
- a larger boost when the query is essentially the page's title or one alias (every query term in that name, covering at least 60% of it). This also lifts the `index.md`/`log.md` hub demotion for that page;
- 0.7x for frontmatter `status: superseded` or `deprecated`, so a replaced page ranks just below its replacement.

Frontmatter never reaches the ranking text as YAML. `title`, `aliases`, and `summary` become a card at the top of the first chunk.

## Battle suites

The committed no-secret fixtures (`tests/fixtures/eval_kb`, `tests/fixtures/battle_kbs/*`) are small and paraphrase-heavy, so semantic search does well on them. Treat them as regression signals, not corpus-scale claims.

```bash
uv run python -m tools.eval.battle_royale --label <label>
uv run python -m tools.eval.battle_royale \
  --suite tests/fixtures/eval_battle_royale_challenge.yaml --label <label>
```

Challenge suite (61 queries), 2026-09-29. "Before" is commit `e979fc5` re-run the same day. The committed `challenge_current` summary predates it and is stale.

| Mode | MRR before | MRR after | p50 after |
| --- | ---: | ---: | ---: |
| `bm25` | 0.833 | 0.833 | 0.1 ms |
| `semantic` | 0.919 | 0.919 | 4.5 ms |
| `hybrid` | 0.910 | 0.883 | 3.6 ms |
| `adaptive` | 0.870 | 0.878 | 3.5 ms |

Hybrid lost ground here while it gained 0.11 and 0.17 MRR on two private knowledge bases. Document-level fusion and the 0.4 weight favor BM25, and this suite rewards semantic search. See [benchmarks/2026-09-29-trace-overhaul.md](benchmarks/2026-09-29-trace-overhaul.md).
