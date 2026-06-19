# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:19:45.279292+00:00
**Search Mode:** reranked
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 19
**Quick Set Only:** No

**Eval mode:** includes stress queries

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 100.0% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 94.7% | ✓ | ≥80% |
| Top-5 Keyword Accuracy | 100.0% | ✓ | ≥95% |
| Mean Reciprocal Rank (path) | 1.000 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 9.3ms | ≤20ms |
| p95 | 13.8ms | ≤50ms |
| p99 | 13.9ms | ≤100ms |
| mean | 10.1ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 100% | 100% | 100% | 10.9ms |
| config | 3 | 100% | 100% | 100% | 9.1ms |
| features | 2 | 100% | 100% | 100% | 9.1ms |
| indexing | 1 | 100% | 100% | 100% | 12.7ms |
| metrics | 2 | 100% | 100% | 50% | 8.6ms |
| search | 2 | 100% | 100% | 100% | 10.1ms |
| troubleshooting | 1 | 100% | 100% | 100% | 9.3ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 100% | 100% | 10.1ms |
