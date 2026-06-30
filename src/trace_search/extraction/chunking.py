"""Document chunking for indexing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from trace_search.config import settings


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

    def split_to_token_windows(
        self,
        text: str,
        *,
        max_tokens: int,
        overlap_tokens: int,
    ) -> list[str]:
        """Split text into token windows without dropping content."""
        self._ensure_tokenizer()
        tokens = self._tokenizer.encode(text, add_special_tokens=False)
        if len(tokens) <= max_tokens:
            return [text]

        step = (
            max_tokens - overlap_tokens
            if 0 < overlap_tokens < max_tokens
            else max_tokens
        )
        chunks = []
        for start in range(0, len(tokens), step):
            window = tokens[start : start + max_tokens]
            if not window:
                break
            chunks.append(self._tokenizer.decode(window, skip_special_tokens=True))
            if start + max_tokens >= len(tokens):
                break
        return chunks


@lru_cache(maxsize=1)
def _get_token_counter() -> TokenCounter:
    """Get singleton TokenCounter instance (lazy-loaded)."""
    return TokenCounter()


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
    return chunk[-overlap_size:] if len(chunk) > overlap_size else chunk


@dataclass(frozen=True)
class ChunkingParams:
    """Resolved chunk sizing and overlap behavior."""

    use_tokens: bool
    max_size: int
    overlap_size: int

    def size(self, text: str) -> int:
        return _get_size(text, self.use_tokens)

    def overlap(self, chunk: str) -> str:
        return _get_overlap_text(chunk, self.overlap_size, self.use_tokens)


def _split_oversized_text(
    text: str,
    *,
    params: ChunkingParams,
) -> list[str]:
    """Split one oversized text block into windows without losing content."""
    if params.size(text) <= params.max_size:
        return [text]

    if params.use_tokens:
        return _get_token_counter().split_to_token_windows(
            text,
            max_tokens=params.max_size,
            overlap_tokens=params.overlap_size,
        )

    step = (
        params.max_size - params.overlap_size
        if 0 < params.overlap_size < params.max_size
        else params.max_size
    )
    return [
        text[start : start + params.max_size] for start in range(0, len(text), step)
    ]


def _prepend_overlap_if_fits(
    overlap: str,
    chunk: str,
    *,
    params: ChunkingParams,
) -> str:
    """Prefix overlap only when it does not force truncating the new chunk."""
    if not overlap:
        return chunk
    combined = f"{overlap}\n\n{chunk}"
    if params.size(combined) <= params.max_size:
        return combined
    return chunk


def _merge_tiny_chunks(
    chunks: list[str],
    *,
    params: ChunkingParams,
) -> list[str]:
    """Merge tiny chunks into neighbors to preserve context and reduce fragmentation."""
    if len(chunks) <= 1:
        return chunks

    if params.use_tokens:
        tiny_threshold = max(5, int(params.max_size * 0.1))
    else:
        tiny_threshold = (
            200 if params.max_size >= 200 else max(10, int(params.max_size * 0.5))
        )

    merged: list[str] = []
    i = 0
    while i < len(chunks):
        chunk = chunks[i]
        if params.size(chunk) >= tiny_threshold:
            merged.append(chunk)
            i += 1
            continue

        # Prefer merging with next chunk to keep heading context with its section.
        if i + 1 < len(chunks):
            combined_next = f"{chunk}\n\n{chunks[i + 1]}"
            if params.size(combined_next) <= params.max_size:
                merged.append(combined_next)
                i += 2
                continue

        # Fall back to previous chunk if it fits.
        if merged:
            combined_prev = f"{merged[-1]}\n\n{chunk}"
            if params.size(combined_prev) <= params.max_size:
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
    params: ChunkingParams,
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
        if params.size(combined) <= params.max_size:
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
) -> ChunkingParams:
    """Resolve chunking parameters with defaults from settings.

    Returns:
        Resolved chunking parameters.
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

    return ChunkingParams(
        use_tokens=use_tokens,
        max_size=max_size,
        overlap_size=overlap_size,
    )


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
    params = _resolve_chunking_params(
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
        section_size = params.size(section)
        current_size = params.size(current_chunk)

        if current_chunk and _heading_level_changed(current_level, section_level):
            chunks.append(current_chunk)
            current_chunk = ""
            current_level = None
            pending_overlap = ""
            current_size = 0

        if current_size + section_size <= params.max_size:
            current_chunk += "\n\n" + section if current_chunk else section
            if current_chunk == section:
                current_level = section_level
        else:
            if current_chunk:
                chunks.append(current_chunk)
                pending_overlap = params.overlap(current_chunk)
                current_level = None

            # If section itself is too large, split it further
            if section_size > params.max_size:
                sub_chunks = chunk_by_paragraphs(
                    section,
                    max_chunk_chars=max_chunk_chars,
                    use_tokens=params.use_tokens,
                    max_chunk_tokens=max_chunk_tokens,
                    overlap_chars=overlap_chars,
                    overlap_tokens=overlap_tokens,
                    enable_overlap=enable_overlap,
                )
                heading_context = _extract_heading_context(section)
                sub_chunks = _prefix_heading_context(
                    sub_chunks,
                    heading_context,
                    params=params,
                )
                if pending_overlap and sub_chunks:
                    sub_chunks[0] = _prepend_overlap_if_fits(
                        pending_overlap,
                        sub_chunks[0],
                        params=params,
                    )
                chunks.extend(sub_chunks)
                if sub_chunks:
                    pending_overlap = params.overlap(sub_chunks[-1])
                current_chunk = ""
                current_level = None
            else:
                current_chunk = _prepend_overlap_if_fits(
                    pending_overlap,
                    section,
                    params=params,
                )
                pending_overlap = ""
                current_level = section_level

    if current_chunk:
        chunks.append(current_chunk)

    if not chunks:
        return [content]

    return _merge_tiny_chunks(
        chunks,
        params=params,
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
    params = _resolve_chunking_params(
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
        if not para:
            continue
        para_size = params.size(para)

        if para_size > params.max_size:
            if current_chunk:
                chunks.append(current_chunk)
                pending_overlap = params.overlap(current_chunk)
                current_chunk = ""

            sub_chunks = _split_oversized_text(
                para,
                params=params,
            )
            if pending_overlap and sub_chunks:
                sub_chunks[0] = _prepend_overlap_if_fits(
                    pending_overlap,
                    sub_chunks[0],
                    params=params,
                )
                pending_overlap = ""
            chunks.extend(sub_chunks)
            if sub_chunks:
                pending_overlap = params.overlap(sub_chunks[-1])
            continue

        if current_chunk:
            candidate = f"{current_chunk}\n\n{para}"
        else:
            candidate = _prepend_overlap_if_fits(
                pending_overlap,
                para,
                params=params,
            )

        if params.size(candidate) <= params.max_size:
            current_chunk = candidate
            if pending_overlap:
                pending_overlap = ""
        else:
            if current_chunk:
                chunks.append(current_chunk)
                pending_overlap = params.overlap(current_chunk)

            # Start new chunk with overlap if applicable
            current_chunk = _prepend_overlap_if_fits(
                pending_overlap,
                para,
                params=params,
            )
            pending_overlap = ""

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def create_contextual_chunk(title: str, folder: str, chunk: str) -> str:
    """Add document context to chunk (Anthropic's contextual retrieval pattern)."""
    return f"Document: {title}\nFolder: {folder}\n\n{chunk}"


def extract_breadcrumb(chunk: str, title: str) -> str:
    """Extract a readable heading breadcrumb from a chunk."""
    headings = []
    for line in chunk.splitlines():
        stripped = line.strip()
        match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if match:
            headings.append(match.group(2).strip())
    if headings:
        return " > ".join(headings[-3:])
    return title
