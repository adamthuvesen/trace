# Wiki Search Evaluation Report

**Timestamp:** 2026-06-21T19:30:52.358555+00:00
**Search Mode:** semantic
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 19
**Quick Set Only:** No

**Eval mode:** includes stress queries

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 94.7% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 89.5% | ✓ | ≥80% |
| Top-5 Keyword Accuracy | 100.0% | ✓ | ≥95% |
| Mean Reciprocal Rank (path) | 0.974 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 16.8ms | ≤20ms |
| p95 | 27.9ms | ≤50ms |
| p99 | 30.1ms | ≤100ms |
| mean | 18.0ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 88% | 100% | 88% | 17.9ms |
| config | 3 | 100% | 100% | 100% | 17.0ms |
| features | 2 | 100% | 100% | 100% | 16.8ms |
| indexing | 1 | 100% | 100% | 100% | 13.3ms |
| metrics | 2 | 100% | 100% | 50% | 20.6ms |
| search | 2 | 100% | 100% | 100% | 24.1ms |
| troubleshooting | 1 | 100% | 100% | 100% | 12.7ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 95% | 100% | 18.0ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| stress-bm25 | Which bag-of-words scoring model dampens... | glossary/tf-idf.md |
