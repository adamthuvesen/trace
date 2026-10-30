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
| macOS Python 3.13 `just verify` | Passed, 537 fast tests and 6 slow tests, no skips |
| Linux ARM64 Python 3.13 `just verify` | Passed, 537 fast tests and 6 slow tests, no skips |
| macOS Python 3.14 `just check` | Passed, 537 fast tests, no skips |
| Strict mypy | Passed across 51 runtime and tooling files |
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

## Final reassessment

A second audit found failure paths that the first pass had missed.
The completed corrections include:

- Unreadable directories stop indexing instead of becoming silent deletions.
- Collection index paths cannot alias on the destination filesystem.
- Forked processes cannot inherit usable writer-lock ownership or unlock their parent's lock.
- Symlink and hard-link lockfiles cannot truncate source documents.
- Pointer publication ignores unsafe stale temporary paths and uses exclusive creation.
- Failed publication removes only that attempt's unpublished files.
- Invalid UTF-8 code sources fail extraction and preserve the previous generation.
- Relative KB paths derive names from the resolved directory.
- Requested paths, symbolic-link targets, and filesystem spelling variants obey consistent visibility rules.
- Unrelated backend classes cannot impersonate the built-in ONNX backend by name.

The registry's unused merge implementation was removed.
Runtime searches and their tests now use the one application-owned merge.
The converter and registry share destination equivalence checks.

Both battle suites now enforce the existing regression thresholds against 24 observed reports.
Failure injection proves that collapsed retrieval and missing baselines return failure.
The reports retain the failing KB, mode, and query transitions.
`just battle` and `just battle-challenge` expose focused verification.
No quality threshold or measurement definition changed.

Independent review repeated the original failure inputs and closed all findings.
All 14 selected negative controls failed against `472a793` and pass in the corrected suite.
Those controls include real filesystem and fork cases plus explicit ENOSPC fault injection.
The Linux run used an unprivileged user and a case-sensitive container filesystem.
This complements macOS case and Unicode alias checks.
PyStemmer required C build tools on the minimal Linux ARM64 image.
That prerequisite is now documented.

## Compatibility and limits

Missing documents, failed extraction, and failed conversion now report failure instead of success.
An extraction failure preserves the last complete generation.
Multi-collection reindex reports both completed and failed collections.
Existing conversion outputs without matching provenance require review and explicit regeneration with `--force`.

Valid v6 indexes remain readable. Their next reindex rebuilds into v7.
Configured embedding incompatibility requires reindexing before semantic queries.
Search snapshots remain independent per collection.
Document fetch and listing read live sources.

Local evidence covers macOS and Linux ARM64 with Python 3.13, plus macOS fast checks with Python 3.14.
Hosted CI, Linux x86-64, and deployed client integrations require their own execution.
Nothing was pushed, and no running daemon index was changed.
Private knowledge bases, large-corpus performance, hardware failures, and deployment behavior remain outside this evidence.
Initial dependency and model preparation can require network access.
PyMuPDF emits existing SWIG deprecation warnings during format tests.

The repository now has explicit owners, enforced dependency direction, executable compatibility checks, and discoverable verification commands.
Future changes should be judged through these guarantees and the stated environmental limits.
