# Wiki Search Evaluation Report

**Timestamp:** 2026-06-21T19:37:05.259350+00:00
**Search Mode:** adaptive
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 19
**Quick Set Only:** No
**Adaptive fallback rate:** 31.6%

**Eval mode:** includes stress queries

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 100.0% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 31.6% | ✗ | ≥80% |
| Top-5 Keyword Accuracy | 31.6% | ✗ | ≥95% |
| Mean Reciprocal Rank (path) | 1.000 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 0.5ms | ≤20ms |
| p95 | 16.4ms | ≤50ms |
| p99 | 16.8ms | ≤100ms |
| mean | 5.2ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 100% | 100% | 38% | 6.4ms |
| config | 3 | 100% | 100% | 0% | 0.3ms |
| features | 2 | 100% | 100% | 100% | 15.5ms |
| indexing | 1 | 100% | 100% | 0% | 0.3ms |
| metrics | 2 | 100% | 100% | 0% | 0.6ms |
| search | 2 | 100% | 100% | 50% | 7.4ms |
| troubleshooting | 1 | 100% | 100% | 0% | 0.4ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 100% | 100% | 5.2ms |
