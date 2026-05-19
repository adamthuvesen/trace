"""MCP server builder for multi-collection knowledge base search."""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from trace_search.config import settings, configure_logging
from trace_search.embeddings import EmbeddingBackend, build_embedding_backend
from trace_search.diagnostics import diagnose_collections, render_doctor_report
from trace_search.indexer import (
    SUPPORTED_EXTENSIONS,
    WikiIndexer,
    extract_content,
    extract_title,
    get_default_index_root,
    should_exclude_path,
)
from trace_search.search import (
    HybridSearch,
    KeywordSearch,
    SearchFilters,
    SearchRoute,
    SemanticSearch,
    SmartSearch,
    SmartSearchResult,
)

configure_logging()
logger = logging.getLogger(__name__)
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 500

# Varying-length English sentences used to trigger PyTorch kernel compilation
# across the token-length distribution seen in real queries. Discarded after encode.
_WARMUP_SENTENCES: tuple[str, ...] = (
    "x",
    "hello world",
    "what is an acronym",
    "how do we document recurring service reviews at the end of a cycle",
    "explain the onboarding checklist for a new workspace in detail",
)


def warm_embedding_model(backend: EmbeddingBackend) -> float | None:
    """Pre-encode a fixed batch to prime the runtime before live queries.

    Returns elapsed milliseconds, or None if warmup is disabled. Calls
    `backend.encode` directly — must not route through any query cache.
    """
    if not settings.embedding_warmup_enabled:
        return None
    start = time.perf_counter()
    backend.encode(list(_WARMUP_SENTENCES))
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("Embedding model warmed in %.1f ms", elapsed_ms)
    return elapsed_ms


@dataclass
class Collection:
    """A lazily-initialized knowledge base collection with its own indexes."""

    name: str
    kb_path: Path
    index_path: Path
    _indexer: WikiIndexer | None = field(default=None, repr=False)
    _semantic: SemanticSearch | None = field(default=None, repr=False)
    _keyword: KeywordSearch | None = field(default=None, repr=False)
    _hybrid: HybridSearch | None = field(default=None, repr=False)
    _smart: SmartSearch | None = field(default=None, repr=False)

    def reset(self) -> None:
        """Clear all cached search components so they are rebuilt on next access."""
        self._indexer = None
        self._semantic = None
        self._keyword = None
        self._hybrid = None
        self._smart = None

    def ensure_index(
        self,
        backend: EmbeddingBackend | None = None,
        *,
        skip_build: bool = False,
    ) -> WikiIndexer:
        if self._indexer is None:
            model_slug = settings.model_slug
            self._indexer = WikiIndexer(
                kb_path=self.kb_path,
                chroma_path=self.index_path / f".chroma_db_{model_slug}",
                bm25_path=self.index_path / f".bm25_index_{model_slug}",
                backend=backend,
            )
            if not skip_build:
                self._indexer.build_index()
        return self._indexer

    def get_semantic(self, backend: EmbeddingBackend | None = None) -> SemanticSearch:
        if self._semantic is None:
            indexer = self.ensure_index(backend)
            self._semantic = SemanticSearch(indexer.collection, indexer.backend)
        return self._semantic

    def get_keyword(self, backend: EmbeddingBackend | None = None) -> KeywordSearch:
        if self._keyword is None:
            self._keyword = KeywordSearch(self.ensure_index(backend))
        return self._keyword

    def get_hybrid(self, backend: EmbeddingBackend | None = None) -> HybridSearch:
        if self._hybrid is None:
            indexer = self.ensure_index(backend)
            self._hybrid = HybridSearch(indexer, indexer.backend)
        return self._hybrid

    def get_smart(self, backend: EmbeddingBackend | None = None) -> SmartSearch:
        if self._smart is None:
            indexer = self.ensure_index(backend)
            self._smart = SmartSearch(indexer, indexer.backend)
        return self._smart

    def get_neighbor_content(
        self,
        path: str,
        chunk_index: int | None,
        chunk_count: int | None,
        backend: EmbeddingBackend | None = None,
    ) -> str | None:
        """Fetch bounded neighboring chunk content for richer context packets."""
        return self.get_neighbor_contents_batch(
            [(path, chunk_index, chunk_count)],
            backend,
        )[0]

    def get_neighbor_contents_batch(
        self,
        requests: list[tuple[str, int | None, int | None]],
        backend: EmbeddingBackend | None = None,
    ) -> list[str | None]:
        """Batch-fetch neighbor content for many `(path, chunk_index, chunk_count)`
        triples in a single ChromaDB `get()` call.

        Returns a list aligned with `requests`; entries are `None` when a hit has no
        valid neighbors or none could be found.
        """
        request_ids: list[list[str]] = []
        all_ids: set[str] = set()
        for path, chunk_index, chunk_count in requests:
            if chunk_index is None or chunk_count is None or chunk_count <= 1:
                request_ids.append([])
                continue
            ids = [
                f"{path}::{i}"
                for i in (chunk_index - 1, chunk_index + 1)
                if 0 <= i < chunk_count
            ]
            request_ids.append(ids)
            all_ids.update(ids)

        if not all_ids:
            return [None] * len(requests)

        indexer = self.ensure_index(backend)
        results = indexer.collection.get(
            ids=list(all_ids),
            include=["documents", "metadatas"],
        )
        id_to_doc: dict[str, str] = {}
        for chunk_id, doc in zip(
            results.get("ids") or [],
            results.get("documents") or [],
        ):
            if doc:
                id_to_doc[chunk_id] = str(doc)

        output: list[str | None] = []
        for ids in request_ids:
            docs = [id_to_doc[cid] for cid in ids if cid in id_to_doc]
            output.append("\n\n".join(docs) if docs else None)
        return output

    def rebuild(
        self,
        backend: EmbeddingBackend | None = None,
        *,
        force: bool = False,
    ) -> int:
        """Reindex this collection and return the resulting chunk count.

        Default is incremental: only added, changed, and removed files are
        reprocessed and cached search components remain valid. Pass
        `force=True` to drop the indexes and rebuild every file from scratch;
        cached search components are cleared so they pick up the new state.
        """
        if force:
            self.reset()
        indexer = self.ensure_index(backend, skip_build=True)
        return indexer.build_index(force=force)


class CollectionRegistry:
    """Manages multiple knowledge base collections with a shared embedding model."""

    def __init__(self, collections: dict[str, Path], index_root: Path | None = None):
        self._backend: EmbeddingBackend | None = None
        self._warmed: bool = False
        idx_root = index_root or (settings.index_path if settings.index_path else None)
        self._index_root = idx_root

        self.collections: dict[str, Collection] = {}
        for name, kb_path in collections.items():
            col_index = get_default_index_root(
                kb_path, idx_root, name if idx_root else None
            )
            self.collections[name] = Collection(
                name=name,
                kb_path=kb_path,
                index_path=col_index,
            )

    @property
    def collection_names(self) -> list[str]:
        return sorted(self.collections.keys())

    @property
    def backend(self) -> EmbeddingBackend:
        if self._backend is None:
            self._backend = build_embedding_backend()
            self._warm_backend()
        return self._backend

    def _warm_backend(self) -> None:
        """Warm the shared embedding backend exactly once per registry lifecycle."""
        if self._warmed:
            return
        assert self._backend is not None
        warm_embedding_model(self._backend)
        self._warmed = True

    def _resolve(self, collection: str | None) -> list[Collection]:
        """Resolve collection name to list of Collection objects."""
        if collection and collection.lower() != "all":
            col = self.collections.get(collection)
            if col is None:
                raise ValueError(
                    f"Unknown collection '{collection}'. "
                    f"Available: {', '.join(self.collection_names)}"
                )
            return [col]
        return list(self.collections.values())

    def search_keyword(
        self,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        filters = filters or SearchFilters()
        cols = self._resolve(collection)
        if len(cols) == 1:
            return cols[0].get_keyword(self.backend).search(
                query, top_k, filters=filters
            )
        return self._merge_results(
            [
                c.get_keyword(self.backend).search(query, top_k, filters=filters)
                for c in cols
            ],
            top_k,
            [c.name for c in cols],
        )

    def search_semantic(
        self,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        filters = filters or SearchFilters()
        cols = self._resolve(collection)
        if len(cols) == 1:
            return cols[0].get_semantic(self.backend).search(
                query, top_k, filters=filters
            )
        return self._merge_results(
            [
                c.get_semantic(self.backend).search(query, top_k, filters=filters)
                for c in cols
            ],
            top_k,
            [c.name for c in cols],
        )

    def search_hybrid(
        self,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        filters = filters or SearchFilters()
        cols = self._resolve(collection)
        if len(cols) == 1:
            return cols[0].get_hybrid(self.backend).search(
                query, top_k, filters=filters
            )
        return self._merge_results(
            [
                c.get_hybrid(self.backend).search(query, top_k, filters=filters)
                for c in cols
            ],
            top_k,
            [c.name for c in cols],
        )

    def search_smart(
        self,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> SmartSearchResult:
        filters = filters or SearchFilters()
        cols = self._resolve(collection)
        if len(cols) == 1:
            result = cols[0].get_smart(self.backend).search(
                query, top_k, filters=filters
            )
            hits = [
                self._with_neighbor_context(cols[0], hit)
                for hit in result.hits
            ]
            return SmartSearchResult(hits=hits, route=result.route)

        results = [
            c.get_smart(self.backend).search(query, top_k, filters=filters)
            for c in cols
        ]
        merged_hits = self._merge_results(
            [result.hits for result in results],
            top_k,
            [c.name for c in cols],
        )
        self._attach_neighbors_batched(merged_hits, cols)
        fallback_used = any(result.route.fallback_used for result in results)
        strategy = "hybrid" if fallback_used else "keyword"
        reasons = sorted({result.route.reason for result in results})
        return SmartSearchResult(
            hits=merged_hits,
            route=SearchRoute(
                strategy=strategy,
                reason="; ".join(reasons),
                fallback_used=fallback_used,
                filters=filters,
            ),
        )

    def probe_search(self, query: str, top_k: int, collection: str | None) -> list[dict]:
        """Run a sample query only when indexes already exist."""
        model_slug = settings.model_slug
        missing = []
        for col in self._resolve(collection):
            chroma_path = col.index_path / f".chroma_db_{model_slug}"
            bm25_path = col.index_path / f".bm25_index_{model_slug}"
            if not chroma_path.exists() or not bm25_path.exists():
                missing.append(col.name)
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(
                f"Sample query skipped because indexes are missing for: {names}. "
                "Run `reindex` first."
            )
        return self.search_smart(query, top_k, collection).hits

    def _with_neighbor_context(self, col: Collection, hit: dict) -> dict:
        enriched = hit.copy()
        if "neighbor_content" not in enriched:
            enriched["neighbor_content"] = col.get_neighbor_content(
                str(enriched.get("path", "")),
                enriched.get("chunk_index"),
                enriched.get("chunk_count"),
                self.backend,
            )
        return enriched

    def _attach_neighbors_batched(
        self, hits: list[dict], cols: list[Collection]
    ) -> None:
        """Group `hits` by their `collection` tag and issue one batched neighbor
        fetch per collection. Mutates each hit in place to set `neighbor_content`.
        """
        col_by_name = {c.name: c for c in cols}
        by_collection: dict[str, list[dict]] = defaultdict(list)
        for hit in hits:
            if "neighbor_content" in hit:
                continue
            col_name = hit.get("collection")
            if col_name in col_by_name:
                by_collection[col_name].append(hit)

        for col_name, col_hits in by_collection.items():
            col = col_by_name[col_name]
            requests = [
                (
                    str(h.get("path", "")),
                    h.get("chunk_index"),
                    h.get("chunk_count"),
                )
                for h in col_hits
            ]
            neighbors = col.get_neighbor_contents_batch(requests, self.backend)
            for hit, neighbor in zip(col_hits, neighbors):
                hit["neighbor_content"] = neighbor

    @staticmethod
    def _merge_results(
        result_lists: list[list[dict]],
        top_k: int,
        collection_names: list[str],
    ) -> list[dict]:
        """Interleave results from multiple collections by score, tag with collection name."""
        tagged: list[dict] = []
        for results, name in zip(result_lists, collection_names):
            for hit in results:
                hit = hit.copy()
                hit["collection"] = name
                tagged.append(hit)
        tagged.sort(
            key=lambda h: h.get("rrf_score", h.get("score", 0)),
            reverse=True,
        )
        return tagged[:top_k]

    def get_document(self, path: str, collection: str | None) -> str:
        cols = self._resolve(collection)
        for col in cols:
            kb = col.kb_path.resolve()
            doc_path = (kb / path).resolve()
            if not doc_path.is_relative_to(kb):
                logger.warning(
                    "get_document: rejected traversal attempt (path=%s, kb=%s)",
                    path,
                    kb,
                )
                continue
            if should_exclude_path(doc_path, kb):
                logger.warning(
                    "get_document: rejected excluded path (path=%s, kb=%s)",
                    path,
                    kb,
                )
                continue
            if doc_path.exists() and doc_path.is_file():
                try:
                    content = extract_content(doc_path)
                except ValueError as exc:
                    return f"Error: {exc}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                except Exception as exc:
                    logger.warning(
                        "get_document: extraction failed (path=%s, reason=%s)",
                        path,
                        exc,
                    )
                    return f"Error reading document: {path}"
                folder = path.split("/")[0] if "/" in path else ""
                col_label = (
                    f"**Collection:** {col.name}\n" if len(self.collections) > 1 else ""
                )
                return f"# {doc_path.stem}\n\n**Path:** `{path}`\n{col_label}**Folder:** {folder}\n\n---\n\n{content}\n"
        return f"Document not found: {path}"

    def list_documents(
        self,
        folder: str | None,
        limit: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> str:
        if limit < 1:
            limit = DEFAULT_LIST_LIMIT
        limit = min(limit, MAX_LIST_LIMIT)
        filters = filters or SearchFilters()
        since_epoch = (
            filters.since.timestamp() if filters.since is not None else None
        )
        extensions_filter = set(filters.extensions)
        prefixes = filters.path_prefix
        cols = self._resolve(collection)
        all_docs: list[dict[str, str]] = []

        for col in cols:
            kb = col.kb_path.resolve()
            search_path = kb

            if folder:
                candidate = (kb / folder).resolve()
                if not candidate.is_relative_to(kb):
                    continue
                if candidate.exists():
                    search_path = candidate
                else:
                    for directory in sorted(kb.iterdir(), key=lambda p: p.name.lower()):
                        if (
                            directory.is_dir()
                            and directory.name.lower() == folder.lower()
                        ):
                            search_path = directory
                            break
                    else:
                        continue

            for file_path in search_path.rglob("*"):
                ext = file_path.suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                if should_exclude_path(file_path, kb):
                    continue
                rel_path = str(file_path.relative_to(kb))
                if extensions_filter and ext not in extensions_filter:
                    continue
                if prefixes and not any(
                    rel_path.startswith(prefix) for prefix in prefixes
                ):
                    continue
                if since_epoch is not None:
                    try:
                        if file_path.stat().st_mtime < since_epoch:
                            continue
                    except OSError:
                        continue
                if ext == ".md":
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        title = extract_title(content, file_path)
                    except Exception:
                        title = file_path.stem
                else:
                    title = file_path.stem
                path_parts = rel_path.split("/")
                doc_folder = path_parts[0] if len(path_parts) > 1 else ""
                doc: dict[str, str] = {
                    "title": title,
                    "path": rel_path,
                    "folder": doc_folder,
                }
                if len(cols) > 1:
                    doc["collection"] = col.name
                all_docs.append(doc)

        if not all_docs:
            return "No documents found."

        all_docs = sorted(all_docs, key=lambda d: (d.get("collection", ""), d["path"]))
        all_docs = all_docs[:limit]

        lines = [
            f"Found {len(all_docs)} documents"
            + (f" in {folder}" if folder else "")
            + ":\n"
        ]
        by_folder: dict[str, list[dict[str, str]]] = defaultdict(list)
        for doc in all_docs:
            key = (
                doc.get("collection", "") + "/" + (doc["folder"] or "(root)")
                if len(cols) > 1
                else doc["folder"] or "(root)"
            )
            by_folder[key].append(doc)

        for folder_name, folder_docs in sorted(by_folder.items()):
            lines.append(f"\n## {folder_name}")
            for doc in folder_docs:
                lines.append(f"- **{doc['title']}**: `{doc['path']}`")

        return "\n".join(lines)

    def reindex(self, collection: str | None, force: bool = False) -> str:
        """Reindex the given collection(s); incremental by default."""
        cols = self._resolve(collection)
        results = []
        for col in cols:
            chunks = col.rebuild(self.backend, force=force)
            suffix = " (forced rebuild)" if force else ""
            results.append(f"**{col.name}**: {chunks} chunks indexed{suffix}")
        return "Reindex complete.\n\n" + "\n".join(results)

    def doctor(
        self,
        sample_query: str | None = None,
        collection: str | None = None,
    ) -> str:
        """Run Trace diagnostics for configuration, corpus, indexes, and queries."""
        report = diagnose_collections(
            {name: col.kb_path for name, col in self.collections.items()},
            index_root=self._index_root,
            sample_query=sample_query,
            sample_collection=collection,
            sample_query_runner=lambda query, col_name: self.probe_search(
                query,
                5,
                col_name,
            ),
        )
        return render_doctor_report(report)

    def index_stats(self, collection: str | None) -> str:
        cols = self._resolve(collection)
        sections = []
        cache_stats = SemanticSearch.get_cache_stats()

        for col in cols:
            indexer = col.ensure_index(self.backend, skip_build=True)
            stats = indexer.get_stats()
            chunking = stats.get("chunking", {})

            if chunking.get("use_tokens"):
                chunk_mode = f"token-based (max {chunking.get('token_chunk_size', settings.token_chunk_size)} tokens)"
            else:
                chunk_mode = f"character-based (max {chunking.get('char_chunk_size', settings.char_chunk_size)} chars)"

            if chunking.get("enable_overlap"):
                if chunking.get("use_tokens"):
                    overlap_info = f"enabled ({chunking.get('token_overlap_size', settings.token_overlap_size)} tokens)"
                else:
                    overlap_info = f"enabled ({chunking.get('char_overlap_size', settings.char_overlap_size)} chars)"
            else:
                overlap_info = "disabled"

            sections.append(f"""## Collection: {col.name}

- **Knowledge base:** `{stats["kb_path"]}`
- **ChromaDB chunks:** {stats["total_chunks"]}
- **BM25 documents:** {stats["bm25_docs"]}
- **BM25 available:** {stats["bm25_available"]}
- **Chunking:** {chunk_mode}, overlap {overlap_info}
- **ChromaDB path:** `{stats["chroma_path"]}`
- **BM25 path:** `{stats["bm25_path"]}`""")

        return f"""# Index Statistics

{chr(10).join(sections)}

## Shared
- **Embedding model:** {settings.embedding_model} (dims={settings.embedding_dims})
- **Embedding backend:** {settings.embedding_backend}
- **Reranker:** {settings.reranker_model} (enabled={settings.reranker_enabled})
- **Cache:** {cache_stats["cache_size"]}/{cache_stats["cache_maxsize"]} (hit rate: {cache_stats["cache_hit_rate"]})
"""


def _build_multi_instructions(collection_names: list[str]) -> str:
    """Generate dynamic instructions listing available collections."""
    names = ", ".join(f'"{c}"' for c in collection_names)
    return f"""Knowledge search server with multiple collections: {names}.

Use these tools to search across knowledge bases:
- search: **DEFAULT** - Smart BM25-first search with semantic/hybrid fallback
- semantic_search: Find documents by meaning/concept (for vague natural language)
- search_hybrid: Combined semantic + keyword with ranking (slower, use if search fails)
- get_document: Retrieve full document content
- list_documents: Browse available documents by folder
- doctor: Diagnose configuration, visible documents, index health, and sample queries
- reindex: Update indexes after adding or changing documents (incremental; pass force=true to rebuild)

All search tools accept an optional `collection` parameter to target a specific
knowledge base. Omit it or pass "all" to search across all collections.

Start with `search` for most queries. It reports which strategy won and suggests
useful `get_document` follow-ups for top results.
"""


def build_multi_mcp(
    server_name: str,
    collections: dict[str, Path],
    index_root: Path | None = None,
    instructions: str | None = None,
) -> tuple[FastMCP, dict[str, Any]]:
    """Build a multi-collection FastMCP server.

    Args:
        server_name: Name for the MCP server.
        collections: Mapping of collection name to knowledge base path.
        index_root: Shared root for index storage. If None, indexes are stored
            inside each KB under .mcp-search/indexes/.
        instructions: Custom server instructions. Auto-generated if None.
    """
    from trace_search.operations import TraceOperations

    registry = CollectionRegistry(collections, index_root)
    operations = TraceOperations(registry)

    if instructions is None:
        instructions = _build_multi_instructions(registry.collection_names)

    mcp = FastMCP(server_name, instructions=instructions)

    _FILTER_HELP = (
        "Optional filters scope results before ranking: `path_prefix` (string "
        "or list of relative-path prefixes), `extensions` (list of suffixes "
        "like `.md` or `.py`), and `since` (ISO 8601 datetime; only files "
        "modified at or after this time)."
    )

    @mcp.tool()
    def search(
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        path_prefix: list[str] | None = None,
        extensions: list[str] | None = None,
        since: str | None = None,
    ) -> str:
        """Search knowledge bases. This is the default and recommended search tool.

        Starts with fast BM25 keyword matching, then falls back when results are weak.
        Set `collection` to target a specific knowledge base, or omit to search all.
        Optional filters scope results before ranking:
        - `path_prefix`: list of relative-path prefixes (e.g. ["architecture/"]).
        - `extensions`: list of file suffixes like [".md", ".py"].
        - `since`: ISO 8601 datetime; only files modified at or after this time.
        """
        return operations.search(
            query,
            top_k,
            collection,
            path_prefix=path_prefix,
            extensions=extensions,
            since=since,
        )

    @mcp.tool()
    def semantic_search(
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        path_prefix: list[str] | None = None,
        extensions: list[str] | None = None,
        since: str | None = None,
    ) -> str:
        """Search knowledge bases by semantic similarity.

        Use when `search` doesn't find what you need, especially for vague
        conceptual questions. Set `collection` to target a specific knowledge base.
        Same `path_prefix` / `extensions` / `since` filters as `search`.
        """
        return operations.semantic_search(
            query,
            top_k,
            collection,
            path_prefix=path_prefix,
            extensions=extensions,
            since=since,
        )

    @mcp.tool()
    def keyword_search(
        keyword: str,
        max_results: int = 20,
        collection: str | None = None,
        path_prefix: list[str] | None = None,
        extensions: list[str] | None = None,
        since: str | None = None,
    ) -> str:
        """Alias for `search`. Use `search` instead — it's the same BM25 engine.

        Same `path_prefix` / `extensions` / `since` filters as `search`.
        """
        return operations.keyword_search(
            keyword,
            max_results,
            collection,
            path_prefix=path_prefix,
            extensions=extensions,
            since=since,
        )

    @mcp.tool()
    def search_hybrid(
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        path_prefix: list[str] | None = None,
        extensions: list[str] | None = None,
        since: str | None = None,
    ) -> str:
        """Combined semantic + keyword search. Use as fallback if `search` fails.

        Same `path_prefix` / `extensions` / `since` filters as `search`.
        """
        return operations.search_hybrid(
            query,
            top_k,
            collection,
            path_prefix=path_prefix,
            extensions=extensions,
            since=since,
        )

    @mcp.tool()
    def get_document(path: str, collection: str | None = None) -> str:
        """Retrieve full content of a document. Set `collection` to disambiguate."""
        return operations.get_document(path, collection)

    @mcp.tool()
    def list_documents(
        folder: str | None = None,
        limit: int = 50,
        collection: str | None = None,
        path_prefix: list[str] | None = None,
        extensions: list[str] | None = None,
        since: str | None = None,
    ) -> str:
        """List available documents. Set `collection` to filter by knowledge base.

        Same `path_prefix` / `extensions` / `since` filters as the search tools;
        `since` only matches if the file's mtime is at or after the given ISO 8601 datetime.
        """
        return operations.list_documents(
            folder,
            limit,
            collection,
            path_prefix=path_prefix,
            extensions=extensions,
            since=since,
        )

    @mcp.tool()
    def index_stats(collection: str | None = None) -> str:
        """Get statistics about search indexes. Set `collection` for a specific one."""
        return operations.index_stats(collection)

    @mcp.tool()
    def reindex(collection: str | None = None, force: bool = False) -> str:
        """Update search indexes after adding or changing documents.

        Default is incremental: only added, changed, and removed files are
        reprocessed; unchanged files are skipped entirely. Pass `force=True`
        to drop both indexes and rebuild every file from scratch (slower,
        useful after upgrading models or recovering from corruption). Set
        `collection` to reindex a specific knowledge base, or omit for all.
        """
        return operations.reindex(collection, force=force)

    @mcp.tool()
    def doctor(
        sample_query: str | None = None,
        collection: str | None = None,
    ) -> str:
        """Diagnose Trace configuration, corpus visibility, index health, and queries."""
        return operations.doctor(sample_query=sample_query, collection=collection)

    return mcp, {
        "search": search,
        "semantic_search": semantic_search,
        "keyword_search": keyword_search,
        "search_hybrid": search_hybrid,
        "get_document": get_document,
        "list_documents": list_documents,
        "index_stats": index_stats,
        "reindex": reindex,
        "doctor": doctor,
    }
