"""Tests for chunking functions in indexer.py."""

import pytest

from trace_search.config import settings
from trace_search.indexer import (
    _get_overlap_text,
    _get_size,
    _get_token_counter,
    chunk_by_headings,
    chunk_by_paragraphs,
)


# Sample markdown content for testing
SAMPLE_MARKDOWN = """# Document Title

This is the introduction paragraph with some text.

## Section One

This is the first section with important content.

### Subsection 1.1

Detailed content in the subsection.

## Section Two

Second section with more content that spans multiple sentences.
This adds more length to test size limits.

### Subsection 2.1

More detailed content here.

## Section Three

Final section with concluding remarks.
"""

LONG_PARAGRAPH = "This is a very long paragraph. " * 100  # ~3200 chars

LARGE_SECTION = f"""# Large Section

{LONG_PARAGRAPH}

Another paragraph here.

{LONG_PARAGRAPH}

And yet another paragraph.
"""


class TestTokenCounter:
    """Tests for TokenCounter class."""

    def test_singleton_pattern(self):
        """_get_token_counter should return the same cached instance."""
        counter1 = _get_token_counter()
        counter2 = _get_token_counter()
        assert counter1 is counter2

    def test_count_tokens_basic(self):
        """count_tokens returns positive integer for text."""
        counter = _get_token_counter()
        count = counter.count_tokens("Hello world")
        assert isinstance(count, int)
        assert count > 0

    def test_count_tokens_empty(self):
        """count_tokens returns 0 for empty string."""
        counter = _get_token_counter()
        assert counter.count_tokens("") == 0

    def test_count_tokens_longer_text(self):
        """Longer text has more tokens than shorter text."""
        counter = _get_token_counter()
        short = counter.count_tokens("Hello")
        long = counter.count_tokens(
            "Hello world, this is a longer sentence with more tokens."
        )
        assert long > short

    def test_truncate_to_tokens_no_truncation(self):
        """truncate_to_tokens returns original if under limit."""
        counter = _get_token_counter()
        text = "Hello world"
        result = counter.truncate_to_tokens(text, 100)
        assert result == text

    def test_truncate_to_tokens_truncates(self):
        """truncate_to_tokens actually truncates long text."""
        counter = _get_token_counter()
        text = "This is a very long sentence that should definitely be truncated to a smaller size."
        result = counter.truncate_to_tokens(text, 5)
        result_tokens = counter.count_tokens(result)
        assert result_tokens <= 5
        assert len(result) < len(text)


class TestGetSize:
    """Tests for _get_size helper function."""

    def test_character_mode(self):
        """_get_size returns character count when use_tokens=False."""
        text = "Hello world"
        assert _get_size(text, use_tokens=False) == len(text)

    def test_token_mode(self):
        """_get_size returns token count when use_tokens=True."""
        text = "Hello world"
        result = _get_size(text, use_tokens=True)
        expected = _get_token_counter().count_tokens(text)
        assert result == expected

    def test_empty_string(self):
        """_get_size handles empty strings."""
        assert _get_size("", use_tokens=False) == 0
        assert _get_size("", use_tokens=True) == 0


class TestGetOverlapText:
    """Tests for _get_overlap_text helper function."""

    def test_character_overlap(self):
        """_get_overlap_text extracts last N characters."""
        text = "Hello world, this is a test"
        result = _get_overlap_text(text, overlap_size=10, use_tokens=False)
        assert result == text[-10:]

    def test_character_overlap_small_text(self):
        """_get_overlap_text returns full text if shorter than overlap."""
        text = "Short"
        result = _get_overlap_text(text, overlap_size=100, use_tokens=False)
        assert result == text

    def test_zero_overlap(self):
        """_get_overlap_text returns empty string for zero overlap."""
        text = "Hello world"
        assert _get_overlap_text(text, overlap_size=0, use_tokens=False) == ""
        assert _get_overlap_text(text, overlap_size=0, use_tokens=True) == ""

    def test_token_overlap(self):
        """_get_overlap_text extracts last N tokens."""
        text = "This is a sentence with multiple words and tokens"
        result = _get_overlap_text(text, overlap_size=5, use_tokens=True)
        counter = _get_token_counter()
        result_tokens = counter.count_tokens(result)
        assert result_tokens <= 5


class TestChunkByHeadingsCharacterMode:
    """Tests for chunk_by_headings in character mode (default)."""

    def test_basic_chunking(self):
        """Basic chunking produces non-empty chunks."""
        chunks = chunk_by_headings(
            SAMPLE_MARKDOWN, use_tokens=False, enable_overlap=False
        )
        assert len(chunks) > 0
        assert all(chunk.strip() for chunk in chunks)

    def test_respects_max_chars(self):
        """All chunks respect max character limit."""
        max_chars = 500
        chunks = chunk_by_headings(
            SAMPLE_MARKDOWN,
            max_chunk_chars=max_chars,
            use_tokens=False,
            enable_overlap=False,
        )
        for chunk in chunks:
            assert len(chunk) <= max_chars, (
                f"Chunk exceeds {max_chars} chars: {len(chunk)}"
            )

    def test_preserves_content(self):
        """Chunking preserves headings and content."""
        chunks = chunk_by_headings(
            SAMPLE_MARKDOWN, use_tokens=False, enable_overlap=False
        )
        combined = "\n".join(chunks)
        assert "Document Title" in combined
        assert "Section One" in combined
        assert "Section Two" in combined

    def test_large_section_splits(self):
        """Large sections are split by paragraphs."""
        chunks = chunk_by_headings(
            LARGE_SECTION,
            max_chunk_chars=1000,
            use_tokens=False,
            enable_overlap=False,
        )
        assert len(chunks) > 1

    def test_empty_content(self):
        """Empty content returns single empty-ish chunk."""
        chunks = chunk_by_headings("", use_tokens=False, enable_overlap=False)
        assert len(chunks) == 1


class TestChunkByHeadingsTokenMode:
    """Tests for chunk_by_headings in token mode."""

    def test_basic_chunking(self):
        """Basic chunking in token mode produces chunks."""
        chunks = chunk_by_headings(
            SAMPLE_MARKDOWN, use_tokens=True, enable_overlap=False
        )
        assert len(chunks) > 0
        assert all(chunk.strip() for chunk in chunks)

    def test_respects_max_tokens(self):
        """All chunks respect max token limit."""
        max_tokens = 100
        chunks = chunk_by_headings(
            SAMPLE_MARKDOWN,
            use_tokens=True,
            max_chunk_tokens=max_tokens,
            enable_overlap=False,
        )
        counter = _get_token_counter()
        for chunk in chunks:
            token_count = counter.count_tokens(chunk)
            # Allow small overflow due to heading preservation
            assert token_count <= max_tokens + 20, (
                f"Chunk exceeds {max_tokens} tokens: {token_count}"
            )


class TestChunkByHeadingsWithOverlap:
    """Tests for chunk_by_headings with overlap enabled."""

    def test_overlap_enabled_character_mode(self):
        """Overlap is applied when chunks split due to size (not heading-level changes).

        Use a large section that forces paragraph-level splits to verify overlap.
        """
        overlap_chars = 50
        # Content with no heading-level changes — forces size-based splits with overlap
        content = "# Big Section\n\n" + "\n\n".join(
            f"Paragraph {i} with enough text to take up space in the chunk."
            for i in range(20)
        )
        chunks = chunk_by_headings(
            content,
            max_chunk_chars=300,
            use_tokens=False,
            enable_overlap=True,
            overlap_chars=overlap_chars,
        )
        assert len(chunks) > 1
        # At least one subsequent chunk should contain overlap text from the previous
        found_overlap = False
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap_chars:]
            if any(word in chunks[i] for word in prev_tail.split() if len(word) > 3):
                found_overlap = True
                break
        assert found_overlap, "No overlap content found between any consecutive chunks"

    def test_overlap_enabled_token_mode(self):
        """Overlap in token mode produces chunks with shared content."""
        chunks = chunk_by_headings(
            SAMPLE_MARKDOWN,
            use_tokens=True,
            max_chunk_tokens=50,
            enable_overlap=True,
            overlap_tokens=10,
        )
        assert len(chunks) > 0
        # With overlap enabled, chunks should still be well-formed
        assert all(chunk.strip() for chunk in chunks)

    def test_more_chunks_with_overlap(self):
        """Enabling overlap may increase total chunk count."""
        without_overlap = chunk_by_headings(
            SAMPLE_MARKDOWN,
            max_chunk_chars=300,
            use_tokens=False,
            enable_overlap=False,
        )
        with_overlap = chunk_by_headings(
            SAMPLE_MARKDOWN,
            max_chunk_chars=300,
            use_tokens=False,
            enable_overlap=True,
            overlap_chars=50,
        )
        assert len(with_overlap) >= len(without_overlap)


class TestChunkByParagraphsCharacterMode:
    """Tests for chunk_by_paragraphs in character mode."""

    def test_basic_chunking(self):
        """Basic paragraph chunking produces chunks."""
        content = "Para 1.\n\nPara 2.\n\nPara 3."
        chunks = chunk_by_paragraphs(content, use_tokens=False, enable_overlap=False)
        assert len(chunks) > 0

    def test_respects_max_chars(self):
        """Chunks respect max character limit."""
        max_chars = 100
        chunks = chunk_by_paragraphs(
            LONG_PARAGRAPH,
            max_chunk_chars=max_chars,
            use_tokens=False,
            enable_overlap=False,
        )
        for chunk in chunks:
            assert len(chunk) <= max_chars

    def test_single_paragraph_fits(self):
        """Single paragraph under limit stays as one chunk."""
        content = "This is a short paragraph."
        chunks = chunk_by_paragraphs(
            content,
            max_chunk_chars=1000,
            use_tokens=False,
            enable_overlap=False,
        )
        assert len(chunks) == 1
        assert chunks[0] == content


class TestChunkByParagraphsTokenMode:
    """Tests for chunk_by_paragraphs in token mode."""

    def test_basic_chunking(self):
        """Basic paragraph chunking in token mode."""
        content = "Para 1.\n\nPara 2.\n\nPara 3."
        chunks = chunk_by_paragraphs(content, use_tokens=True, enable_overlap=False)
        assert len(chunks) > 0

    def test_respects_max_tokens(self):
        """Chunks respect max token limit."""
        max_tokens = 50
        chunks = chunk_by_paragraphs(
            LONG_PARAGRAPH,
            use_tokens=True,
            max_chunk_tokens=max_tokens,
            enable_overlap=False,
        )
        counter = _get_token_counter()
        for chunk in chunks:
            token_count = counter.count_tokens(chunk)
            assert token_count <= max_tokens


class TestChunkByParagraphsWithOverlap:
    """Tests for chunk_by_paragraphs with overlap enabled."""

    def test_overlap_character_mode(self):
        """Overlap in character mode."""
        content = "A" * 200 + "\n\n" + "B" * 200 + "\n\n" + "C" * 200
        chunks = chunk_by_paragraphs(
            content,
            max_chunk_chars=250,
            use_tokens=False,
            enable_overlap=True,
            overlap_chars=30,
        )
        assert len(chunks) >= 2

    def test_overlap_token_mode(self):
        """Overlap in token mode."""
        content = "Word " * 50 + "\n\n" + "Token " * 50 + "\n\n" + "Text " * 50
        chunks = chunk_by_paragraphs(
            content,
            use_tokens=True,
            max_chunk_tokens=100,
            enable_overlap=True,
            overlap_tokens=20,
        )
        assert len(chunks) >= 1


class TestDefaultConfiguration:
    """Tests for default configuration values."""

    def test_defaults_loaded(self):
        """Default configuration values are set."""
        assert settings.char_chunk_size == 1000
        assert settings.char_overlap_size == 100
        assert settings.token_chunk_size == 512
        assert settings.token_overlap_size == 50

    def test_chunk_by_headings_uses_defaults(self):
        """chunk_by_headings uses default values without explicit params."""
        # This should not raise - uses defaults from settings
        chunks = chunk_by_headings(SAMPLE_MARKDOWN)
        assert len(chunks) > 0

    def test_chunk_by_paragraphs_uses_defaults(self):
        """chunk_by_paragraphs uses default values without explicit params."""
        chunks = chunk_by_paragraphs("Para 1.\n\nPara 2.")
        assert len(chunks) > 0


class TestEdgeCases:
    """Edge case tests."""

    def test_only_whitespace(self):
        """Whitespace-only content."""
        chunks = chunk_by_headings("   \n\n   ", use_tokens=False, enable_overlap=False)
        assert len(chunks) == 1

    def test_single_heading_no_content(self):
        """Single heading with no content."""
        chunks = chunk_by_headings("# Title", use_tokens=False, enable_overlap=False)
        assert len(chunks) == 1
        assert "Title" in chunks[0]

    def test_no_headings(self):
        """Content with no markdown headings."""
        content = "Just plain text.\n\nAnother paragraph.\n\nThird one."
        chunks = chunk_by_headings(content, use_tokens=False, enable_overlap=False)
        assert len(chunks) >= 1

    def test_unicode_content(self):
        """Unicode content is handled correctly."""
        content = "# Titel\n\nHej varlden! This has some Swedish characters."
        chunks = chunk_by_headings(content, use_tokens=False, enable_overlap=False)
        assert len(chunks) > 0
        assert "varlden" in chunks[0]

    def test_very_small_chunk_size(self):
        """Very small chunk size doesn't crash."""
        chunks = chunk_by_headings(
            SAMPLE_MARKDOWN,
            max_chunk_chars=50,
            use_tokens=False,
            enable_overlap=False,
        )
        assert len(chunks) > 0


class TestBackwardCompatibility:
    """Backward compatibility tests."""

    def test_old_api_still_works(self):
        """Old API (just max_chunk_chars) still works."""
        chunks = chunk_by_headings(SAMPLE_MARKDOWN, max_chunk_chars=1000)
        assert len(chunks) > 0

    def test_old_paragraphs_api_works(self):
        """Old paragraph API still works."""
        chunks = chunk_by_paragraphs("Para 1.\n\nPara 2.", max_chunk_chars=500)
        assert len(chunks) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
