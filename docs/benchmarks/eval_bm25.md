# Wiki Search Evaluation Report

**Timestamp:** 2026-06-13T11:15:45.833781+00:00
**Search Mode:** bm25
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 17
**Quick Set Only:** No

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 88.2% | ✓ | ≥75% |
| Top-5 Path Accuracy | 94.1% | ~ | ≥95% |
| Top-1 Keyword Accuracy | 82.4% | ✓ | ≥80% |
| Top-5 Keyword Accuracy | 94.1% | ~ | ≥95% |
| Mean Reciprocal Rank (path) | 0.912 | - | - |
| Within max_rank Path | 94.1% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 0.2ms | ≤20ms |
| p95 | 2.6ms | ≤50ms |
| p99 | 10.3ms | ≤100ms |
| mean | 0.9ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 6 | 83% | 83% | 83% | 2.2ms |
| config | 3 | 100% | 100% | 100% | 0.1ms |
| features | 2 | 50% | 100% | 50% | 0.2ms |
| indexing | 1 | 100% | 100% | 100% | 0.1ms |
| metrics | 2 | 100% | 100% | 50% | 0.2ms |
| search | 2 | 100% | 100% | 100% | 0.1ms |
| troubleshooting | 1 | 100% | 100% | 100% | 0.1ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 17 | 88% | 94% | 0.9ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| para-rerank | reorder the shortlist with a slower but ... | features/cross-encoder.md |
| para-ann | find nearby vectors fast without scannin... | glossary/rrf.md |
