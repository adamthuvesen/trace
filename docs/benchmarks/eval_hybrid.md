# Wiki Search Evaluation Report

**Timestamp:** 2026-06-13T11:15:52.565971+00:00
**Search Mode:** hybrid
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 17
**Quick Set Only:** No

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
| p50 | 7.1ms | ≤20ms |
| p95 | 10.9ms | ≤50ms |
| p99 | 16.0ms | ≤100ms |
| mean | 7.8ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 6 | 67% | 100% | 67% | 9.2ms |
| config | 3 | 100% | 100% | 100% | 7.0ms |
| features | 2 | 100% | 100% | 100% | 7.0ms |
| indexing | 1 | 100% | 100% | 100% | 7.5ms |
| metrics | 2 | 100% | 100% | 50% | 7.0ms |
| search | 2 | 100% | 100% | 100% | 7.0ms |
| troubleshooting | 1 | 100% | 100% | 100% | 7.0ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 17 | 88% | 100% | 7.8ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| easy-embeddings | What are embeddings? | config/embedding-backend.md |
| lex-saturation | term frequency saturation document lengt... | glossary/tf-idf.md |
