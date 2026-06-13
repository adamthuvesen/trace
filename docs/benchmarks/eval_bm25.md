# Wiki Search Evaluation Report

**Timestamp:** 2026-06-13T10:15:31.363606+00:00
**Search Mode:** bm25
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
| p50 | 0.2ms | ≤20ms |
| p95 | 10.6ms | ≤50ms |
| p99 | 15.0ms | ≤100ms |
| mean | 2.2ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 4 | 100% | 100% | 100% | 4.2ms |
| config | 1 | 100% | 100% | 100% | 0.1ms |
| docs | 1 | 100% | 100% | 100% | 0.1ms |
| features | 1 | 100% | 100% | 100% | 0.1ms |
| indexing | 1 | 100% | 100% | 100% | 0.2ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 8 | 100% | 100% | 2.2ms |
