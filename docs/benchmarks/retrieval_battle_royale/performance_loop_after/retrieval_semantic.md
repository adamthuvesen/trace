# Wiki Search Evaluation Report

**Timestamp:** 2026-06-21T19:37:04.387748+00:00
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
| p50 | 12.7ms | ≤20ms |
| p95 | 16.2ms | ≤50ms |
| p99 | 18.1ms | ≤100ms |
| mean | 12.9ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 88% | 100% | 88% | 12.5ms |
| config | 3 | 100% | 100% | 100% | 14.5ms |
| features | 2 | 100% | 100% | 100% | 14.6ms |
| indexing | 1 | 100% | 100% | 100% | 14.1ms |
| metrics | 2 | 100% | 100% | 50% | 10.3ms |
| search | 2 | 100% | 100% | 100% | 13.8ms |
| troubleshooting | 1 | 100% | 100% | 100% | 10.5ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 95% | 100% | 12.9ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| stress-bm25 | Which bag-of-words scoring model dampens... | glossary/tf-idf.md |
