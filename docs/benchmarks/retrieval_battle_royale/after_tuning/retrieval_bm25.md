# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:19:44.488267+00:00
**Search Mode:** bm25
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 19
**Quick Set Only:** No

**Eval mode:** includes stress queries

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 89.5% | ✓ | ≥75% |
| Top-5 Path Accuracy | 94.7% | ~ | ≥95% |
| Top-1 Keyword Accuracy | 0.0% | ✗ | ≥80% |
| Top-5 Keyword Accuracy | 0.0% | ✗ | ≥95% |
| Mean Reciprocal Rank (path) | 0.921 | - | - |
| Within max_rank Path | 94.7% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 0.2ms | ≤20ms |
| p95 | 0.5ms | ≤50ms |
| p99 | 0.5ms | ≤100ms |
| mean | 0.2ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 88% | 88% | 0% | 0.2ms |
| config | 3 | 100% | 100% | 0% | 0.2ms |
| features | 2 | 50% | 100% | 0% | 0.1ms |
| indexing | 1 | 100% | 100% | 0% | 0.2ms |
| metrics | 2 | 100% | 100% | 0% | 0.2ms |
| search | 2 | 100% | 100% | 0% | 0.2ms |
| troubleshooting | 1 | 100% | 100% | 0% | 0.2ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 89% | 95% | 0.2ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| para-rerank | reorder the shortlist with a slower but ... | features/cross-encoder.md |
| para-ann | find nearby vectors fast without scannin... | glossary/rrf.md |
