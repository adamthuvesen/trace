# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:14:32.592009+00:00
**Search Mode:** bm25
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 8
**Quick Set Only:** No

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 100.0% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 0.0% | ✗ | ≥80% |
| Top-5 Keyword Accuracy | 0.0% | ✗ | ≥95% |
| Mean Reciprocal Rank (path) | 1.000 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 0.3ms | ≤20ms |
| p95 | 1.0ms | ≤50ms |
| p99 | 1.2ms | ≤100ms |
| mean | 0.4ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| ambiguous | 1 | 100% | 100% | 0% | 0.3ms |
| hybrid | 2 | 100% | 100% | 0% | 0.2ms |
| lexical | 2 | 100% | 100% | 0% | 0.8ms |
| paraphrase | 2 | 100% | 100% | 0% | 0.2ms |
| rerank | 1 | 100% | 100% | 0% | 0.5ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 8 | 100% | 100% | 0.4ms |
