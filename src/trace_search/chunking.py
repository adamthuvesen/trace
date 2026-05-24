"""Document chunking for indexing."""

from __future__ import annotations

import re
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


def _split_oversized_text(
    text: str,
    *,
    use_tokens: bool,
    max_size: int,
    overlap_size: int,
) -> list[str]:
    """Split one oversized text block into windows without losing content."""
    if _get_size(text, use_tokens) <= max_size:
        return [text]

    if use_tokens:
        return _get_token_counter().split_to_token_windows(
            text,
            max_tokens=max_size,
            overlap_tokens=overlap_size,
        )

    step = max_size - overlap_size if 0 < overlap_size < max_size else max_size
    return [text[start : start + max_size] for start in range(0, len(text), step)]


def _prepend_overlap_if_fits(
    overlap: str,
    chunk: str,
    *,
    use_tokens: bool,
    max_size: int,
) -> str:
    """Prefix overlap only when it does not force truncating the new chunk."""
    if not overlap:
        return chunk
    combined = f"{overlap}\n\n{chunk}"
    if _get_size(combined, use_tokens) <= max_size:
        return combined
    return chunk


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
                if pending_overlap and sub_chunks:
                    sub_chunks[0] = _prepend_overlap_if_fits(
                        pending_overlap,
                        sub_chunks[0],
                        use_tokens=use_tokens,
                        max_size=max_size,
                    )
                chunks.extend(sub_chunks)
                if sub_chunks:
                    pending_overlap = _get_overlap_text(
                        sub_chunks[-1], overlap_size, use_tokens
                    )
                current_chunk = ""
                current_level = None
            else:
                current_chunk = _prepend_overlap_if_fits(
                    pending_overlap,
                    section,
                    use_tokens=use_tokens,
                    max_size=max_size,
                )
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
        if not para:
            continue
        para_size = _get_size(para, use_tokens)

        if para_size > max_size:
            if current_chunk:
                chunks.append(current_chunk)
                pending_overlap = _get_overlap_text(
                    current_chunk, overlap_size, use_tokens
                )
                current_chunk = ""

            sub_chunks = _split_oversized_text(
                para,
                use_tokens=use_tokens,
                max_size=max_size,
                overlap_size=overlap_size,
            )
            if pending_overlap and sub_chunks:
                sub_chunks[0] = _prepend_overlap_if_fits(
                    pending_overlap,
                    sub_chunks[0],
                    use_tokens=use_tokens,
                    max_size=max_size,
                )
                pending_overlap = ""
            chunks.extend(sub_chunks)
            if sub_chunks:
                pending_overlap = _get_overlap_text(
                    sub_chunks[-1], overlap_size, use_tokens
                )
            continue

        if current_chunk:
            candidate = f"{current_chunk}\n\n{para}"
        else:
            candidate = _prepend_overlap_if_fits(
                pending_overlap,
                para,
                use_tokens=use_tokens,
                max_size=max_size,
            )

        if _get_size(candidate, use_tokens) <= max_size:
            current_chunk = candidate
            if pending_overlap:
                pending_overlap = ""
        else:
            if current_chunk:
                chunks.append(current_chunk)
                pending_overlap = _get_overlap_text(
                    current_chunk, overlap_size, use_tokens
                )

            # Start new chunk with overlap if applicable
            current_chunk = _prepend_overlap_if_fits(
                pending_overlap,
                para,
                use_tokens=use_tokens,
                max_size=max_size,
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
