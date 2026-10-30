# Agentic development refactor verification

This work starts from `2ef64eb` and remains local on `adam/refactor-agentic-development`.
It preserves retrieval semantics while strengthening ownership, persistence, and verification.

## Implemented design

- `IndexBuilder` owns source capture, incremental reuse, and publication.
- `IndexReader` owns generation loading and neighbor resolution.
- `TraceOperations` owns collection selection and one snapshot per collection for each search.
- Typed responses carry collection and generation identity through ranking and rendering.
- Public dictionary methods remain compatibility boundaries.
- Persisted schemas reject malformed rows, contradictory counts, and missing source provenance.
- Build recipes identify the actual backend, dimensions, chunking, tokenizer, transformation, and BM25 settings.
- Evaluation manifests identify the corpus, query population, code, recipe, and measurement protocol.
- Evaluation aggregates derive from result rows. Report loading rejects contradictory claims.
- Conversion plans reject collisions and overlapping roots before output writes.
- Conversion provenance distinguishes unchanged, changed, and unverified outputs.

The runtime no longer imports server adapters.
Indexing and extraction no longer import retrieval or collection operations.
The previous module-size check was removed because file length does not establish ownership.

## Enforcement choices

| Mechanism | Why a stronger mechanism cannot finish the job alone |
| --- | --- |
| Strict persisted and input validation | Python types cannot validate filesystem bytes or MCP arguments |
| Import contracts | Module ownership does not stop Python from importing the wrong owner |
| Snapshot and publication tests | Types cannot prove ordering across reindexing, filesystem calls, and readers |
| Real transport and installed-wheel checks | In-process types cannot prove subprocess, protocol, or packaging behavior |
| Explicit quality populations and baseline checks | Valid types cannot establish retrieval relevance or comparable measurements |
| Architecture and migration documentation | Code cannot decide which historical contracts a future schema change must preserve |
| Independent review | Automated checks cannot assess every design tradeoff or discover every omitted failure case |

## Behavioral evidence

The full local verification command is `just verify`.
It includes static checks, tests, installed-wheel verification, fixture gates, and both battle suites.
Strict typing covers runtime code and reusable tools.
The same recipes configure CI.

| Local check | Result |
| --- | --- |
| Python 3.13 `just verify` | Passed, 500 fast tests and 6 slow tests, no skips |
| Python 3.14 `just check` | Passed, 500 fast tests, no skips |
| Strict mypy | Passed across 50 runtime and tooling files |
| Import contracts | Both passed |
| Installed wheel | All 12 verification stages passed |
| Independent review | No unresolved findings after correction |

Before and after runs captured 424 query/mode cases across both battle suites.
Every top-five result list matched exactly.
The comparison included document paths, chunk positions, content hashes, raw scores, and fusion scores.
This establishes fixture equivalence, not general retrieval quality or a speed improvement.

| Population | Queries | Top-1 path | Top-5 path | Path MRR |
| --- | ---: | ---: | ---: | ---: |
| Core fixture | 17 | 88.2% | 100.0% | 0.941 |
| Stress fixture | 12 | 33.3% | 91.7% | 0.590 |

Both populations match their observed pre-refactor baselines.
Existing thresholds and percentile definitions remain unchanged.
Stress Top-1 remains below its attention target. The refactor does not claim to solve that ranking weakness.

An actual v6 index built by the original source loaded through the new reader.
Incremental reindex published v7 with the same 24 chunks and the same sampled semantic results.
All migration work used a copied scratch index.

Real stdio and HTTP checks cover automatic negotiation, MCP `2025-11-25`, and MCP `2026-07-28`.
The HTTP client survives server restart without a session identifier.
Host and Origin rejection, tool errors, and strict input validation are exercised.
A real MCP reindex and semantic search succeeded with a cached model and external sockets blocked.

## Historical and new failure cases

These historical defects failed against their pre-fix source and passed after their original fixes:

| Fix | Replayed behavior |
| --- | --- |
| `3a80599` | Hybrid ranking uses one generation |
| `46fb139` | Adaptive `top_k=1` still compares the runner-up |
| `8802bd4` | Rendering preserves fused cross-collection order |
| `0875b29` | Generation directories are synchronized before `CURRENT` changes |

The rendering replay isolates the formatting boundary with fused hits.
The durability replay observes real filesystem calls. It does not simulate power loss.

New targeted cases cover extraction failure and retry, source mutation, metadata-only refresh, and backend cache isolation.
They also cover read-only snapshots, collection-specific followups, malformed generations, partial reindex errors, and false-success responses.
Converter cases exercise case and Unicode aliases on the actual destination filesystem.
Malformed CSV rows, stale outputs, and source/output aliases fail visibly.
These are current-defect or proactive guarantees, not invented historical incidents.

## Independent review and development exercise

GPT-6.1 Sol implementers and an independent Sol reviewer performed this work.
Review found and corrected contradictory evaluation reports, filesystem aliases, implicit collection-name compatibility, and incomplete persisted provenance checks.
The reviewer repeated the failing inputs after correction.

A disposable extension exercise added an optional frontmatter field through extraction, storage, and search.
It exposed a manually maintained metadata codec and checks tied to one schema version.
Optional codec fields now derive from the persisted schema.
Current-family invariants survive a version bump, while unknown persisted schemas remain rejected.
Future schema decoding still requires an explicit compatibility decision.
The exercise field and scratch source were removed.

## Compatibility and limits

Missing documents, failed extraction, and failed conversion now report failure instead of success.
An extraction failure preserves the last complete generation.
Multi-collection reindex reports both completed and failed collections.
Existing conversion outputs without matching provenance require review and explicit regeneration with `--force`.

Valid v6 indexes remain readable. Their next reindex rebuilds into v7.
Configured embedding incompatibility requires reindexing before semantic queries.
Search snapshots remain independent per collection.
Document fetch and listing read live sources.

Local evidence covers macOS with Python 3.13 and fast checks with Python 3.14.
Linux CI and hosted client integrations require their own execution.
Nothing was pushed, and no running daemon index was changed.
Private knowledge bases, large-corpus performance, hardware failures, and deployment behavior remain outside this evidence.
Initial dependency and model preparation can require network access.
PyMuPDF emits existing SWIG deprecation warnings during format tests.

The repository now has explicit owners, enforced dependency direction, executable compatibility checks, and discoverable verification commands.
Future changes should be judged through these guarantees and the stated environmental limits.
