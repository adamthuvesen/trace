# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:14:31.196376+00:00
**Search Mode:** semantic
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 19
**Quick Set Only:** No

**Eval mode:** includes stress queries

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 84.2% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 78.9% | ~ | ≥80% |
| Top-5 Keyword Accuracy | 100.0% | ✓ | ≥95% |
| Mean Reciprocal Rank (path) | 0.921 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 8.9ms | ≤20ms |
| p95 | 11.1ms | ≤50ms |
| p99 | 12.0ms | ≤100ms |
| mean | 8.7ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 62% | 100% | 62% | 8.7ms |
| config | 3 | 100% | 100% | 100% | 8.5ms |
| features | 2 | 100% | 100% | 100% | 8.1ms |
| indexing | 1 | 100% | 100% | 100% | 6.6ms |
| metrics | 2 | 100% | 100% | 50% | 8.6ms |
| search | 2 | 100% | 100% | 100% | 10.7ms |
| troubleshooting | 1 | 100% | 100% | 100% | 9.1ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 84% | 100% | 8.7ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| easy-embeddings | What are embeddings? | config/embedding-backend.md |
| lex-saturation | term frequency saturation document lengt... | glossary/tf-idf.md |
| stress-bm25 | Which bag-of-words scoring model dampens... | glossary/tf-idf.md |
