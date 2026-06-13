# Wiki Search Evaluation Report

**Timestamp:** 2026-06-13T11:15:49.228423+00:00
**Search Mode:** semantic
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
| p50 | 6.7ms | ≤20ms |
| p95 | 7.1ms | ≤50ms |
| p99 | 7.3ms | ≤100ms |
| mean | 6.8ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 6 | 67% | 100% | 67% | 6.9ms |
| config | 3 | 100% | 100% | 100% | 6.6ms |
| features | 2 | 100% | 100% | 100% | 6.8ms |
| indexing | 1 | 100% | 100% | 100% | 6.4ms |
| metrics | 2 | 100% | 100% | 50% | 6.7ms |
| search | 2 | 100% | 100% | 100% | 6.7ms |
| troubleshooting | 1 | 100% | 100% | 100% | 6.7ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 17 | 88% | 100% | 6.8ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| easy-embeddings | What are embeddings? | config/embedding-backend.md |
| lex-saturation | term frequency saturation document lengt... | glossary/tf-idf.md |
