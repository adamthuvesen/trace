# Wiki Search Evaluation Report

**Timestamp:** 2026-06-21T19:37:06.759227+00:00
**Search Mode:** smart
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 8
**Quick Set Only:** No
**Smart fallback rate:** 12.5%

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 100.0% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 12.5% | ✗ | ≥80% |
| Top-5 Keyword Accuracy | 12.5% | ✗ | ≥95% |
| Mean Reciprocal Rank (path) | 1.000 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 0.2ms | ≤20ms |
| p95 | 10.5ms | ≤50ms |
| p99 | 14.8ms | ≤100ms |
| mean | 2.2ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| ambiguous | 1 | 100% | 100% | 100% | 15.9ms |
| hybrid | 2 | 100% | 100% | 0% | 0.2ms |
| lexical | 2 | 100% | 100% | 0% | 0.3ms |
| paraphrase | 2 | 100% | 100% | 0% | 0.2ms |
| rerank | 1 | 100% | 100% | 0% | 0.2ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 8 | 100% | 100% | 2.2ms |
