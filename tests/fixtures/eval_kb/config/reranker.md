# Enabling the reranker

Set **`RERANKER_ENABLED`** to `true` to reorder the top retrieval results with a
cross-encoder before returning them. The flag is off by default and adds latency
per query.
