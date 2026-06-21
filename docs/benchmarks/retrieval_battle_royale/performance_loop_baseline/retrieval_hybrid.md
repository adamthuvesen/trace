# Wiki Search Evaluation Report

**Timestamp:** 2026-06-21T19:30:52.756206+00:00
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
| p50 | 19.7ms | ≤20ms |
| p95 | 24.4ms | ≤50ms |
| p99 | 25.5ms | ≤100ms |
| mean | 20.3ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 100% | 100% | 100% | 20.0ms |
| config | 3 | 100% | 100% | 100% | 18.5ms |
| features | 2 | 100% | 100% | 100% | 19.5ms |
| indexing | 1 | 100% | 100% | 100% | 18.7ms |
| metrics | 2 | 100% | 100% | 50% | 20.2ms |
| search | 2 | 100% | 100% | 100% | 24.8ms |
| troubleshooting | 1 | 100% | 100% | 100% | 21.6ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 100% | 100% | 20.3ms |
