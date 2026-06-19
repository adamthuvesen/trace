# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:19:45.078980+00:00
**Search Mode:** hybrid
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
| p50 | 12.6ms | ≤20ms |
| p95 | 26.8ms | ≤50ms |
| p99 | 26.8ms | ≤100ms |
| mean | 14.4ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 100% | 100% | 100% | 16.5ms |
| config | 3 | 100% | 100% | 100% | 14.4ms |
| features | 2 | 100% | 100% | 100% | 10.1ms |
| indexing | 1 | 100% | 100% | 100% | 8.2ms |
| metrics | 2 | 100% | 100% | 50% | 19.3ms |
| search | 2 | 100% | 100% | 100% | 11.7ms |
| troubleshooting | 1 | 100% | 100% | 100% | 7.8ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 100% | 100% | 14.4ms |
