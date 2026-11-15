<!-- search("BM25 ranking", top_k=3) -->
Found 3 results

## Strategy
- **Selected:** hybrid
- **Fallback used:** yes
- **Reason:** BM25 matched only one document

## Context

### 1. BM25
- **Path:** `glossary/bm25.md`
- **Collection:** docs
- **Folder:** glossary
- **Source:** hybrid

**Snippet 1:** BM25
- **Match evidence:** title matches: bm25; path matches: bm25; breadcrumb matches: bm25
- **Matched terms:** `bm25`, `ranking`
- **Best quote:** Document: BM25 Folder: glossary # BM25 BM25 is a classic **keyword** ranking function for lexical retrieval. It scores bag-of-words queries by combining term frequency saturation with document-length normalization, and is a common baseline when compa...

### 2. Embedding backend
- **Path:** `config/embedding-backend.md`
- **Collection:** docs
- **Folder:** config
- **Source:** hybrid

**Snippet 1:** Embedding backend
- **Match evidence:** hybrid retrieval score: 0.006
- **Best quote:** Document: Embedding backend Folder: config # Embedding backend Set **`EMBEDDING_BACKEND`** to `onnx` for int8 ONNX inference (the default, faster on CPU) or `torch` for the PyTorch path. Both load the same embedding model; only the runtime differs.

### 3. Embedding model
- **Path:** `config/embedding-model.md`
- **Collection:** docs
- **Folder:** config
- **Source:** hybrid

**Snippet 1:** Embedding model
- **Match evidence:** hybrid retrieval score: 0.006
- **Best quote:** Document: Embedding model Folder: config # Embedding model Set **`EMBEDDING_MODEL`** to `all-MiniLM-L6-v2` (the default, 384-dimension) or `BAAI/bge-base-en-v1.5` for higher-quality embeddings at a larger index size. Changing this value requires a forced reindex.

## Suggested Follow-ups
- `get_document(path="glossary/bm25.md", collection="docs")`
- `get_document(path="config/embedding-backend.md", collection="docs")`
- `get_document(path="config/embedding-model.md", collection="docs")`

<!-- keyword_search("embedding model", max_results=3) -->
Found 3 results:

---
### 1. Embedding model
**Path:** `config/embedding-model.md`
**Collection:** docs
**Folder:** config
**BM25 Score:** 11.583

**Preview:**
Document: Embedding model Folder: config # Embedding model Set **`EMBEDDING_MODEL`** to `all-MiniLM-L6-v2` (the default, 384-dimension) or `BAAI/bge-base-en-v1.5` for higher-quality embeddings at a larger index size. Changing this value requires a forced reindex.

---
### 2. Embedding backend
**Path:** `config/embedding-backend.md`
**Collection:** docs
**Folder:** config
**BM25 Score:** 4.691

**Preview:**
Document: Embedding backend Folder: config # Embedding backend Set **`EMBEDDING_BACKEND`** to `onnx` for int8 ONNX inference (the default, faster on CPU) or `torch` for the PyTorch path. Both load the same embedding model; only the runtime differs.

---
### 3. Embeddings
**Path:** `glossary/embeddings.md`
**Collection:** docs
**Folder:** glossary
**BM25 Score:** 2.665

**Preview:**
Document: Embeddings Folder: glossary # Embeddings **Embeddings** map text into dense numeric vectors so that passages with related meaning land near each other in the space. Retrieval then compares vectors instead of raw words, which is what lets it match paraphrases.


<!-- get_document("search/hybrid-search.md") -->
# hybrid-search

**Path:** `search/hybrid-search.md`
**Folder:** search

---

# Hybrid search

**Hybrid search** combines **semantic** vector retrieval with **keyword** (lexical)
signals so you capture both paraphrases and exact terminology.



