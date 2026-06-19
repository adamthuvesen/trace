# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:14:33.104186+00:00
**Search Mode:** reranked
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
| p50 | 7.1ms | ≤20ms |
| p95 | 13.8ms | ≤50ms |
| p99 | 13.9ms | ≤100ms |
| mean | 8.8ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| ambiguous | 1 | 100% | 100% | 100% | 7.0ms |
| hybrid | 2 | 50% | 100% | 50% | 7.1ms |
| lexical | 2 | 100% | 100% | 100% | 13.7ms |
| paraphrase | 2 | 100% | 100% | 100% | 7.3ms |
| rerank | 1 | 100% | 100% | 100% | 7.0ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 8 | 88% | 100% | 8.8ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| api-hybrid-429 | HTTP 429 Retry-After burst limit | errors/retryable-errors.md |
