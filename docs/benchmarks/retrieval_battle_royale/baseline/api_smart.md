# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:14:33.173383+00:00
**Search Mode:** smart
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 8
**Quick Set Only:** No
**Smart fallback rate:** 87.5%

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 87.5% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 75.0% | ~ | ≥80% |
| Top-5 Keyword Accuracy | 87.5% | ! | ≥95% |
| Mean Reciprocal Rank (path) | 0.938 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 7.8ms | ≤20ms |
| p95 | 12.0ms | ≤50ms |
| p99 | 12.5ms | ≤100ms |
| mean | 8.0ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| ambiguous | 1 | 100% | 100% | 100% | 10.8ms |
| hybrid | 2 | 50% | 100% | 50% | 10.3ms |
| lexical | 2 | 100% | 100% | 50% | 3.8ms |
| paraphrase | 2 | 100% | 100% | 100% | 7.6ms |
| rerank | 1 | 100% | 100% | 100% | 9.4ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 8 | 88% | 100% | 8.0ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| api-hybrid-429 | HTTP 429 Retry-After burst limit | errors/retryable-errors.md |
