"""Multi-collection orchestration for Trace."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from trace_search.config import settings
from trace_search.corpus import iter_kb_files
from trace_search.diagnostics import diagnose_collections, render_doctor_report
from trace_search.embeddings import EmbeddingBackend, build_embedding_backend
from trace_search.extractors import SUPPORTED_EXTENSIONS, extract_content, extract_title
from trace_search.index_metadata import metadata_matches_active_model, read_index_metadata
from trace_search.index_paths import bm25_dir, chroma_dir
from trace_search.kb_paths import get_default_index_root, should_exclude_path
from trace_search.search import (
    HybridSearch,
    KeywordSearch,
    SearchFilters,
    SemanticSearch,
    SmartSearch,
)
from trace_search.search_types import SearchRoute, SmartSearchResult
from trace_search.server_warmup import warm_embedding_model
from trace_search.wiki_indexer import WikiIndexer

logger = logging.getLogger(__name__)

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 500

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
                chroma_path=chroma_dir(self.index_path, model_slug),
                bm25_path=bm25_dir(self.index_path, model_slug),
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

    def get_smart(
        self,
        backend: EmbeddingBackend | None = None,
        *,
        skip_build: bool = False,
    ) -> SmartSearch:
        if skip_build:
            indexer = self.ensure_index(backend, skip_build=True)
            return SmartSearch(indexer, indexer.backend)
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
        """Batch-fetch neighbor content via the collection indexer."""
        indexer = self.ensure_index(backend)
        return indexer.neighbor_contents_batch(requests)


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

    def _search(
        self,
        mode: str,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> list[dict] | SmartSearchResult:
        if mode == "smart":
            return self.search_smart(query, top_k, collection, filters=filters)
        filters = filters or SearchFilters()
        cols = self._resolve(collection)

        def run_on(col: Collection) -> list[dict]:
            if mode == "keyword":
                return col.get_keyword(self.backend).search(
                    query, top_k, filters=filters
                )
            if mode == "semantic":
                return col.get_semantic(self.backend).search(
                    query, top_k, filters=filters
                )
            if mode == "hybrid":
                return col.get_hybrid(self.backend).search(
                    query, top_k, filters=filters
                )
            raise ValueError(f"Unknown search mode: {mode}")

        if len(cols) == 1:
            return run_on(cols[0])
        return self._merge_results(
            [run_on(col) for col in cols],
            top_k,
            [c.name for c in cols],
        )

    def search_keyword(
        self,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        result = self._search("keyword", query, top_k, collection, filters)
        assert isinstance(result, list)
        return result

    def search_semantic(
        self,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        result = self._search("semantic", query, top_k, collection, filters)
        assert isinstance(result, list)
        return result

    def search_hybrid(
        self,
        query: str,
        top_k: int,
        collection: str | None,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        result = self._search("hybrid", query, top_k, collection, filters)
        assert isinstance(result, list)
        return result

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
        """Run a sample query only when indexes already exist and match settings."""
        model_slug = settings.model_slug
        missing = []
        incompatible = []
        for col in self._resolve(collection):
            chroma_path = chroma_dir(col.index_path, model_slug)
            bm25_path = bm25_dir(col.index_path, model_slug)
            if not chroma_path.exists() or not bm25_path.exists():
                missing.append(col.name)
                continue
            metadata = read_index_metadata(col.index_path)
            if metadata is None or not metadata_matches_active_model(metadata):
                incompatible.append(col.name)
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(
                f"Sample query skipped because indexes are missing for: {names}. "
                "Run `reindex` first."
            )
        if incompatible:
            names = ", ".join(sorted(incompatible))
            raise ValueError(
                f"Sample query skipped because indexes are incompatible or missing "
                f"metadata for: {names}. Run `reindex` first."
            )
        cols = self._resolve(collection)
        if len(cols) == 1:
            result = cols[0].get_smart(self.backend, skip_build=True).search(
                query,
                top_k,
            )
            return result.hits

        results = [
            c.get_smart(self.backend, skip_build=True).search(query, top_k)
            for c in cols
        ]
        return self._merge_results(
            [result.hits for result in results],
            top_k,
            [c.name for c in cols],
        )

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

            for file_path in iter_kb_files(kb, root=search_path):
                ext = file_path.suffix.lower()
                rel_path = str(file_path.relative_to(kb))
                try:
                    mtime = file_path.stat().st_mtime
                except OSError:
                    continue
                if not filters.matches_record(rel_path, ext, mtime):
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
