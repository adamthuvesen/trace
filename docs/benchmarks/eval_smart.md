# Wiki Search Evaluation Report

**Timestamp:** 2026-06-13T10:46:30.788487+00:00
**Search Mode:** smart
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 13
**Quick Set Only:** No
**Smart fallback rate:** 61.5%

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
| p50 | 7.3ms | ≤20ms |
| p95 | 13.5ms | ≤50ms |
| p99 | 20.5ms | ≤100ms |
| mean | 5.8ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 4 | 100% | 100% | 100% | 11.2ms |
| config | 5 | 100% | 100% | 100% | 1.6ms |
| docs | 1 | 100% | 100% | 100% | 7.5ms |
| features | 1 | 100% | 100% | 100% | 7.3ms |
| indexing | 1 | 100% | 100% | 100% | 7.3ms |
| troubleshooting | 1 | 100% | 100% | 100% | 0.1ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 13 | 100% | 100% | 5.8ms |
