"""Document indexer for wiki knowledge base."""

import json
import logging
import re
import shutil
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import bm25s
import chromadb
import Stemmer
from chromadb.config import Settings as ChromaSettings

from trace_search.config import settings
from trace_search.embeddings import EmbeddingBackend, build_embedding_backend

logger = logging.getLogger(__name__)

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "SUPPORTED_EXTENSIONS_ORDERED",
    "WikiIndexer",
    "TokenCounter",
    "extract_title",
    "extract_content",
    "extract_pdf_content",
    "extract_docx_content",
    "extract_pptx_content",
    "extract_csv_content",
    "extract_code_content",
    "extract_notebook_content",
    "chunk_by_headings",
    "chunk_by_paragraphs",
    "create_contextual_chunk",
]

# Supported file extensions for indexing
SUPPORTED_EXTENSIONS_ORDERED = (
    # Documents
    ".md",
    ".pdf",
    ".docx",
    ".pptx",
    ".csv",
    # Code
    ".sql",
    ".py",
    ".yml",
    ".yaml",
    ".ipynb",
    # TypeScript
    ".ts",
    ".tsx",
)
SUPPORTED_EXTENSIONS = set(SUPPORTED_EXTENSIONS_ORDERED)


class TokenCounter:
    """Token counter using the embedding model's tokenizer.

    Use _get_token_counter() to get a cached singleton instance.
    """

    _tokenizer = None

    def _ensure_tokenizer(self) -> None:
        """Lazy-load tokenizer on first use."""
        if self._tokenizer is None:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(
                settings.tokenizer_model,
                use_fast=True,
            )

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using the embedding model's tokenizer."""
        self._ensure_tokenizer()
        return len(self._tokenizer.encode(text, add_special_tokens=False))

    def truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit within max_tokens."""
        self._ensure_tokenizer()
        tokens = self._tokenizer.encode(text, add_special_tokens=False)
        if len(tokens) <= max_tokens:
            return text
        truncated_tokens = tokens[:max_tokens]
        return self._tokenizer.decode(truncated_tokens, skip_special_tokens=True)

    def get_last_n_tokens(self, text: str, n: int) -> str:
        """Get the last n tokens of text as a string."""
        self._ensure_tokenizer()
        tokens = self._tokenizer.encode(text, add_special_tokens=False)
        if len(tokens) <= n:
            return text
        last_tokens = tokens[-n:]
        return self._tokenizer.decode(last_tokens, skip_special_tokens=True)


@lru_cache(maxsize=1)
def _get_token_counter() -> TokenCounter:
    """Get singleton TokenCounter instance (lazy-loaded)."""
    return TokenCounter()


def extract_title(content: str, path: Path) -> str:
    """Extract title from file with fallback strategies."""
    ext = path.suffix.lower()

    # Code files: use filename with extension (e.g., "schema_parser.py")
    if ext in {".sql", ".py", ".ts", ".tsx", ".yml", ".yaml", ".ipynb"}:
        return path.name

    # Markdown: extract from first heading
    if ext == ".md":
        match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return path.stem

    # Documents: find first substantial line
    if ext in {".pdf", ".docx", ".pptx", ".csv"}:
        for line in content.split("\n")[:10]:
            line = line.strip()
            if line and 10 < len(line) < 200 and not line.isupper():
                return line

    return path.stem


def extract_pdf_content(path: Path) -> str:
    """Extract text from PDF using PyMuPDF (better quality)."""
    import fitz  # PyMuPDF

    with fitz.open(path) as doc:
        pages = []
        for page in doc:
            text = page.get_text("text")
            if text.strip():
                pages.append(text)
    return "\n\n".join(pages)


def extract_docx_content(path: Path) -> str:
    """Extract text from Word document (paragraphs + tables)."""
    from docx import Document

    doc = Document(path)
    texts = []

    # Extract paragraphs
    for para in doc.paragraphs:
        if para.text.strip():
            texts.append(para.text)

    # Extract tables
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(
                cell.text.strip() for cell in row.cells if cell.text.strip()
            )
            if row_text:
                texts.append(row_text)

    return "\n\n".join(texts)


def extract_pptx_content(path: Path) -> str:
    """Extract text from PowerPoint (text frames + tables + notes)."""
    from pptx import Presentation

    prs = Presentation(path)
    texts = []

    for slide_num, slide in enumerate(prs.slides, 1):
        slide_texts = [f"[Slide {slide_num}]"]

        # Extract text from shapes
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    if para.text.strip():
                        slide_texts.append(para.text)
            elif shape.has_table:
                for row in shape.table.rows:
                    row_text = " | ".join(
                        cell.text.strip() for cell in row.cells if cell.text.strip()
                    )
                    if row_text:
                        slide_texts.append(row_text)

        # Extract speaker notes
        if slide.has_notes_slide:
            notes_text = slide.notes_slide.notes_text_frame.text.strip()
            if notes_text:
                slide_texts.append(f"[Notes: {notes_text}]")

        texts.append("\n".join(slide_texts))

    return "\n\n".join(texts)


def extract_csv_content(path: Path) -> str:
    """Extract and flatten CSV data into readable text."""
    import csv

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row_num, row in enumerate(reader, 1):
            row_parts = [f"Row {row_num}:"]
            for key, value in row.items():
                if value:
                    value_str = str(value).strip()
                    if value_str:
                        row_parts.append(f"{key}: {value_str}")
            if len(row_parts) > 1:  # Has content beyond row number
                rows.append(" | ".join(row_parts))
        return "\n".join(rows)


def extract_code_content(path: Path) -> str:
    """Extract code file content (SQL, Python, TypeScript, YAML)."""
    return path.read_text(encoding="utf-8", errors="replace")


def extract_notebook_content(path: Path) -> str:
    """Extract Jupyter notebook content (code + markdown cells)."""
    try:
        nb = json.loads(path.read_text(encoding="utf-8"))
        cells = nb.get("cells", [])
        content_parts = []
        for i, cell in enumerate(cells):
            cell_type = cell.get("cell_type", "code")
            source = "".join(cell.get("source", []))
            if source.strip():
                content_parts.append(f"[{cell_type.upper()} CELL {i + 1}]\n{source}")
        return "\n\n".join(content_parts)
    except Exception as e:
        logger.warning("Failed to parse notebook %s: %s", path, e)
        return ""


def extract_content(path: Path) -> str:
    """Extract text content based on file type.

    Args:
        path: Path to the file to extract content from.

    Returns:
        Extracted text content.

    Raises:
        ValueError: If file type is not supported.
    """
    ext = path.suffix.lower()

    extractors: dict[str, Callable[[Path], str]] = {
        ".md": lambda p: p.read_text(encoding="utf-8"),
        ".pdf": extract_pdf_content,
        ".docx": extract_docx_content,
        ".pptx": extract_pptx_content,
        ".csv": extract_csv_content,
        ".sql": extract_code_content,
        ".py": extract_code_content,
        ".ts": extract_code_content,
        ".tsx": extract_code_content,
        ".yml": extract_code_content,
        ".yaml": extract_code_content,
        ".ipynb": extract_notebook_content,
    }

    extractor = extractors.get(ext)
    if extractor is None:
        raise ValueError(f"Unsupported file type: {ext}")
    return extractor(path)


def _get_size(text: str, use_tokens: bool) -> int:
    """Get size of text in characters or tokens."""
    if use_tokens:
        return _get_token_counter().count_tokens(text)
    return len(text)


def _get_overlap_text(chunk: str, overlap_size: int, use_tokens: bool) -> str:
    """Extract overlap text from end of chunk."""
    if overlap_size <= 0:
        return ""
    if use_tokens:
        return _get_token_counter().get_last_n_tokens(chunk, overlap_size)
    # Character-based: take last N chars
    return chunk[-overlap_size:] if len(chunk) > overlap_size else chunk


def _merge_tiny_chunks(
    chunks: list[str],
    *,
    use_tokens: bool,
    max_size: int,
) -> list[str]:
    """Merge tiny chunks into neighbors to preserve context and reduce fragmentation."""
    if len(chunks) <= 1:
        return chunks

    if use_tokens:
        tiny_threshold = max(5, int(max_size * 0.1))
    else:
        tiny_threshold = 200 if max_size >= 200 else max(10, int(max_size * 0.5))

    merged: list[str] = []
    i = 0
    while i < len(chunks):
        chunk = chunks[i]
        if _get_size(chunk, use_tokens) >= tiny_threshold:
            merged.append(chunk)
            i += 1
            continue

        # Prefer merging with next chunk to keep heading context with its section.
        if i + 1 < len(chunks):
            combined_next = f"{chunk}\n\n{chunks[i + 1]}"
            if _get_size(combined_next, use_tokens) <= max_size:
                merged.append(combined_next)
                i += 2
                continue

        # Fall back to previous chunk if it fits.
        if merged:
            combined_prev = f"{merged[-1]}\n\n{chunk}"
            if _get_size(combined_prev, use_tokens) <= max_size:
                merged[-1] = combined_prev
                i += 1
                continue

        merged.append(chunk)
        i += 1

    return merged


def _extract_heading_context(section: str) -> str:
    """Extract contiguous markdown headings from the start of a section."""
    lines = []
    for line in section.splitlines():
        if line.strip().startswith("#"):
            lines.append(line.strip())
            continue
        if line.strip() == "":
            continue
        break
    return "\n".join(lines).strip()


def _prefix_heading_context(
    chunks: list[str],
    context: str,
    *,
    use_tokens: bool,
    max_size: int,
) -> list[str]:
    """Prefix heading context to chunks where it fits, to preserve section meaning."""
    if not context or len(chunks) <= 1:
        return chunks

    prefixed: list[str] = [chunks[0]]
    for chunk in chunks[1:]:
        if chunk.lstrip().startswith(context):
            prefixed.append(chunk)
            continue
        combined = f"{context}\n\n{chunk}"
        if _get_size(combined, use_tokens) <= max_size:
            prefixed.append(combined)
        else:
            prefixed.append(chunk)
    return prefixed


def _get_heading_level(section: str) -> int | None:
    """Return heading level from the first heading line in a section, if any."""
    for line in section.splitlines():
        stripped = line.lstrip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            match = re.match(r"^(#{1,6})\s", stripped)
            if match:
                return len(match.group(1))
        break
    return None


def _heading_level_changed(current_level: int | None, next_level: int | None) -> bool:
    """Decide whether to split chunks when heading levels change."""
    if current_level is None and next_level is None:
        return False
    if current_level is None or next_level is None:
        return True
    return current_level != next_level


def _resolve_chunking_params(
    use_tokens: bool | None,
    max_chunk_chars: int | None,
    max_chunk_tokens: int | None,
    overlap_chars: int | None,
    overlap_tokens: int | None,
    enable_overlap: bool | None,
) -> tuple[bool, int, int]:
    """Resolve chunking parameters with defaults from settings.

    Returns:
        Tuple of (use_tokens, max_size, overlap_size)
    """
    if use_tokens is None:
        use_tokens = settings.use_token_based_chunking
    if max_chunk_chars is None:
        max_chunk_chars = settings.char_chunk_size
    if max_chunk_tokens is None:
        max_chunk_tokens = settings.token_chunk_size
    if overlap_chars is None:
        overlap_chars = settings.char_overlap_size
    if overlap_tokens is None:
        overlap_tokens = settings.token_overlap_size
    if enable_overlap is None:
        enable_overlap = settings.enable_chunk_overlap

    max_size = max_chunk_tokens if use_tokens else max_chunk_chars
    overlap_size = overlap_tokens if use_tokens else overlap_chars
    if not enable_overlap:
        overlap_size = 0

    return use_tokens, max_size, overlap_size


def chunk_by_headings(
    content: str,
    max_chunk_chars: int | None = None,
    *,
    use_tokens: bool | None = None,
    max_chunk_tokens: int | None = None,
    overlap_chars: int | None = None,
    overlap_tokens: int | None = None,
    enable_overlap: bool | None = None,
) -> list[str]:
    """Split content by markdown headings, respecting size limits.

    Args:
        content: Markdown content to chunk.
        max_chunk_chars: Max characters per chunk.
        use_tokens: Use token-based sizing.
        max_chunk_tokens: Max tokens per chunk (token mode).
        overlap_chars: Character overlap between chunks.
        overlap_tokens: Token overlap between chunks.
        enable_overlap: Enable overlap.

    Returns:
        List of content chunks.
    """
    use_tokens, max_size, overlap_size = _resolve_chunking_params(
        use_tokens,
        max_chunk_chars,
        max_chunk_tokens,
        overlap_chars,
        overlap_tokens,
        enable_overlap,
    )

    # Split on headings (keep the heading with content)
    sections = re.split(r"(?=^#{1,3}\s)", content, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    chunks: list[str] = []
    current_chunk = ""
    pending_overlap = ""  # overlap from previous chunk
    current_level: int | None = None

    for section in sections:
        section_level = _get_heading_level(section)
        section_size = _get_size(section, use_tokens)
        current_size = _get_size(current_chunk, use_tokens)

        if current_chunk and _heading_level_changed(current_level, section_level):
            chunks.append(current_chunk)
            current_chunk = ""
            current_level = None
            pending_overlap = ""
            current_size = 0

        if current_size + section_size <= max_size:
            current_chunk += "\n\n" + section if current_chunk else section
            if current_chunk == section:
                current_level = section_level
        else:
            if current_chunk:
                chunks.append(current_chunk)
                pending_overlap = _get_overlap_text(
                    current_chunk, overlap_size, use_tokens
                )
                current_level = None

            # If section itself is too large, split it further
            if section_size > max_size:
                sub_chunks = chunk_by_paragraphs(
                    section,
                    max_chunk_chars=max_chunk_chars,
                    use_tokens=use_tokens,
                    max_chunk_tokens=max_chunk_tokens,
                    overlap_chars=overlap_chars,
                    overlap_tokens=overlap_tokens,
                    enable_overlap=enable_overlap,
                )
                heading_context = _extract_heading_context(section)
                sub_chunks = _prefix_heading_context(
                    sub_chunks,
                    heading_context,
                    use_tokens=use_tokens,
                    max_size=max_size,
                )
                # Prepend overlap to first sub-chunk (truncate if exceeds max_size)
                if pending_overlap and sub_chunks:
                    sub_chunks[0] = pending_overlap + "\n\n" + sub_chunks[0]
                    if _get_size(sub_chunks[0], use_tokens) > max_size:
                        if use_tokens:
                            sub_chunks[0] = _get_token_counter().truncate_to_tokens(
                                sub_chunks[0], max_size
                            )
                        else:
                            sub_chunks[0] = sub_chunks[0][:max_size]
                chunks.extend(sub_chunks)
                if sub_chunks:
                    pending_overlap = _get_overlap_text(
                        sub_chunks[-1], overlap_size, use_tokens
                    )
                current_chunk = ""
                current_level = None
            else:
                # Prepend overlap to new section (truncate if exceeds max_size)
                if pending_overlap:
                    current_chunk = pending_overlap + "\n\n" + section
                    if _get_size(current_chunk, use_tokens) > max_size:
                        if use_tokens:
                            current_chunk = _get_token_counter().truncate_to_tokens(
                                current_chunk, max_size
                            )
                        else:
                            current_chunk = current_chunk[:max_size]
                else:
                    current_chunk = section
                pending_overlap = ""
                current_level = section_level

    if current_chunk:
        chunks.append(current_chunk)

    if not chunks:
        return [content]

    return _merge_tiny_chunks(
        chunks,
        use_tokens=use_tokens,
        max_size=max_size,
    )


def chunk_by_paragraphs(
    content: str,
    max_chunk_chars: int | None = None,
    *,
    use_tokens: bool | None = None,
    max_chunk_tokens: int | None = None,
    overlap_chars: int | None = None,
    overlap_tokens: int | None = None,
    enable_overlap: bool | None = None,
) -> list[str]:
    """Split content by paragraphs for large sections.

    Args:
        content: Content to chunk.
        max_chunk_chars: Max characters per chunk.
        use_tokens: Use token-based sizing.
        max_chunk_tokens: Max tokens per chunk (token mode).
        overlap_chars: Character overlap between chunks.
        overlap_tokens: Token overlap between chunks.
        enable_overlap: Enable overlap.

    Returns:
        List of content chunks.
    """
    use_tokens, max_size, overlap_size = _resolve_chunking_params(
        use_tokens,
        max_chunk_chars,
        max_chunk_tokens,
        overlap_chars,
        overlap_tokens,
        enable_overlap,
    )

    paragraphs = content.split("\n\n")
    chunks: list[str] = []
    current_chunk = ""
    pending_overlap = ""

    for para in paragraphs:
        para_size = _get_size(para, use_tokens)
        current_size = _get_size(current_chunk, use_tokens)

        if current_size + para_size <= max_size:
            current_chunk += "\n\n" + para if current_chunk else para
        else:
            if current_chunk:
                chunks.append(current_chunk)
                pending_overlap = _get_overlap_text(
                    current_chunk, overlap_size, use_tokens
                )

            # Start new chunk with overlap if applicable
            if pending_overlap:
                current_chunk = pending_overlap + "\n\n" + para
            else:
                current_chunk = para
            pending_overlap = ""

            # If single paragraph exceeds max, truncate it
            if _get_size(current_chunk, use_tokens) > max_size:
                if use_tokens:
                    current_chunk = _get_token_counter().truncate_to_tokens(
                        current_chunk, max_size
                    )
                else:
                    current_chunk = current_chunk[:max_size]

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def create_contextual_chunk(title: str, folder: str, chunk: str) -> str:
    """Add document context to chunk (Anthropic's contextual retrieval pattern)."""
    return f"Document: {title}\nFolder: {folder}\n\n{chunk}"


class WikiIndexer:
    """Index wiki documents into ChromaDB and BM25 for search."""

    def __init__(
        self,
        kb_path: str | Path | None = None,
        chroma_path: str | Path | None = None,
        bm25_path: str | Path | None = None,
        backend: EmbeddingBackend | None = None,
    ):
        """Initialize wiki indexer.

        Args:
            kb_path: Path to knowledge base. Uses KB_PATH env var if None.
            chroma_path: Path for ChromaDB storage. Auto-generated if None.
            bm25_path: Path for BM25 index storage. Auto-generated if None.
            backend: Pre-loaded embedding backend to share across indexers.
        """
        self.kb_path = Path(kb_path) if kb_path else settings.resolved_kb_path

        # Model-specific index paths to prevent dimension mismatch
        model_slug = settings.model_slug

        # Use explicit index_path setting if available, otherwise fall back to
        # the resolved kb_path (works in both single-KB and multi-collection mode
        # since self.kb_path is already set above).
        index_base = settings.index_path if settings.index_path else self.kb_path

        if chroma_path:
            self.chroma_path = Path(chroma_path)
        elif settings.chroma_path:
            self.chroma_path = Path(settings.chroma_path)
        else:
            self.chroma_path = index_base / f".chroma_db_{model_slug}"
        if bm25_path:
            self.bm25_path = Path(bm25_path)
        else:
            self.bm25_path = index_base / f".bm25_index_{model_slug}"

        logger.info(
            "Embedding model: %s (dims=%d)",
            settings.embedding_model,
            settings.embedding_dims,
        )
        logger.info("ChromaDB path: %s", self.chroma_path)
        logger.info("BM25 path: %s", self.bm25_path)

        # Initialize ChromaDB with persistence
        self.client = chromadb.PersistentClient(
            path=str(self.chroma_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        # Embedding backend: reuse shared instance or construct default
        self.backend: EmbeddingBackend = backend or build_embedding_backend()

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name="wiki_docs",
            metadata={"hnsw:space": "cosine"},
        )

        # BM25 index (lazy loaded)
        self._bm25: bm25s.BM25 | None = None
        self._bm25_corpus: list[dict] | None = None  # metadata for each doc
        self._stemmer = Stemmer.Stemmer("english")

    def _get_relative_path(self, path: Path) -> str:
        """Get path relative to knowledge base."""
        return str(path.relative_to(self.kb_path))

    def _get_folder(self, path: Path) -> str:
        """Get top-level folder name."""
        rel = path.relative_to(self.kb_path)
        parts = rel.parts
        return parts[0] if len(parts) > 1 else ""

    def _should_exclude(self, path: Path) -> bool:
        """Check if path should be excluded based on patterns (exact part match)."""
        exclude = set(settings.exclude_patterns_list)
        return any(part in exclude for part in path.parts)

    def load_documents(self) -> list[dict[str, str]]:
        """Load all supported files from knowledge base."""
        docs = []

        for file_path in self.kb_path.rglob("*"):
            ext = file_path.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            if any(part.startswith(".") for part in file_path.parts):
                continue
            if self._should_exclude(file_path):
                continue

            try:
                content = extract_content(file_path)
            except Exception as e:
                logger.warning("Failed to extract %s: %s", file_path, e)
                continue

            if not content.strip():
                continue

            rel_path = self._get_relative_path(file_path)
            title = extract_title(content, file_path)
            folder = self._get_folder(file_path)

            docs.append(
                {
                    "path": rel_path,
                    "title": title,
                    "folder": folder,
                    "content": content,
                }
            )

        docs.sort(key=lambda d: d["path"])
        return docs

    def _reconcile_index_state(self, force: bool) -> bool:
        """Check index consistency and return the effective force flag.

        Loads the existing BM25 index when possible. Returns True if a full
        rebuild is required (either because force=True or a consistency issue
        was detected).
        """
        chroma_count = self.collection.count()
        chroma_exists = chroma_count > 0
        bm25_exists = self.bm25_path.exists()

        if not force and chroma_exists and bm25_exists:
            try:
                self._load_bm25()
            except Exception as e:
                logger.warning(
                    "Failed to load BM25 index, rebuilding both indexes: %s", e
                )
                return True
            if self._bm25 is not None and self._bm25_corpus is not None:
                logger.info("Index already exists with %s chunks", chroma_count)
                return False
            logger.warning("Incomplete BM25 index detected, rebuilding both indexes")
            return True

        if not force and chroma_exists != bm25_exists:
            logger.warning(
                "Detected partial index state (chroma=%s, bm25=%s), rebuilding both indexes",
                chroma_exists,
                bm25_exists,
            )
            return True

        return force

    def _build_chunks(
        self, docs: list[dict]
    ) -> tuple[list[str], list[str], list[dict]]:
        """Convert documents into (chunks, ids, metadatas) ready for indexing."""
        all_chunks: list[str] = []
        all_ids: list[str] = []
        all_metadatas: list[dict] = []

        for doc in docs:
            chunks = chunk_by_headings(doc["content"])
            for i, chunk in enumerate(chunks):
                all_chunks.append(
                    create_contextual_chunk(doc["title"], doc["folder"], chunk)
                )
                all_ids.append(f"{doc['path']}::{i}")
                all_metadatas.append(
                    {
                        "path": doc["path"],
                        "title": doc["title"],
                        "folder": doc["folder"],
                        "chunk_index": i,
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
            stemmer=self._stemmer,
        )
        self._bm25 = bm25s.BM25(k1=settings.bm25_k1, b=settings.bm25_b)
        self._bm25.index(corpus_tokens)
        self._bm25_corpus = metadatas

        self.bm25_path.mkdir(parents=True, exist_ok=True)
        self._bm25.save(str(self.bm25_path), corpus=chunks)

        metadata_path = self.bm25_path / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadatas, f)

    def build_index(self, force: bool = False) -> int:
        """Build or update the search index. Returns number of chunks indexed."""
        force = self._reconcile_index_state(force)
        if not force:
            return self.collection.count()

        self._clear_chroma_collection()
        self._clear_bm25_index()

        logger.info("Loading documents...")
        docs = self.load_documents()
        logger.info("Found %s documents", len(docs))

        all_chunks, all_ids, all_metadatas = self._build_chunks(docs)

        if not all_chunks:
            logger.info("No chunks to index")
            return 0

        logger.info("Generating embeddings for %s chunks...", len(all_chunks))
        embeddings = self.backend.encode(all_chunks)

        self._persist_chroma(all_ids, all_chunks, embeddings, all_metadatas)
        self._persist_bm25(all_chunks, all_metadatas)

        logger.info(
            "Index complete: %s chunks (ChromaDB + BM25)",
            self.collection.count(),
        )
        return self.collection.count()

    def _clear_chroma_collection(self) -> None:
        """Drop and recreate the Chroma collection atomically without materializing ids."""
        try:
            self.client.delete_collection("wiki_docs")
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name="wiki_docs",
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
            "embedding_model": settings.embedding_model,
            "embedding_dims": settings.embedding_dims,
            "embedding_pooling": settings.embedding_pooling,
            "bm25_available": bm25 is not None,
            # Chunking configuration
            "chunking": {
                "use_tokens": settings.use_token_based_chunking,
                "enable_overlap": settings.enable_chunk_overlap,
                "char_chunk_size": settings.char_chunk_size,
                "char_overlap_size": settings.char_overlap_size,
                "token_chunk_size": settings.token_chunk_size,
                "token_overlap_size": settings.token_overlap_size,
            },
        }
