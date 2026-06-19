# Wiki Search Evaluation Report

**Timestamp:** 2026-06-19T19:14:32.060933+00:00
**Search Mode:** smart
**Embedding Model:** all-MiniLM-L6-v2
**Total Queries:** 19
**Quick Set Only:** No
**Smart fallback rate:** 78.9%

**Eval mode:** includes stress queries

## Overall Metrics

| Metric | Value | Status | Target |
|--------|-------|--------|--------|
| Top-1 Path Accuracy | 84.2% | ✓ | ≥75% |
| Top-5 Path Accuracy | 100.0% | ✓ | ≥95% |
| Top-1 Keyword Accuracy | 57.9% | ✗ | ≥80% |
| Top-5 Keyword Accuracy | 78.9% | ✗ | ≥95% |
| Mean Reciprocal Rank (path) | 0.921 | - | - |
| Within max_rank Path | 100.0% | - | - |

## Latency

| Percentile | Value | Target |
|------------|-------|--------|
| p50 | 9.0ms | ≤20ms |
| p95 | 17.2ms | ≤50ms |
| p99 | 17.9ms | ≤100ms |
| mean | 8.9ms | - |

## By Category

| Category | Queries | Top-1 Path | Top-5 Path | Top-1 KW | Latency |
|----------|---------|------------|------------|----------|---------|
| concepts | 8 | 62% | 100% | 62% | 12.3ms |
| config | 3 | 100% | 100% | 0% | 0.3ms |
| features | 2 | 100% | 100% | 100% | 8.7ms |
| indexing | 1 | 100% | 100% | 100% | 11.4ms |
| metrics | 2 | 100% | 100% | 50% | 9.5ms |
| search | 2 | 100% | 100% | 100% | 10.4ms |
| troubleshooting | 1 | 100% | 100% | 0% | 0.1ms |

## By File Type

| Type | Queries | Top-1 | Top-5 | Latency |
|------|---------|-------|-------|---------|
| .md | 19 | 84% | 100% | 8.9ms |

## Failed Queries (Top-1 Miss)

| Query ID | Query | Retrieved Path |
|----------|-------|----------------|
| easy-embeddings | What are embeddings? | config/embedding-backend.md |
| lex-saturation | term frequency saturation document lengt... | glossary/tf-idf.md |
| stress-bm25 | Which bag-of-words scoring model dampens... | glossary/tf-idf.md |
