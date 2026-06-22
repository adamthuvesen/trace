"""Tests for MCP server functions."""

import pytest

from trace_search.config import settings
from trace_search.indexer import (
    SUPPORTED_EXTENSIONS,
    extract_csv_content,
    extract_docx_content,
    extract_pdf_content,
    extract_pptx_content,
)
from trace_search.server_app import build_multi_mcp

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
CODE_EXTENSIONS = (".sql", ".py", ".ts", ".tsx", ".yml", ".yaml", ".ipynb")


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
            ".pdf",
            ".docx",
            ".pptx",
            ".csv",
            ".sql",
            ".py",
            ".yml",
            ".yaml",
            ".ts",
            ".tsx",
            ".ipynb",
        }
        assert SUPPORTED_EXTENSIONS == expected


class TestToolDefinitions:
    @pytest.mark.parametrize("tool_name", SERVER_TOOL_NAMES)
    def test_server_tool_exists(self, multi_mcp, tool_name):
        _, tools = multi_mcp
        tool = tools[tool_name]
        assert tool is not None
        assert hasattr(tool, "name")
        assert tool.name == tool_name

    def test_all_tools_are_non_none(self, multi_mcp):
        _, tools = multi_mcp
        for name, tool in tools.items():
            assert tool is not None, f"Tool {name} is None"
            assert hasattr(tool, "name"), f"Tool {name} missing 'name' attribute"


class TestToolDocstrings:
    def test_search_has_description(self, multi_mcp):
        _, tools = multi_mcp
        search = tools["search"]
        assert search.description is not None
        assert "BM25" in search.description or "keyword" in search.description

    def test_semantic_search_has_description(self, multi_mcp):
        _, tools = multi_mcp
        assert "semantic" in tools["semantic_search"].description.lower()

    def test_keyword_search_description_matches_direct_bm25_behavior(self, multi_mcp):
        _, tools = multi_mcp
        desc = tools["keyword_search"].description.lower()
        assert "bm25" in desc
        assert "alias" not in desc

    def test_hybrid_search_has_description(self, multi_mcp):
        desc = (
            tools["search_hybrid"].description.lower()
            if (tools := multi_mcp[1])
            else ""
        )
        assert "hybrid" in desc or "combined" in desc


class TestMCPServer:
    def test_mcp_has_name(self, multi_mcp):
        mcp, _ = multi_mcp
        assert mcp.name == "test-server"


class TestServerImports:
    def test_import_format_results(self):
        from trace_search.retrieval.search import format_results

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
        from trace_search.indexer import WikiIndexer

        assert WikiIndexer is not None

    def test_import_settings(self):
        assert settings is not None
        assert hasattr(settings, "kb_path")
        assert hasattr(settings, "embedding_model")

    def test_import_collection_registry(self):
        from trace_search.server_app import CollectionRegistry

        assert CollectionRegistry is not None


@pytest.mark.slow
class TestGetDocumentLogic:
    def test_md_file_extraction(self, wiki_path):
        md_files = list(wiki_path.rglob("*.md"))
        if not md_files:
            pytest.skip("No MD files found in wiki")
        content = md_files[0].read_text(encoding="utf-8")
        assert isinstance(content, str)
        assert len(content) > 0

    def test_pptx_file_extraction(self, wiki_path):
        pptx_files = list(wiki_path.rglob("*.pptx"))
        if not pptx_files:
            pytest.skip("No PPTX files found in wiki")
        content = extract_pptx_content(pptx_files[0])
        assert isinstance(content, str)
        assert "[Slide" in content

    def test_pdf_file_extraction(self, wiki_path):
        pdf_files = list(wiki_path.rglob("*.pdf"))
        if not pdf_files:
            pytest.skip("No PDF files found in wiki")
        content = extract_pdf_content(pdf_files[0])
        assert isinstance(content, str)

    def test_docx_file_extraction(self, wiki_path):
        docx_files = list(wiki_path.rglob("*.docx"))
        if not docx_files:
            pytest.skip("No DOCX files found in wiki")
        content = extract_docx_content(docx_files[0])
        assert isinstance(content, str)

    def test_csv_file_extraction(self, wiki_path):
        csv_files = list(wiki_path.rglob("*.csv"))
        if not csv_files:
            pytest.skip("No CSV files found in wiki")
        try:
            content = extract_csv_content(csv_files[0])
            assert isinstance(content, str)
        except Exception:
            pytest.skip(f"Could not parse CSV: {csv_files[0]}")


@pytest.mark.slow
class TestListDocumentsLogic:
    def test_finds_all_formats(self, wiki_path):
        found_extensions = set()
        for ext in SUPPORTED_EXTENSIONS:
            if list(wiki_path.rglob(f"*{ext}")):
                found_extensions.add(ext)
        assert ".md" in found_extensions

    def test_list_documents_includes_all_extensions(self, wiki_path):
        found_exts = set()
        for ext in SUPPORTED_EXTENSIONS:
            files = [
                f
                for f in wiki_path.rglob(f"*{ext}")
                if not any(part.startswith(".") for part in f.parts)
            ]
            if files:
                found_exts.add(ext)
        assert len(found_exts) >= 3, (
            f"Should find at least 3 file types, found: {found_exts}"
        )
        assert ".md" in found_exts


class TestGetDocumentCodeFiles:
    @pytest.mark.parametrize("extension", CODE_EXTENSIONS)
    def test_get_document_handles_supported_code_extensions(self, extension):
        assert extension in SUPPORTED_EXTENSIONS


class TestGetDocumentErrorEnvelope:
    def test_unsupported_extension_returns_error_prefix(self, tmp_path):
        (tmp_path / "notes.psd").write_bytes(b"\x00fake")
        _, tools = build_multi_mcp("env-test", {"docs": tmp_path})

        result = tools["get_document"].fn("notes.psd")

        assert result.startswith("Error: "), (
            f"Expected 'Error: ' prefix, got: {result!r}"
        )
        assert "Supported" in result

    def test_multi_collection_response_includes_collection_tag(self, tmp_path):
        wiki = tmp_path / "wiki"
        brain = tmp_path / "brain"
        wiki.mkdir()
        brain.mkdir()
        (wiki / "intro.md").write_text("# Intro\n\nContent", encoding="utf-8")

        _, tools = build_multi_mcp("tag-test", {"wiki": wiki, "brain": brain})

        result = tools["get_document"].fn("intro.md")

        assert "**Collection:** wiki" in result

    def test_single_collection_response_omits_collection_tag(self, tmp_path):
        (tmp_path / "solo.md").write_text("# Solo\n\nContent", encoding="utf-8")

        _, tools = build_multi_mcp("solo-test", {"docs": tmp_path})

        result = tools["get_document"].fn("solo.md")

        assert "**Collection:**" not in result

    def test_get_document_respects_indexer_exclusions(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "secret.md").write_text(
            "# Secret\n\nShould not be readable",
            encoding="utf-8",
        )

        _, tools = build_multi_mcp("excluded-doc-test", {"docs": tmp_path})

        result = tools["get_document"].fn("node_modules/secret.md")

        assert result == "Document not found: node_modules/secret.md"
        assert "Should not be readable" not in result


class TestCollectionRebuild:
    def test_get_smart_can_skip_implicit_index_build(self, tmp_path):
        """Doctor probes need existing indexes without triggering reindex."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from tests.test_runtime_hardening import FakeBackend
        from trace_search.server_app import Collection

        col = Collection(
            name="test",
            kb_path=tmp_path,
            index_path=tmp_path / "idx",
        )
        fake_indexer = SimpleNamespace(collection=MagicMock(), backend=FakeBackend())

        with patch.object(col, "ensure_index", return_value=fake_indexer) as ensure:
            col.get_smart(skip_build=True)

        ensure.assert_called_once_with(None, skip_build=True)
        assert col._smart is None

    def test_get_smart_after_skip_build_uses_normal_cached_path(self, tmp_path):
        """A doctor probe must not poison later normal search initialization."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from tests.test_runtime_hardening import FakeBackend
        from trace_search.server_app import Collection

        col = Collection(
            name="test",
            kb_path=tmp_path,
            index_path=tmp_path / "idx",
        )
        fake_indexer = SimpleNamespace(collection=MagicMock(), backend=FakeBackend())

        with patch.object(col, "ensure_index", return_value=fake_indexer) as ensure:
            col.get_smart(skip_build=True)
            col.get_smart()

        assert ensure.call_args_list[0].kwargs == {"skip_build": True}
        assert ensure.call_args_list[1].args == (None,)
        assert ensure.call_args_list[1].kwargs == {}
        assert col._smart is not None

    def test_rebuild_force_clears_caches_and_returns_chunk_count(self, tmp_path):
        """rebuild(force=True) must clear all four caches and return the new chunk count."""
        from unittest.mock import MagicMock, patch

        from trace_search.server_app import Collection

        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "doc.md").write_text("# Doc\n\ncontent", encoding="utf-8")

        col = Collection(
            name="test",
            kb_path=kb,
            index_path=tmp_path / "idx",
        )
        col._indexer = MagicMock()
        col._semantic = MagicMock()
        col._keyword = MagicMock()
        col._hybrid = MagicMock()

        fake_indexer = MagicMock()
        fake_indexer.build_index.return_value = 3

        with patch.object(col, "ensure_index", return_value=fake_indexer):
            result = col.rebuild(force=True)

        assert col._indexer is None
        assert col._semantic is None
        assert col._keyword is None
        assert col._hybrid is None
        fake_indexer.build_index.assert_called_once_with(force=True)
        assert result == 3

    def test_rebuild_incremental_keeps_caches_and_calls_build_without_force(
        self, tmp_path
    ):
        """rebuild() defaults to incremental and preserves cached search components."""
        from unittest.mock import MagicMock, patch

        from trace_search.server_app import Collection

        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "doc.md").write_text("# Doc\n\ncontent", encoding="utf-8")

        col = Collection(
            name="test",
            kb_path=kb,
            index_path=tmp_path / "idx",
        )
        semantic_marker = MagicMock()
        keyword_marker = MagicMock()
        hybrid_marker = MagicMock()
        col._semantic = semantic_marker
        col._keyword = keyword_marker
        col._hybrid = hybrid_marker

        fake_indexer = MagicMock()
        fake_indexer.build_index.return_value = 5

        with patch.object(col, "ensure_index", return_value=fake_indexer):
            result = col.rebuild()

        assert col._semantic is semantic_marker
        assert col._keyword is keyword_marker
        assert col._hybrid is hybrid_marker
        fake_indexer.build_index.assert_called_once_with(force=False)
        assert result == 5


class TestReindexForceFlag:
    def test_mcp_reindex_threads_force_into_collection(self, tmp_path):
        """The MCP reindex tool must thread `force` down to Collection.rebuild."""
        from unittest.mock import patch

        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "doc.md").write_text("# Doc\n\ncontent", encoding="utf-8")

        _, tools = build_multi_mcp("force-test", {"docs": kb})

        with patch(
            "trace_search.server_app.Collection.rebuild",
            return_value=7,
            autospec=True,
        ) as rebuild_mock:
            result = tools["reindex"].fn(force=True)

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
            "trace_search.server_app.Collection.rebuild",
            return_value=2,
            autospec=True,
        ) as rebuild_mock:
            result = tools["reindex"].fn()

        assert "(forced rebuild)" not in result
        assert "2 chunks indexed" in result
        kwargs = rebuild_mock.call_args.kwargs
        assert kwargs.get("force") is False


class TestListDocumentsMultiCollectionWalk:
    def test_each_collection_walked_exactly_once(self, tmp_path):
        """list_documents should call rglob('*') exactly once per collection."""
        from pathlib import Path
        from unittest.mock import patch

        wiki = tmp_path / "wiki"
        brain = tmp_path / "brain"
        wiki.mkdir()
        brain.mkdir()
        (wiki / "a.md").write_text("# A\n\ncontent", encoding="utf-8")
        (brain / "b.md").write_text("# B\n\ncontent", encoding="utf-8")

        _, tools = build_multi_mcp("walk-test", {"wiki": wiki, "brain": brain})

        rglob_calls: list[str] = []
        original_rglob = Path.rglob

        def spy_rglob(self, pattern):
            rglob_calls.append(pattern)
            return original_rglob(self, pattern)

        with patch.object(Path, "rglob", spy_rglob):
            tools["list_documents"].fn(limit=50)

        assert rglob_calls.count("*") == 2, (
            f"Expected exactly 2 rglob('*') calls (one per collection), got: {rglob_calls}"
        )


class TestListDocumentsDeterminism:
    def test_list_documents_is_stable_and_sorted(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "x.md").write_text("# X Doc\n\nContent", encoding="utf-8")
        (tmp_path / "a" / "a.sql").write_text("SELECT 1;", encoding="utf-8")
        (tmp_path / "b" / "z.pdf").write_bytes(b"%PDF-1.4")

        _, tools = build_multi_mcp("det-test", {"docs": tmp_path})

        first = tools["list_documents"].fn(limit=2)
        second = tools["list_documents"].fn(limit=2)

        assert first == second
        assert "Found 2 documents" in first
        assert "`a/a.sql`" in first
        assert "`a/x.md`" in first
        assert "`b/z.pdf`" not in first

    def test_list_documents_uses_indexer_exclusions(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "docs" / "intro.md").write_text(
            "# Intro\n\nContent", encoding="utf-8"
        )
        (tmp_path / "node_modules" / "package.md").write_text(
            "# Package\n\nShould not list",
            encoding="utf-8",
        )

        _, tools = build_multi_mcp("exclude-test", {"docs": tmp_path})
        result = tools["list_documents"].fn(limit=50)

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
        result = tools["list_documents"].fn(limit=50)

        assert "`intro.md`" in result
        assert "secret-link.md" not in result
