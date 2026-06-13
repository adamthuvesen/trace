# Wiki Search Evaluation Report

**Timestamp:** 2026-06-13T10:46:20.718049+00:00
**Search Mode:** bm25
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 13
**Quick Set Only:** No

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 92.3% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 100.0% | ✓ | ≥80% |
| Top-5 Keyword Accuracy | 100.0% | ✓ | ≥95% |
| Mean Reciprocal Rank (path) | 0.962 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 0.1ms | ≤20ms |
| p95 | 4.8ms | ≤50ms |
| p99 | 10.4ms | ≤100ms |
| mean | 1.0ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 4 | 100% | 100% | 100% | 3.1ms |
| config | 5 | 80% | 100% | 100% | 0.1ms |
| docs | 1 | 100% | 100% | 100% | 0.1ms |
| features | 1 | 100% | 100% | 100% | 0.1ms |
| indexing | 1 | 100% | 100% | 100% | 0.1ms |
| troubleshooting | 1 | 100% | 100% | 100% | 0.2ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 13 | 92% | 100% | 1.0ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| easy-kb-path | How do I set KB_PATH? | troubleshooting/conflicting-roots.md |
