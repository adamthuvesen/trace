# Wiki Search Evaluation Report

**Timestamp:** 2026-06-13T11:15:55.846202+00:00
**Search Mode:** smart
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 17
**Quick Set Only:** No
**Smart fallback rate:** 76.5%

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 88.2% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 82.4% | ✓ | ≥80% |
| Top-5 Keyword Accuracy | 100.0% | ✓ | ≥95% |
| Mean Reciprocal Rank (path) | 0.941 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 7.2ms | ≤20ms |
| p95 | 10.6ms | ≤50ms |
| p99 | 19.1ms | ≤100ms |
| mean | 6.5ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 6 | 67% | 100% | 67% | 9.7ms |
| config | 3 | 100% | 100% | 100% | 0.2ms |
| features | 2 | 100% | 100% | 100% | 7.6ms |
| indexing | 1 | 100% | 100% | 100% | 7.4ms |
| metrics | 2 | 100% | 100% | 50% | 7.3ms |
| search | 2 | 100% | 100% | 100% | 7.1ms |
| troubleshooting | 1 | 100% | 100% | 100% | 0.2ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 17 | 88% | 100% | 6.5ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| easy-embeddings | What are embeddings? | config/embedding-backend.md |
| lex-saturation | term frequency saturation document lengt... | glossary/tf-idf.md |
