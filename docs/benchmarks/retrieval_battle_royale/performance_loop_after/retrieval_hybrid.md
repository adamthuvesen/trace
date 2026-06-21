# Wiki Search Evaluation Report

**Timestamp:** 2026-06-21T19:37:04.855488+00:00
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
| p50 | 20.0ms | ≤20ms |
| p95 | 49.1ms | ≤50ms |
| p99 | 51.2ms | ≤100ms |
| mean | 24.0ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 100% | 100% | 100% | 18.7ms |
| config | 3 | 100% | 100% | 100% | 44.9ms |
| features | 2 | 100% | 100% | 100% | 26.5ms |
| indexing | 1 | 100% | 100% | 100% | 18.3ms |
| metrics | 2 | 100% | 100% | 50% | 18.7ms |
| search | 2 | 100% | 100% | 100% | 15.8ms |
| troubleshooting | 1 | 100% | 100% | 100% | 30.7ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 100% | 100% | 24.0ms |
