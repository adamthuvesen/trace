# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:19:45.383625+00:00
**Search Mode:** smart
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 19
**Quick Set Only:** No
**Smart fallback rate:** 52.6%

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
| p50 | 7.8ms | ≤20ms |
| p95 | 10.4ms | ≤50ms |
| p99 | 15.4ms | ≤100ms |
| mean | 5.1ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 100% | 100% | 38% | 4.3ms |
| config | 3 | 100% | 100% | 0% | 0.1ms |
| features | 2 | 100% | 100% | 100% | 9.0ms |
| indexing | 1 | 100% | 100% | 100% | 9.5ms |
| metrics | 2 | 100% | 100% | 50% | 8.5ms |
| search | 2 | 100% | 100% | 100% | 8.4ms |
| troubleshooting | 1 | 100% | 100% | 0% | 0.1ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 100% | 100% | 5.1ms |
