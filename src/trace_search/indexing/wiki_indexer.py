"""Build and serve the BM25 + embedding index for one local knowledge base."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

import numpy as np

from trace_search.config import settings
from trace_search.extraction.chunking import (
    chunk_by_headings,
    create_contextual_chunk,
    extract_breadcrumb,
)
from trace_search.extraction.frontmatter import Frontmatter, split_frontmatter
from trace_search.extraction.extractors import (
    SUPPORTED_EXTENSIONS,
    extract_content,
    extract_title,
)
from trace_search.indexing.embeddings import (
    EmbeddingArray,
    EmbeddingBackend,
    build_embedding_backend,
)
from trace_search.indexing.index_metadata import (
    build_index_metadata,
    categorize_source_changes,
    metadata_matches_settings,
    utc_now_iso,
)
from trace_search.indexing.index_paths import chunk_id
from trace_search.indexing.index_store import (
    ChunkMetadata,
    IndexSnapshot,
    legacy_index_dirs,
    load_snapshot,
    read_current,
    write_snapshot,
    writer_lock,
)
from trace_search.indexing.kb_paths import get_default_index_root, should_exclude_path

logger = logging.getLogger(__name__)

BackendProvider = Callable[[], EmbeddingBackend]


class LoadedDocument(TypedDict):
    path: str
    title: str
    folder: str
    extension: str
    mtime: float
    content: str
    frontmatter: Frontmatter


def _document_card(doc: LoadedDocument) -> tuple[str, str]:
    """Return (aliases, lead text) for a document's first chunk.

    The lead puts a page's alternate names and summary where both BM25 and the
    embedding see them, instead of burying them in raw YAML.
    """
    meta = doc["frontmatter"]
    title_key = doc["title"].casefold()
    names = [
        name for name in (meta.title, *meta.aliases) if name.casefold() != title_key
    ]
    aliases = "; ".join(dict.fromkeys(names))
    lead = ""
    if aliases:
        lead += f"Also known as: {aliases}\n"
    if meta.summary:
        lead += f"Summary: {meta.summary}\n"
    return aliases, lead


class WikiIndexer:
    """Index one knowledge base and hand out its current in-memory snapshot."""

    def __init__(
        self,
        kb_path: str | Path | None = None,
        index_root: str | Path | None = None,
        backend: EmbeddingBackend | BackendProvider | None = None,
    ):
        """Initialize the indexer.

        Args:
            kb_path: Path to knowledge base. Uses KB_PATH env var if None.
            index_root: Directory holding index generations. Defaults to
                ``INDEX_PATH`` or ``<kb>/.mcp-search/indexes``.
            backend: Embedding backend, or a zero-argument provider so the model
                loads only when a build or semantic query needs it.
        """
        self.kb_path = (
            Path(kb_path) if kb_path else settings.resolved_kb_path
        ).resolve()
        self.index_root = (
            Path(index_root)
            if index_root
            else get_default_index_root(self.kb_path, settings.index_path)
        )
        if backend is None:
            self._backend_provider: BackendProvider = build_embedding_backend
        elif isinstance(backend, EmbeddingBackend):
            self._backend_provider = lambda: backend
        else:
            self._backend_provider = backend
        self._backend: EmbeddingBackend | None = None
        self._snapshot: IndexSnapshot | None = None
        self._lock = threading.Lock()

    @property
    def backend(self) -> EmbeddingBackend:
        """The embedding backend, loaded on first use."""
        if self._backend is None:
            self._backend = self._backend_provider()
        return self._backend

    def has_index(self) -> bool:
        """Whether a generation has been published for this knowledge base."""
        return read_current(self.index_root) is not None

    def snapshot(self) -> IndexSnapshot:
        """Return the current generation, reloading it when a new one was published.

        Costs one small file read per call. A reindex by any process, including
        a CLI run beside a long-lived server, is picked up on the next search.
        """
        current = read_current(self.index_root)
        loaded = self._snapshot
        if loaded is not None and loaded.generation == current:
            return loaded
        with self._lock:
            loaded = self._snapshot
            if loaded is None or loaded.generation != read_current(self.index_root):
                fresh = load_snapshot(self.index_root)
                if fresh is not None:
                    logger.info(
                        "Loaded index generation %s for %s (%d chunks)",
                        fresh.generation,
                        self.kb_path,
                        len(fresh),
                    )
                loaded = fresh or IndexSnapshot.empty()
                self._snapshot = loaded
            return loaded

    def _get_relative_path(self, path: Path) -> str:
        return str(path.relative_to(self.kb_path))

    def _get_folder(self, path: Path) -> str:
        rel = path.relative_to(self.kb_path)
        parts = rel.parts
        return parts[0] if len(parts) > 1 else ""

    def _load_single_document(self, file_path: Path) -> LoadedDocument | None:
        """Extract one supported file into a doc dict, or return None to skip."""
        ext = file_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return None
        if should_exclude_path(file_path, self.kb_path):
            return None

        try:
            content = extract_content(file_path)
        except Exception as e:
            logger.warning("Failed to extract %s: %s", file_path, e)
            return None

        if not content.strip():
            return None

        frontmatter, body = (
            split_frontmatter(content) if ext == ".md" else (Frontmatter(), content)
        )
        stat = file_path.stat()
        return {
            "path": self._get_relative_path(file_path),
            "title": extract_title(body, file_path, fallback=frontmatter.title),
            "folder": self._get_folder(file_path),
            "extension": ext,
            "mtime": stat.st_mtime,
            "content": body,
            "frontmatter": frontmatter,
        }

    def _load_documents_subset(self, relative_paths: list[str]) -> list[LoadedDocument]:
        """Load only the listed relative paths into doc dicts."""
        docs: list[LoadedDocument] = []
        for rel in relative_paths:
            file_path = self.kb_path / rel
            if not file_path.is_file():
                continue
            doc = self._load_single_document(file_path)
            if doc is not None:
                docs.append(doc)
        docs.sort(key=lambda d: d["path"])
        return docs

    def _build_chunks(
        self, docs: list[LoadedDocument]
    ) -> tuple[list[str], list[str], list[ChunkMetadata]]:
        """Convert documents into (ids, texts, chunk metadata) ready for indexing."""
        ids: list[str] = []
        texts: list[str] = []
        chunks: list[ChunkMetadata] = []

        for doc in docs:
            pieces = chunk_by_headings(doc["content"]) if doc["content"].strip() else []
            aliases, lead = _document_card(doc)
            if not pieces:
                pieces = [""]
            frontmatter = doc["frontmatter"]
            for i, piece in enumerate(pieces):
                ids.append(chunk_id(doc["path"], i))
                texts.append(
                    create_contextual_chunk(
                        doc["title"], doc["folder"], piece, lead=lead if i == 0 else ""
                    )
                )
                chunk: ChunkMetadata = {
                    "path": doc["path"],
                    "title": doc["title"],
                    "folder": doc["folder"],
                    "chunk_index": i,
                    "chunk_count": len(pieces),
                    "breadcrumb": extract_breadcrumb(piece, doc["title"]),
                    "extension": doc["extension"],
                    "source_mtime": float(doc["mtime"]),
                }
                if aliases:
                    chunk["aliases"] = aliases
                if frontmatter.status:
                    chunk["status"] = frontmatter.status
                if frontmatter.as_of:
                    chunk["as_of"] = frontmatter.as_of
                chunks.append(chunk)

        return ids, texts, chunks

    def _reusable_snapshot(self) -> IndexSnapshot | None:
        """The on-disk generation, when its chunks can be reused incrementally."""
        current = self.snapshot()
        if current.generation is None:
            legacy = legacy_index_dirs(self.index_root)
            if legacy:
                logger.warning(
                    "Ignoring Chroma-era index directories (safe to delete): %s",
                    ", ".join(str(path) for path in legacy),
                )
            return None
        if current.metadata is None:
            logger.info("Index metadata missing or outdated; running a full rebuild")
            return None
        if not metadata_matches_settings(current.metadata):
            logger.info(
                "Index was built with other model or chunk settings; rebuilding"
            )
            return None
        return current

    def _encode(self, texts: list[str], dim: int) -> EmbeddingArray:
        if not texts:
            return np.empty((0, dim), dtype=np.float32)
        logger.info("Embedding %d chunks...", len(texts))
        return self.backend.encode(texts)

    def build_index(self, force: bool = False) -> int:
        """Build or update the index and return its chunk count.

        Incremental by default: unchanged files keep their chunks and
        embeddings, and only added or changed files are re-extracted and
        re-embedded. ``force=True`` rebuilds every file. Either way the result
        is published as a new generation under the writer lock, so a failed
        build leaves the previous index serving.
        """
        with writer_lock(self.index_root):
            build_started_at = utc_now_iso()
            current = None if force else self._reusable_snapshot()
            changes = categorize_source_changes(
                self.kb_path, current.metadata if current is not None else None
            )
            if current is not None and not changes.has_changes:
                logger.info(
                    "Index up to date: %d files, %d chunks",
                    len(changes.unchanged),
                    len(current),
                )
                return len(current)

            if current is not None:
                unchanged = set(changes.unchanged)
                kept = [
                    row
                    for row, chunk in enumerate(current.chunks)
                    if chunk["path"] in unchanged
                ]
                to_index = changes.added + changes.changed
            else:
                kept = []
                to_index = [record.path for record in changes.inventory]

            new_ids, new_texts, new_chunks = self._build_chunks(
                self._load_documents_subset(to_index)
            )
            reused_dim = current.embeddings.shape[1] if current is not None else 0
            new_embeddings = self._encode(new_texts, reused_dim)

            ids = [current.chunk_ids[row] for row in kept] if current else []
            texts = [current.texts[row] for row in kept] if current else []
            chunks = [current.chunks[row] for row in kept] if current else []
            ids += new_ids
            texts += new_texts
            chunks += new_chunks
            if current is not None and kept and new_texts:
                embeddings = np.vstack([current.embeddings[kept], new_embeddings])
            elif current is not None and kept:
                embeddings = current.embeddings[kept]
            else:
                embeddings = new_embeddings

            order = sorted(
                range(len(ids)),
                key=lambda row: (chunks[row]["path"], chunks[row]["chunk_index"]),
            )
            snapshot = IndexSnapshot.build(
                chunk_ids=[ids[row] for row in order],
                texts=[texts[row] for row in order],
                chunks=[chunks[row] for row in order],
                embeddings=embeddings[order] if len(order) else embeddings,
                k1=settings.bm25_k1,
                b=settings.bm25_b,
                metadata=build_index_metadata(
                    kb_path=self.kb_path,
                    build_started_at=build_started_at,
                    build_completed_at=utc_now_iso(),
                    document_count=len({chunk["path"] for chunk in chunks}),
                    chunk_count=len(ids),
                    source_files=changes.inventory,
                ),
            )
            published = write_snapshot(self.index_root, snapshot)
            with self._lock:
                self._snapshot = published

        logger.info(
            "Reindex (%s): +%d added, ~%d changed, -%d removed, =%d unchanged; "
            "%d chunks total",
            "incremental" if current is not None else "full",
            len(changes.added),
            len(changes.changed),
            len(changes.removed),
            len(changes.unchanged),
            len(published),
        )
        return len(published)

    def neighbor_contents_batch(
        self,
        requests: list[tuple[str, int | None, int | None]],
    ) -> list[str | None]:
        """Return the text of each hit's previous and next chunk, joined."""
        snapshot = self.snapshot()
        output: list[str | None] = []
        for path, chunk_index, chunk_count in requests:
            if chunk_index is None or chunk_count is None or chunk_count <= 1:
                output.append(None)
                continue
            docs = [
                snapshot.texts[snapshot.row_by_id[cid]]
                for i in (chunk_index - 1, chunk_index + 1)
                if 0 <= i < chunk_count
                and (cid := chunk_id(path, i)) in snapshot.row_by_id
            ]
            output.append("\n\n".join(docs) if docs else None)
        return output

    def get_stats(self) -> dict[str, object]:
        """Get index statistics."""
        snapshot = self.snapshot()
        return {
            "total_chunks": len(snapshot),
            "documents": len({chunk["path"] for chunk in snapshot.chunks}),
            "generation": snapshot.generation or "none (run reindex)",
            "kb_path": str(self.kb_path),
            "index_root": str(self.index_root),
            "chunking": {
                "char_chunk_size": settings.char_chunk_size,
                "char_overlap_size": settings.char_overlap_size,
            },
        }
