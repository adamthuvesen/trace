import pytest

from trace_search.config import settings
from trace_search.extraction.extractors import (
    SUPPORTED_EXTENSIONS,
)
from trace_search.server.mcp_tools import build_multi_mcp

SERVER_TOOL_NAMES = (
    "search",
    "semantic_search",
    "keyword_search",
    "search_hybrid",
    "get_document",
    "list_documents",
    "index_stats",
    "reindex",
    "doctor",
)
CODE_EXTENSIONS = (".sql", ".py", ".ts", ".tsx", ".yml", ".yaml")


@pytest.fixture()
def multi_mcp(tmp_path):
    """Build a multi-collection MCP with a minimal test KB."""
    kb = tmp_path / "test-kb"
    kb.mkdir()
    (kb / "hello.md").write_text("# Hello\n\nWorld", encoding="utf-8")
    return build_multi_mcp("test-server", {"test-kb": kb})


class TestSupportedExtensions:
    def test_all_extensions_present(self):
        expected = {
            ".md",
            ".sql",
            ".py",
            ".yml",
            ".yaml",
            ".ts",
            ".tsx",
        }
        assert expected == SUPPORTED_EXTENSIONS


class TestToolDefinitions:
    @pytest.mark.parametrize("tool_name", SERVER_TOOL_NAMES)
    def test_server_tool_exists(self, multi_mcp, tool_name):
        _, tools = multi_mcp
        tool = tools[tool_name]
        assert callable(tool)
        assert tool.__name__ == tool_name

    def test_all_tools_are_non_none(self, multi_mcp):
        _, tools = multi_mcp
        for name, tool in tools.items():
            assert callable(tool), f"Tool {name} is not callable"


class TestToolDocstrings:
    def test_search_has_description(self, multi_mcp):
        _, tools = multi_mcp
        search = tools["search"]
        assert search.__doc__ is not None
        assert "BM25" in search.__doc__ or "keyword" in search.__doc__

    def test_semantic_search_has_description(self, multi_mcp):
        _, tools = multi_mcp
        assert "semantic" in (tools["semantic_search"].__doc__ or "").lower()

    def test_keyword_search_description_matches_direct_bm25_behavior(self, multi_mcp):
        _, tools = multi_mcp
        desc = (tools["keyword_search"].__doc__ or "").lower()
        assert "bm25" in desc
        assert "alias" not in desc

    def test_hybrid_search_has_description(self, multi_mcp):
        desc = (tools["search_hybrid"].__doc__ or "").lower() if (tools := multi_mcp[1]) else ""
        assert "hybrid" in desc or "combined" in desc


class TestMCPServer:
    def test_mcp_has_name(self, multi_mcp):
        mcp, _ = multi_mcp
        assert mcp.name == "test-server"


class TestServerImports:
    def test_import_format_results(self):
        from trace_search.retrieval.formatting import format_results

        assert callable(format_results)

    def test_import_semantic_search_class(self):
        from trace_search.retrieval.search import SemanticSearch

        assert SemanticSearch is not None

    def test_import_keyword_search_class(self):
        from trace_search.retrieval.search import KeywordSearch

        assert KeywordSearch is not None

    def test_import_hybrid_search_class(self):
        from trace_search.retrieval.search import HybridSearch

        assert HybridSearch is not None

    def test_import_wiki_indexer(self):
        from trace_search.indexing.wiki_indexer import WikiIndexer

        assert WikiIndexer is not None

    def test_import_settings(self):
        assert settings is not None
        assert hasattr(settings, "kb_path")
        assert hasattr(settings, "embedding_model")

    def test_import_collection_registry(self):
        from trace_search.collections.collection_registry import CollectionRegistry

        assert CollectionRegistry is not None


class TestGetDocumentFormats:
    def test_get_document_and_list_documents_read_markdown(self, tmp_path):
        (tmp_path / "intro.md").write_text("# Format fixture\n\nMarkdown content")
        _, tools = build_multi_mcp("formats", {"documents": tmp_path})

        assert "Format fixture" in tools["get_document"]("intro.md")
        assert "intro.md" in tools["list_documents"]()


class TestGetDocumentCodeFiles:
    @pytest.mark.parametrize("extension", CODE_EXTENSIONS)
    def test_get_document_handles_supported_code_extensions(self, extension):
        assert extension in SUPPORTED_EXTENSIONS


class TestGetDocumentErrorEnvelope:
    def test_unsupported_extension_raises_tool_error(self, tmp_path):
        (tmp_path / "notes.psd").write_bytes(b"\x00fake")
        _, tools = build_multi_mcp("env-test", {"docs": tmp_path})

        from fastmcp.exceptions import ToolError

        with pytest.raises(ToolError, match="Unsupported"):
            tools["get_document"]("notes.psd")

    def test_multi_collection_response_includes_collection_tag(self, tmp_path):
        docs = tmp_path / "docs"
        brain = tmp_path / "brain"
        docs.mkdir()
        brain.mkdir()
        (docs / "intro.md").write_text("# Intro\n\nContent", encoding="utf-8")

        _, tools = build_multi_mcp("tag-test", {"docs": docs, "brain": brain})

        result = tools["get_document"]("intro.md")

        assert "**Collection:** docs" in result

    def test_single_collection_response_omits_collection_tag(self, tmp_path):
        (tmp_path / "solo.md").write_text("# Solo\n\nContent", encoding="utf-8")

        _, tools = build_multi_mcp("solo-test", {"docs": tmp_path})

        result = tools["get_document"]("solo.md")

        assert "**Collection:**" not in result

    def test_get_document_respects_indexer_exclusions(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "secret.md").write_text(
            "# Secret\n\nShould not be readable",
            encoding="utf-8",
        )

        _, tools = build_multi_mcp("excluded-doc-test", {"docs": tmp_path})

        from fastmcp.exceptions import ToolError

        with pytest.raises(ToolError, match="Document not found"):
            tools["get_document"]("node_modules/secret.md")


class TestCollectionRebuild:
    @staticmethod
    def _collection(tmp_path):
        from trace_search.collections.collection_registry import Collection

        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "doc.md").write_text("# Doc\n\ncontent", encoding="utf-8")
        return Collection(name="test", kb_path=kb, index_path=tmp_path / "idx")

    def test_probe_path_skips_implicit_build_without_poisoning_later_search(self, tmp_path):
        """Doctor probes need existing indexes without triggering reindex."""
        from tests.test_runtime_hardening import FakeBackend

        col = self._collection(tmp_path)

        assert not col.indexer(FakeBackend, build_if_missing=False).has_index()
        assert col.indexer(FakeBackend).has_index()

    def test_rebuild_returns_chunk_count_and_threads_force(self, tmp_path):
        from tests.test_runtime_hardening import FakeBackend
        from trace_search.indexing.index_store import read_current

        col = self._collection(tmp_path)

        assert col.rebuild(FakeBackend) == 1
        first = read_current(col.index_path)
        assert col.rebuild(FakeBackend) == 1
        assert read_current(col.index_path) == first  # incremental no-op
        assert col.rebuild(FakeBackend, force=True) == 1
        assert read_current(col.index_path) != first


class TestReindexForceFlag:
    def test_mcp_reindex_threads_force_into_collection(self, tmp_path):
        """The MCP reindex tool must thread `force` down to Collection.rebuild."""
        from unittest.mock import patch

        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "doc.md").write_text("# Doc\n\ncontent", encoding="utf-8")

        _, tools = build_multi_mcp("force-test", {"docs": kb})

        with patch(
            "trace_search.collections.collection_registry.Collection.rebuild",
            return_value=7,
            autospec=True,
        ) as rebuild_mock:
            result = tools["reindex"](force=True)

        assert "(forced rebuild)" in result
        assert "7 chunks indexed" in result
        rebuild_mock.assert_called_once()
        _, kwargs = rebuild_mock.call_args[0], rebuild_mock.call_args.kwargs
        assert kwargs.get("force") is True

    def test_mcp_reindex_defaults_to_incremental(self, tmp_path):
        """Omitting `force` reindexes incrementally and does not advertise a rebuild."""
        from unittest.mock import patch

        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "doc.md").write_text("# Doc\n\ncontent", encoding="utf-8")

        _, tools = build_multi_mcp("incremental-test", {"docs": kb})

        with patch(
            "trace_search.collections.collection_registry.Collection.rebuild",
            return_value=2,
            autospec=True,
        ) as rebuild_mock:
            result = tools["reindex"]()

        assert "(forced rebuild)" not in result
        assert "2 chunks indexed" in result
        kwargs = rebuild_mock.call_args.kwargs
        assert kwargs.get("force") is False


class TestListDocumentsMultiCollectionWalk:
    def test_each_collection_walked_exactly_once(self, tmp_path):
        """List documents scans each collection directory once."""
        import os
        from unittest.mock import patch

        docs = tmp_path / "docs"
        brain = tmp_path / "brain"
        docs.mkdir()
        brain.mkdir()
        (docs / "a.md").write_text("# A\n\ncontent", encoding="utf-8")
        (brain / "b.md").write_text("# B\n\ncontent", encoding="utf-8")

        _, tools = build_multi_mcp("walk-test", {"docs": docs, "brain": brain})

        scans = []
        original_scan = os.scandir

        def scan(path):
            scans.append(path)
            return original_scan(path)

        with patch.object(os, "scandir", scan):
            tools["list_documents"](limit=50)

        assert scans == [docs, brain]


class TestListDocumentsDeterminism:
    def test_list_documents_is_stable_and_sorted(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "x.md").write_text("# X Doc\n\nContent", encoding="utf-8")
        (tmp_path / "a" / "a.sql").write_text("SELECT 1;", encoding="utf-8")
        (tmp_path / "b" / "z.md").write_text("# Z Doc\n\nContent", encoding="utf-8")

        _, tools = build_multi_mcp("det-test", {"docs": tmp_path})

        first = tools["list_documents"](limit=2)
        second = tools["list_documents"](limit=2)

        assert first == second
        assert "Found 2 documents" in first
        assert "`a/a.sql`" in first
        assert "`a/x.md`" in first
        assert "`b/z.md`" not in first

    def test_list_documents_uses_indexer_exclusions(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "docs" / "intro.md").write_text("# Intro\n\nContent", encoding="utf-8")
        (tmp_path / "node_modules" / "package.md").write_text(
            "# Package\n\nShould not list",
            encoding="utf-8",
        )

        _, tools = build_multi_mcp("exclude-test", {"docs": tmp_path})
        result = tools["list_documents"](limit=50)

        assert "`docs/intro.md`" in result
        assert "node_modules" not in result

    def test_list_documents_skips_outside_symlink(self, tmp_path):
        kb = tmp_path / "kb"
        outside = tmp_path / "outside"
        kb.mkdir()
        outside.mkdir()
        (kb / "intro.md").write_text("# Intro\n\nContent", encoding="utf-8")
        target = outside / "secret.md"
        target.write_text("# Secret\n\nShould not list", encoding="utf-8")
        (kb / "secret-link.md").symlink_to(target)

        _, tools = build_multi_mcp("symlink-test", {"docs": kb})
        result = tools["list_documents"](limit=50)

        assert "`intro.md`" in result
        assert "secret-link.md" not in result
