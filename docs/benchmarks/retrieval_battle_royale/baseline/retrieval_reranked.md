# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:14:31.884312+00:00
**Search Mode:** reranked
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
| p50 | 17.9ms | ≤20ms |
| p95 | 72.9ms | ≤50ms |
| p99 | 90.1ms | ≤100ms |
| mean | 25.3ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 62% | 100% | 62% | 33.3ms |
| config | 3 | 100% | 100% | 100% | 23.3ms |
| features | 2 | 100% | 100% | 100% | 14.5ms |
| indexing | 1 | 100% | 100% | 100% | 37.3ms |
| metrics | 2 | 100% | 100% | 50% | 13.7ms |
| search | 2 | 100% | 100% | 100% | 18.0ms |
| troubleshooting | 1 | 100% | 100% | 100% | 13.9ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 84% | 100% | 25.3ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| easy-embeddings | What are embeddings? | config/embedding-backend.md |
| lex-saturation | term frequency saturation document lengt... | glossary/tf-idf.md |
| stress-bm25 | Which bag-of-words scoring model dampens... | glossary/tf-idf.md |
