# Wiki Search Evaluation Report

**Timestamp:** 2026-06-13T10:15:38.082369+00:00
**Search Mode:** hybrid
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
| p50 | 8.5ms | ≤20ms |
| p95 | 19.1ms | ≤50ms |
| p99 | 22.1ms | ≤100ms |
| mean | 10.4ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 4 | 100% | 100% | 100% | 13.1ms |
| config | 1 | 100% | 100% | 100% | 7.1ms |
| docs | 1 | 100% | 100% | 100% | 8.3ms |
| features | 1 | 100% | 100% | 100% | 7.7ms |
| indexing | 1 | 100% | 100% | 100% | 7.3ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 8 | 100% | 100% | 10.4ms |
