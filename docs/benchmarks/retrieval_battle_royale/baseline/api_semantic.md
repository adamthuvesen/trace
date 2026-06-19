# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:14:32.858418+00:00
**Search Mode:** semantic
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 8
**Quick Set Only:** No

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 87.5% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 87.5% | ✓ | ≥80% |
| Top-5 Keyword Accuracy | 100.0% | ✓ | ≥95% |
| Mean Reciprocal Rank (path) | 0.938 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 27.6ms | ≤20ms |
| p95 | 49.0ms | ≤50ms |
| p99 | 50.8ms | ≤100ms |
| mean | 32.1ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| ambiguous | 1 | 100% | 100% | 100% | 25.2ms |
| hybrid | 2 | 50% | 100% | 50% | 39.9ms |
| lexical | 2 | 100% | 100% | 100% | 26.8ms |
| paraphrase | 2 | 100% | 100% | 100% | 36.3ms |
| rerank | 1 | 100% | 100% | 100% | 25.9ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 8 | 88% | 100% | 32.1ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| api-hybrid-429 | HTTP 429 Retry-After burst limit | errors/retryable-errors.md |
