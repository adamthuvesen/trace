"""Tests for multi-collection knowledge server."""

import pytest

from trace_search.config import Settings


class TestKBCollectionsParsing:
    """Test KB_COLLECTIONS config parsing."""

    def test_parse_two_collections(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        kb1 = tmp_path / "wiki"
        kb2 = tmp_path / "ai-context"
        kb1.mkdir()
        kb2.mkdir()

        s = Settings(kb_collections=f"wiki:{kb1},ai-context:{kb2}")
        result = s.parsed_collections
        assert set(result.keys()) == {"wiki", "ai-context"}
        assert result["wiki"] == kb1
        assert result["ai-context"] == kb2

    def test_fallback_to_kb_path(self, tmp_path):
        kb = tmp_path / "docs"
        kb.mkdir()

        s = Settings(kb_path=kb)
        result = s.parsed_collections
        assert result == {"docs": kb}

    def test_raises_when_neither_set(self, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        monkeypatch.delenv("KB_COLLECTIONS", raising=False)
        s = Settings()
        with pytest.raises(ValueError, match="Set KB_COLLECTIONS or KB_PATH"):
            _ = s.parsed_collections

    def test_raises_when_both_set(self, tmp_path):
        kb = tmp_path / "docs"
        kb.mkdir()
        s = Settings(kb_path=kb, kb_collections=f"docs:{kb}")
        with pytest.raises(
            ValueError, match="KB_COLLECTIONS.*KB_PATH|KB_PATH.*KB_COLLECTIONS"
        ):
            _ = s.parsed_collections

    def test_only_kb_collections_works(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        kb = tmp_path / "wiki"
        kb.mkdir()
        s = Settings(kb_collections=f"wiki:{kb}")
        result = s.parsed_collections
        assert result == {"wiki": kb}

    def test_only_kb_path_works(self, tmp_path):
        kb = tmp_path / "docs"
        kb.mkdir()
        s = Settings(kb_path=kb)
        result = s.parsed_collections
        assert result == {"docs": kb}

    def test_invalid_format_raises(self, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        s = Settings(kb_collections="no-colon-here")
        with pytest.raises(ValueError, match="Invalid KB_COLLECTIONS entry"):
            _ = s.parsed_collections

    def test_nonexistent_path_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        s = Settings(kb_collections=f"wiki:{tmp_path / 'nope'}")
        with pytest.raises(ValueError, match="does not exist"):
            _ = s.parsed_collections

    def test_file_path_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KB_PATH", raising=False)
        f = tmp_path / "file.txt"
        f.write_text("hi")
        s = Settings(kb_collections=f"wiki:{f}")
        with pytest.raises(ValueError, match="not a directory"):
            _ = s.parsed_collections


class TestCollectionRegistry:
    """Test CollectionRegistry initialization and routing."""

    def test_collection_names_sorted(self, tmp_path):
        from trace_search.server_app import CollectionRegistry

        kb1 = tmp_path / "beta"
        kb2 = tmp_path / "alpha"
        kb1.mkdir()
        kb2.mkdir()

        reg = CollectionRegistry({"beta": kb1, "alpha": kb2})
        assert reg.collection_names == ["alpha", "beta"]

    def test_default_index_root_stays_inside_collection_kb(self, tmp_path):
        from trace_search.server_app import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()

        reg = CollectionRegistry({"docs": kb})
        assert reg.collections["docs"].index_path == kb / ".mcp-search" / "indexes"

    def test_explicit_index_root_uses_collection_subdir(self, tmp_path):
        from trace_search.server_app import CollectionRegistry

        kb = tmp_path / "docs"
        index_root = tmp_path / "indexes"
        kb.mkdir()

        reg = CollectionRegistry({"docs": kb}, index_root=index_root)
        assert reg.collections["docs"].index_path == index_root / "docs"

    def test_resolve_specific(self, tmp_path):
        from trace_search.server_app import CollectionRegistry

        kb = tmp_path / "wiki"
        kb.mkdir()

        reg = CollectionRegistry({"wiki": kb})
        cols = reg._resolve("wiki")
        assert len(cols) == 1
        assert cols[0].name == "wiki"

    def test_resolve_unknown_raises(self, tmp_path):
        from trace_search.server_app import CollectionRegistry

        kb = tmp_path / "wiki"
        kb.mkdir()

        reg = CollectionRegistry({"wiki": kb})
        with pytest.raises(ValueError, match="Unknown collection 'nope'"):
            reg._resolve("nope")

    def test_resolve_all(self, tmp_path):
        from trace_search.server_app import CollectionRegistry

        kb1 = tmp_path / "a"
        kb2 = tmp_path / "b"
        kb1.mkdir()
        kb2.mkdir()

        reg = CollectionRegistry({"a": kb1, "b": kb2})
        assert len(reg._resolve(None)) == 2
        assert len(reg._resolve("all")) == 2


class TestCollectionReset:
    """Test Collection.reset() clears all cached slots."""

    def test_reset_clears_all_slots(self, tmp_path):
        from unittest.mock import MagicMock

        from trace_search.server_app import Collection

        col = Collection(name="x", kb_path=tmp_path, index_path=tmp_path)
        col._indexer = MagicMock()
        col._semantic = MagicMock()
        col._keyword = MagicMock()
        col._hybrid = MagicMock()

        col.reset()

        assert col._indexer is None
        assert col._semantic is None
        assert col._keyword is None
        assert col._hybrid is None


class TestListDocumentsLimit:
    """Test list_documents honors limit as the sole bound."""

    def test_limit_respected_single_folder(self, tmp_path):
        from trace_search.server_app import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()
        folder = kb / "section"
        folder.mkdir()
        for i in range(25):
            (folder / f"doc_{i:02d}.md").write_text(f"# Doc {i}\n\nContent.")

        reg = CollectionRegistry({"docs": kb})
        result = reg.list_documents(folder=None, limit=10, collection=None)
        # Count listed docs (lines starting with "- **")
        listed = [line for line in result.splitlines() if line.startswith("- **")]
        assert len(listed) == 10

    def test_limit_larger_than_folder_returns_all(self, tmp_path):
        from trace_search.server_app import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()
        folder = kb / "section"
        folder.mkdir()
        for i in range(5):
            (folder / f"doc_{i}.md").write_text(f"# Doc {i}\n\nContent.")

        reg = CollectionRegistry({"docs": kb})
        result = reg.list_documents(folder=None, limit=50, collection=None)
        listed = [line for line in result.splitlines() if line.startswith("- **")]
        assert len(listed) == 5


class TestGetDocumentWarning:
    """Test get_document emits warning on traversal rejection."""

    def test_traversal_rejection_emits_warning(self, tmp_path, caplog):
        import logging

        from trace_search.server_app import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()

        reg = CollectionRegistry({"docs": kb})
        with caplog.at_level(logging.WARNING, logger="trace_search.server_app"):
            result = reg.get_document("../../etc/passwd", "docs")

        assert "rejected traversal" in caplog.text
        assert "Document not found" in result

    def test_extraction_failure_emits_warning(self, tmp_path, caplog):
        import logging
        from unittest.mock import patch

        from trace_search.server_app import CollectionRegistry

        kb = tmp_path / "docs"
        kb.mkdir()
        doc = kb / "broken.md"
        doc.write_text("# Broken")

        reg = CollectionRegistry({"docs": kb})
        with caplog.at_level(logging.WARNING, logger="trace_search.server_app"):
            with patch(
                "trace_search.server_app.extract_content",
                side_effect=RuntimeError("disk read failed"),
            ):
                result = reg.get_document("broken.md", "docs")

        assert "extraction failed" in caplog.text
        assert "broken.md" in caplog.text
        assert "disk read failed" in caplog.text
        assert result.startswith("Error reading document:")


class TestBuildMultiMcp:
    """Test build_multi_mcp creates server with collection-aware tools."""

    def test_tools_have_collection_param(self, tmp_path):
        from trace_search.server_app import build_multi_mcp

        kb = tmp_path / "docs"
        kb.mkdir()

        mcp, tools = build_multi_mcp("test-trace", {"docs": kb})
        assert mcp.name == "test-trace"
        assert set(tools.keys()) == {
            "search",
            "semantic_search",
            "keyword_search",
            "search_hybrid",
            "get_document",
            "list_documents",
            "index_stats",
            "reindex",
            "doctor",
        }

    def test_instructions_list_collections(self, tmp_path):
        from trace_search.server_app import _build_multi_instructions

        result = _build_multi_instructions(["ai-context", "wiki"])
        assert '"ai-context"' in result
        assert '"wiki"' in result
        assert "collection" in result


class TestMergeResults:
    """Test result merging across collections."""

    def test_merge_interleaves_by_score(self):
        from trace_search.server_app import CollectionRegistry

        results_a = [
            {"path": "a.md", "score": 5.0, "source": "keyword"},
            {"path": "b.md", "score": 3.0, "source": "keyword"},
        ]
        results_b = [
            {"path": "c.md", "score": 4.0, "source": "keyword"},
            {"path": "d.md", "score": 1.0, "source": "keyword"},
        ]
        merged = CollectionRegistry._merge_results(
            [results_a, results_b],
            top_k=3,
            collection_names=["a", "b"],
        )
        assert len(merged) == 3
        assert merged[0]["path"] == "a.md"
        assert merged[0]["collection"] == "a"
        assert merged[1]["path"] == "c.md"
        assert merged[1]["collection"] == "b"
        assert merged[2]["path"] == "b.md"

    def test_merge_respects_top_k(self):
        from trace_search.server_app import CollectionRegistry

        results = [
            {"path": f"{i}.md", "score": float(i), "source": "keyword"}
            for i in range(10)
        ]
        merged = CollectionRegistry._merge_results(
            [results], top_k=3, collection_names=["x"]
        )
        assert len(merged) == 3


class TestResolveAllCaseInsensitive:
    """Tests for case-insensitive 'all' handling in _resolve."""

    def _make_registry(self, tmp_path):
        from trace_search.server_app import CollectionRegistry

        wiki = tmp_path / "wiki"
        brain = tmp_path / "brain"
        wiki.mkdir()
        brain.mkdir()
        return CollectionRegistry({"wiki": wiki, "brain": brain})

    def test_resolve_all_lowercase(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg._resolve("all")
        assert len(result) == 2

    def test_resolve_all_uppercase(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg._resolve("ALL")
        assert len(result) == 2

    def test_resolve_all_mixed_case(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg._resolve("All")
        assert len(result) == 2

    def test_resolve_none_returns_all(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg._resolve(None)
        assert len(result) == 2

    def test_resolve_unknown_raises(self, tmp_path):
        reg = self._make_registry(tmp_path)
        with pytest.raises(ValueError, match="wiki"):
            reg._resolve("Wiki")

    def test_resolve_known_collection_case_sensitive(self, tmp_path):
        reg = self._make_registry(tmp_path)
        result = reg._resolve("wiki")
        assert len(result) == 1
        assert result[0].name == "wiki"


class TestTraceServerImport:
    """Test that trace_server module can be imported without KB env vars."""

    def test_import_succeeds(self):
        import trace_search.trace_server as ks

        assert hasattr(ks, "main")
        assert callable(ks.main)
