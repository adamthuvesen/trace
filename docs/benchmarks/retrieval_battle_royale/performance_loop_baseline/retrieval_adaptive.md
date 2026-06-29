# Wiki Search Evaluation Report

**Timestamp:** 2026-06-21T19:30:53.578610+00:00
**Search Mode:** adaptive
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 19
**Quick Set Only:** No
**Adaptive fallback rate:** 52.6%

**Eval mode:** includes stress queries

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 100.0% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 47.4% | ✗ | ≥80% |
| Top-5 Keyword Accuracy | 52.6% | ✗ | ≥95% |
| Mean Reciprocal Rank (path) | 1.000 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 19.7ms | ≤20ms |
| p95 | 39.1ms | ≤50ms |
| p99 | 60.3ms | ≤100ms |
| mean | 15.3ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 100% | 100% | 38% | 9.2ms |
| config | 3 | 100% | 100% | 0% | 0.3ms |
| features | 2 | 100% | 100% | 100% | 30.3ms |
| indexing | 1 | 100% | 100% | 100% | 65.6ms |
| metrics | 2 | 100% | 100% | 50% | 20.3ms |
| search | 2 | 100% | 100% | 100% | 24.7ms |
| troubleshooting | 1 | 100% | 100% | 0% | 0.2ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 100% | 100% | 15.3ms |
