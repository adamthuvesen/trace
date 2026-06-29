# Wiki Search Evaluation Report

**Timestamp:** 2026-06-21T19:30:54.414935+00:00
**Search Mode:** adaptive
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 8
**Quick Set Only:** No
**Adaptive fallback rate:** 50.0%

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 100.0% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 50.0% | ✗ | ≥80% |
| Top-5 Keyword Accuracy | 50.0% | ✗ | ≥95% |
| Mean Reciprocal Rank (path) | 1.000 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 10.6ms | ≤20ms |
| p95 | 46.2ms | ≤50ms |
| p99 | 52.2ms | ≤100ms |
| mean | 16.9ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| ambiguous | 1 | 100% | 100% | 100% | 53.6ms |
| hybrid | 2 | 100% | 100% | 0% | 0.5ms |
| lexical | 2 | 100% | 100% | 0% | 0.4ms |
| paraphrase | 2 | 100% | 100% | 100% | 23.8ms |
| rerank | 1 | 100% | 100% | 100% | 32.4ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 8 | 100% | 100% | 16.9ms |
