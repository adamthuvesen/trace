# Wiki Search Evaluation Report

**Timestamp:** 2026-06-21T19:37:06.734248+00:00
**Search Mode:** reranked
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 8
**Quick Set Only:** No

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 100.0% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 100.0% | ✓ | ≥80% |
| Top-5 Keyword Accuracy | 100.0% | ✓ | ≥95% |
| Mean Reciprocal Rank (path) | 1.000 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 41.6ms | ≤20ms |
| p95 | 74.7ms | ≤50ms |
| p99 | 84.2ms | ≤100ms |
| mean | 43.9ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| ambiguous | 1 | 100% | 100% | 100% | 31.5ms |
| hybrid | 2 | 100% | 100% | 100% | 41.6ms |
| lexical | 2 | 100% | 100% | 100% | 32.3ms |
| paraphrase | 2 | 100% | 100% | 100% | 69.7ms |
| rerank | 1 | 100% | 100% | 100% | 32.6ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 8 | 100% | 100% | 43.9ms |
