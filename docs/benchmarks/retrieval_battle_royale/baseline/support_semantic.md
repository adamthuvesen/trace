# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:14:32.263872+00:00
**Search Mode:** semantic
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
| p50 | 9.4ms | ≤20ms |
| p95 | 10.1ms | ≤50ms |
| p99 | 10.1ms | ≤100ms |
| mean | 9.1ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| ambiguous | 1 | 100% | 100% | 100% | 9.7ms |
| hybrid | 2 | 100% | 100% | 100% | 8.4ms |
| lexical | 2 | 100% | 100% | 100% | 9.8ms |
| paraphrase | 2 | 100% | 100% | 100% | 8.4ms |
| rerank | 1 | 100% | 100% | 100% | 10.0ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 8 | 100% | 100% | 9.1ms |
