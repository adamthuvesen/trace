"""Document indexer for wiki knowledge base (public re-exports)."""

import bm25s  # noqa: F401 — patched in tests via trace_search.indexer
import chromadb  # noqa: F401 — patched in tests via trace_search.indexer

from trace_search.extraction.chunking import (
    TokenCounter,
    chunk_by_headings,
    chunk_by_paragraphs,
    create_contextual_chunk,
)
from trace_search.extraction.chunking import (  # noqa: F401 — test_chunking imports via indexer
    _get_overlap_text,
    _get_size,
    _get_token_counter,
)
from trace_search.indexing.embeddings import build_embedding_backend  # noqa: F401
from trace_search.extraction.extractors import (
    SUPPORTED_EXTENSIONS,
    SUPPORTED_EXTENSIONS_ORDERED,
    extract_code_content,
    extract_content,
    extract_csv_content,
    extract_docx_content,
    extract_notebook_content,
    extract_pdf_content,
    extract_pptx_content,
    extract_title,
)
from trace_search.indexing.kb_paths import get_default_index_root, should_exclude_path
from trace_search.indexing.wiki_indexer import WikiIndexer

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "SUPPORTED_EXTENSIONS_ORDERED",
    "WikiIndexer",
    "TokenCounter",
    "bm25s",
    "chromadb",
    "build_embedding_backend",
    "extract_title",
    "extract_content",
    "extract_pdf_content",
    "extract_docx_content",
    "extract_pptx_content",
    "extract_csv_content",
    "extract_code_content",
    "extract_notebook_content",
    "get_default_index_root",
    "should_exclude_path",
    "chunk_by_headings",
    "chunk_by_paragraphs",
    "create_contextual_chunk",
    "_get_overlap_text",
    "_get_size",
    "_get_token_counter",
]
