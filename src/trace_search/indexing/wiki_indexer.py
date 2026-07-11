"""ChromaDB + BM25 indexing for local knowledge bases."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import bm25s
import chromadb
from chromadb.errors import NotFoundError
from chromadb.config import Settings as ChromaSettings

from trace_search.retrieval.bm25_tokenize import english_stemmer
from trace_search.extraction.chunking import (
    chunk_by_headings,
    create_contextual_chunk,
    extract_breadcrumb,
)
from trace_search.config import settings
from trace_search.extraction.corpus import iter_kb_files
from trace_search.indexing.embeddings import EmbeddingBackend, build_embedding_backend
from trace_search.extraction.extractors import (
    SUPPORTED_EXTENSIONS,
    extract_content,
    extract_title,
)
from trace_search.indexing.index_metadata import (
    build_index_metadata,
    categorize_source_changes,
    collect_source_files,
    invalidate_index_metadata,
    metadata_matches_active_model,
    read_index_metadata,
    utc_now_iso,
    write_index_metadata,
)
from trace_search.indexing.index_paths import (
    CHROMA_COLLECTION,
    bm25_dir,
    chroma_dir,
    chunk_id,
)
from trace_search.indexing.kb_paths import get_default_index_root, should_exclude_path

logger = logging.getLogger(__name__)


class WikiIndexer:
    """Index knowledge base documents into ChromaDB and BM25 for search."""

    def __init__(
        self,
        kb_path: str | Path | None = None,
        chroma_path: str | Path | None = None,
        bm25_path: str | Path | None = None,
        backend: EmbeddingBackend | None = None,
    ):
        """Initialize the indexer.

        Args:
            kb_path: Path to knowledge base. Uses KB_PATH env var if None.
            chroma_path: Path for ChromaDB storage. Auto-generated if None.
            bm25_path: Path for BM25 index storage. Auto-generated if None.
            backend: Pre-loaded embedding backend to share across indexers.
        """
        self.kb_path = (
            Path(kb_path) if kb_path else settings.resolved_kb_path
        ).resolve()

        # Model-specific index paths to prevent dimension mismatch
        model_slug = settings.model_slug

        # Use explicit INDEX_PATH when set; otherwise keep indexes in the
        # documented per-KB .mcp-search/indexes directory.
        index_base = get_default_index_root(self.kb_path, settings.index_path)

        if chroma_path:
            self.chroma_path = Path(chroma_path)
        elif settings.chroma_path:
            self.chroma_path = Path(settings.chroma_path)
        else:
            self.chroma_path = chroma_dir(index_base, model_slug)
        if bm25_path:
            self.bm25_path = Path(bm25_path)
        else:
            self.bm25_path = bm25_dir(index_base, model_slug)

        logger.info(
            "Embedding model: %s (dims=%d)",
            settings.embedding_model,
            settings.embedding_dims,
        )
        logger.info("ChromaDB path: %s", self.chroma_path)
        logger.info("BM25 path: %s", self.bm25_path)

        self.client = chromadb.PersistentClient(
            path=str(self.chroma_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        self.backend: EmbeddingBackend = backend or build_embedding_backend()

        self.collection = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

        self._bm25: bm25s.BM25 | None = None
        self._bm25_corpus: list[dict] | None = None

    def _get_relative_path(self, path: Path) -> str:
        return str(path.relative_to(self.kb_path))

    def _get_folder(self, path: Path) -> str:
        rel = path.relative_to(self.kb_path)
        parts = rel.parts
        return parts[0] if len(parts) > 1 else ""

    def _should_exclude(self, path: Path) -> bool:
        return should_exclude_path(path, self.kb_path)

    def _load_single_document(self, file_path: Path) -> dict | None:
        """Extract one supported file into a doc dict, or return None to skip."""
        ext = file_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return None
        if self._should_exclude(file_path):
            return None

        try:
            content = extract_content(file_path)
        except Exception as e:
            logger.warning("Failed to extract %s: %s", file_path, e)
            return None

        if not content.strip():
            return None

        stat = file_path.stat()
        return {
            "path": self._get_relative_path(file_path),
            "title": extract_title(content, file_path),
            "folder": self._get_folder(file_path),
            "extension": ext,
            "mtime": stat.st_mtime,
            "content": content,
        }

    def load_documents(self) -> list[dict]:
        """Load all supported files from knowledge base."""
        docs: list[dict] = []
        for file_path in iter_kb_files(self.kb_path):
            doc = self._load_single_document(file_path)
            if doc is not None:
                docs.append(doc)
        docs.sort(key=lambda d: d["path"])
        return docs

    def _load_documents_subset(self, relative_paths: list[str]) -> list[dict]:
        """Load only the listed relative paths into doc dicts."""
        docs: list[dict] = []
        for rel in relative_paths:
            file_path = self.kb_path / rel
            if not file_path.is_file():
                continue
            doc = self._load_single_document(file_path)
            if doc is not None:
                docs.append(doc)
        docs.sort(key=lambda d: d["path"])
        return docs

    def _reconcile_index_state(self, force: bool) -> str:
        """Decide whether to do a full rebuild or an incremental update.

        Returns "force" when the indexes must be rebuilt from scratch (caller
        requested it, indexes are missing or empty, or metadata is missing or
        outdated). Returns "incremental" when the existing indexes are healthy
        enough to update in place; BM25 may need rebuilding from Chroma but
        chunks are preserved across the update.
        """
        if force:
            return "force"

        chroma_count = self.collection.count()
        if chroma_count == 0:
            return "force"

        metadata = read_index_metadata(self.bm25_path.parent)
        if metadata is None:
            logger.info("Index metadata missing or outdated; promoting to full rebuild")
            return "force"

        if not metadata_matches_active_model(metadata):
            logger.info(
                "Index metadata does not match active embedding settings; "
                "promoting to full rebuild"
            )
            return "force"

        if self.bm25_path.exists():
            try:
                self._load_bm25()
            except Exception as e:
                logger.warning(
                    "BM25 load failed; will rebuild from Chroma during incremental: %s",
                    e,
                )
                self._bm25 = None
                self._bm25_corpus = None

        return "incremental"

    def _build_chunks(
        self, docs: list[dict]
    ) -> tuple[list[str], list[str], list[dict]]:
        """Convert documents into (chunks, ids, metadatas) ready for indexing."""
        all_chunks: list[str] = []
        all_ids: list[str] = []
        all_metadatas: list[dict] = []

        for doc in docs:
            chunks = chunk_by_headings(doc["content"])
            chunk_count = len(chunks)
            extension = doc.get("extension") or Path(doc["path"]).suffix.lower()
            source_mtime = float(doc.get("mtime") or 0.0)
            for i, chunk in enumerate(chunks):
                all_chunks.append(
                    create_contextual_chunk(doc["title"], doc["folder"], chunk)
                )
                all_ids.append(chunk_id(doc["path"], i))
                all_metadatas.append(
                    {
                        "path": doc["path"],
                        "title": doc["title"],
                        "folder": doc["folder"],
                        "chunk_index": i,
                        "chunk_count": chunk_count,
                        "breadcrumb": extract_breadcrumb(chunk, doc["title"]),
                        "extension": extension,
                        "source_mtime": source_mtime,
                    }
                )

        return all_chunks, all_ids, all_metadatas

    def _persist_chroma(
        self,
        ids: list[str],
        chunks: list[str],
        embeddings,
        metadatas: list[dict],
    ) -> None:
        """Write chunks and embeddings to ChromaDB in batches."""
        batch_size = 500
        for i in range(0, len(chunks), batch_size):
            end = min(i + batch_size, len(chunks))
            self.collection.add(
                ids=ids[i:end],
                documents=chunks[i:end],
                embeddings=embeddings[i:end].tolist(),
                metadatas=metadatas[i:end],
            )
            logger.info("Indexed %s/%s chunks (ChromaDB)", end, len(chunks))

    def _persist_bm25(self, chunks: list[str], metadatas: list[dict]) -> None:
        """Build and save the BM25 index plus metadata to disk."""
        logger.info("Building BM25 index...")
        corpus_tokens = bm25s.tokenize(
            chunks,
            stopwords="en",
            stemmer=english_stemmer(),
        )
        self._bm25 = bm25s.BM25(k1=settings.bm25_k1, b=settings.bm25_b)
        self._bm25.index(corpus_tokens)
        self._bm25.corpus = [
            {"id": index, "text": chunk} for index, chunk in enumerate(chunks)
        ]
        self._bm25_corpus = metadatas

        self.bm25_path.mkdir(parents=True, exist_ok=True)
        self._bm25.save(str(self.bm25_path), corpus=chunks)

        metadata_path = self.bm25_path / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadatas, f)

    def build_index(self, force: bool = False) -> int:
        """Build or update the search index. Returns number of chunks indexed.

        Default behavior is incremental: detect added, changed, and removed
        source files and apply only the necessary work. Pass `force=True` to
        drop both indexes and rebuild every file from scratch.
        """
        mode = self._reconcile_index_state(force)
        build_started_at = utc_now_iso()

        if mode == "force":
            return self._full_rebuild(build_started_at)

        metadata = read_index_metadata(self.bm25_path.parent)
        changes = categorize_source_changes(self.kb_path, metadata)

        bm25_healthy = (
            self.bm25_path.exists()
            and self._bm25 is not None
            and self._bm25_corpus is not None
        )
        if not changes.has_changes and bm25_healthy:
            logger.info(
                "Index up to date: %d unchanged files, %d chunks",
                len(changes.unchanged),
                self.collection.count(),
            )
            return self.collection.count()

        try:
            self._apply_incremental_changes(changes)
            self._rebuild_bm25_from_chroma()
        except Exception:
            logger.exception(
                "Incremental reindex failed; invalidating metadata so next "
                "reindex runs as a full rebuild"
            )
            invalidate_index_metadata(self.bm25_path.parent)
            raise

        chunk_count = self.collection.count()
        new_metadata = build_index_metadata(
            kb_path=self.kb_path,
            build_started_at=build_started_at,
            build_completed_at=utc_now_iso(),
            document_count=len(changes.inventory),
            chunk_count=chunk_count,
            source_files=changes.inventory,
        )
        write_index_metadata(self.bm25_path.parent, new_metadata)
        logger.info(
            "Incremental reindex: +%d added, ~%d changed, -%d removed, =%d unchanged; %d chunks total",
            len(changes.added),
            len(changes.changed),
            len(changes.removed),
            len(changes.unchanged),
            chunk_count,
        )
        return chunk_count

    def _full_rebuild(self, build_started_at: str) -> int:
        """Drop both indexes and reindex every visible file from scratch."""
        self._clear_chroma_collection()
        self._clear_bm25_index()

        logger.info("Loading documents...")
        docs = self.load_documents()
        logger.info("Found %s documents", len(docs))

        all_chunks, all_ids, all_metadatas = self._build_chunks(docs)

        if not all_chunks:
            logger.info("No chunks to index")
            inventory = collect_source_files(self.kb_path)
            metadata = build_index_metadata(
                kb_path=self.kb_path,
                build_started_at=build_started_at,
                build_completed_at=utc_now_iso(),
                document_count=len(docs),
                chunk_count=0,
                source_files=inventory,
            )
            write_index_metadata(self.bm25_path.parent, metadata)
            return 0

        logger.info("Generating embeddings for %s chunks...", len(all_chunks))
        embeddings = self.backend.encode(all_chunks)

        self._persist_chroma(all_ids, all_chunks, embeddings, all_metadatas)
        self._persist_bm25(all_chunks, all_metadatas)

        chunk_count = self.collection.count()
        logger.info("Index complete: %s chunks (ChromaDB + BM25)", chunk_count)

        inventory = collect_source_files(self.kb_path)
        metadata = build_index_metadata(
            kb_path=self.kb_path,
            build_started_at=build_started_at,
            build_completed_at=utc_now_iso(),
            document_count=len(docs),
            chunk_count=chunk_count,
            source_files=inventory,
        )
        write_index_metadata(self.bm25_path.parent, metadata)
        return chunk_count

    def _apply_incremental_changes(self, changes) -> None:
        """Apply categorized file changes to the Chroma collection in place."""
        for path in changes.changed + changes.removed:
            self.collection.delete(where={"path": path})

        paths_to_index = changes.added + changes.changed
        if not paths_to_index:
            return

        docs = self._load_documents_subset(paths_to_index)
        chunks, ids, metadatas = self._build_chunks(docs)
        if not chunks:
            return

        embeddings = self.backend.encode(chunks)
        self._persist_chroma(ids, chunks, embeddings, metadatas)

    def _rebuild_bm25_from_chroma(self) -> None:
        """Rebuild BM25 from the current Chroma chunk inventory."""
        result = self.collection.get(include=["documents", "metadatas"])
        documents = list(result.get("documents") or [])
        metadatas = list(result.get("metadatas") or [])

        self._clear_bm25_index()

        if not documents:
            return

        self._persist_bm25(documents, metadatas)

    def _clear_chroma_collection(self) -> None:
        """Drop and recreate the Chroma collection atomically without materializing ids."""
        try:
            self.client.delete_collection(CHROMA_COLLECTION)
        except NotFoundError:
            logger.debug("Chroma collection did not exist before rebuild")
        except Exception as exc:
            logger.warning("Failed to delete Chroma collection before rebuild: %s", exc)
            raise
        self.collection = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    def _clear_bm25_index(self) -> None:
        """Delete BM25 files and clear in-memory BM25 state."""
        self._bm25 = None
        self._bm25_corpus = None
        if self.bm25_path.exists():
            shutil.rmtree(self.bm25_path)

    def _load_bm25(self) -> None:
        """Load BM25 index from disk."""
        if self._bm25 is not None:
            return

        if not self.bm25_path.exists():
            return

        self._bm25 = bm25s.BM25.load(str(self.bm25_path), load_corpus=True)
        metadata_path = self.bm25_path / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                self._bm25_corpus = json.load(f)

    @property
    def bm25(self) -> bm25s.BM25 | None:
        """Get BM25 index, loading from disk if needed."""
        if self._bm25 is None:
            self._load_bm25()
        return self._bm25

    @property
    def bm25_corpus(self) -> list[dict] | None:
        """Get BM25 corpus metadata."""
        if self._bm25_corpus is None:
            self._load_bm25()
        return self._bm25_corpus

    def get_chunks_by_ids(self, ids: list[str]) -> dict[str, str]:
        """Fetch chunk documents by Chroma ids."""
        if not ids:
            return {}
        results = self.collection.get(ids=ids, include=["documents"])
        id_to_doc: dict[str, str] = {}
        for chunk_key, doc in zip(
            results.get("ids") or [],
            results.get("documents") or [],
        ):
            if doc:
                id_to_doc[chunk_key] = str(doc)
        return id_to_doc

    def neighbor_contents_batch(
        self,
        requests: list[tuple[str, int | None, int | None]],
    ) -> list[str | None]:
        """Batch-fetch neighbor chunk text for grouped search context."""
        request_ids: list[list[str]] = []
        all_ids: set[str] = set()
        for path, chunk_index, chunk_count in requests:
            if chunk_index is None or chunk_count is None or chunk_count <= 1:
                request_ids.append([])
                continue
            ids = [
                chunk_id(path, i)
                for i in (chunk_index - 1, chunk_index + 1)
                if 0 <= i < chunk_count
            ]
            request_ids.append(ids)
            all_ids.update(ids)

        if not all_ids:
            return [None] * len(requests)

        id_to_doc = self.get_chunks_by_ids(list(all_ids))
        output: list[str | None] = []
        for ids in request_ids:
            docs = [id_to_doc[cid] for cid in ids if cid in id_to_doc]
            output.append("\n\n".join(docs) if docs else None)
        return output

    def get_stats(self) -> dict[str, object]:
        """Get index statistics."""
        bm25 = self.bm25
        bm25_corpus = self.bm25_corpus
        bm25_docs = len(bm25_corpus) if bm25_corpus else 0
        return {
            "total_chunks": self.collection.count(),
            "bm25_docs": bm25_docs,
            "kb_path": str(self.kb_path),
            "chroma_path": str(self.chroma_path),
            "bm25_path": str(self.bm25_path),
            "bm25_available": bm25 is not None,
            # Chunking configuration
            "chunking": {
                "enable_overlap": settings.enable_chunk_overlap,
                "char_chunk_size": settings.char_chunk_size,
                "char_overlap_size": settings.char_overlap_size,
            },
        }
