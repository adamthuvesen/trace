"""Tests for the Trace command-line adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from trace_search.cli import run_cli


_FILTER_KEYS = ("path_prefix", "extensions", "since")


def _filter_tuple(kwargs: dict[str, Any]) -> tuple[Any, Any, Any]:
    return tuple(kwargs.get(key) for key in _FILTER_KEYS)


@dataclass
class FakeOperations:
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    def search(
        self,
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        **filter_kwargs: Any,
    ) -> str:
        self.calls.append(
            ("search", (query, top_k, collection, *_filter_tuple(filter_kwargs)))
        )
        return "# Search"

    def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        **filter_kwargs: Any,
    ) -> str:
        self.calls.append(
            (
                "semantic_search",
                (query, top_k, collection, *_filter_tuple(filter_kwargs)),
            )
        )
        return "# Semantic"

    def keyword_search(
        self,
        keyword: str,
        max_results: int = 20,
        collection: str | None = None,
        **filter_kwargs: Any,
    ) -> str:
        self.calls.append(
            (
                "keyword_search",
                (keyword, max_results, collection, *_filter_tuple(filter_kwargs)),
            )
        )
        return "# Keyword"

    def search_hybrid(
        self,
        query: str,
        top_k: int = 10,
        collection: str | None = None,
        **filter_kwargs: Any,
    ) -> str:
        self.calls.append(
            (
                "search_hybrid",
                (query, top_k, collection, *_filter_tuple(filter_kwargs)),
            )
        )
        return "# Hybrid"

    def get_document(self, path: str, collection: str | None = None) -> str:
        self.calls.append(("get_document", (path, collection)))
        return "# Document\n\nBody"

    def list_documents(
        self,
        folder: str | None = None,
        limit: int = 50,
        collection: str | None = None,
        **filter_kwargs: Any,
    ) -> str:
        self.calls.append(
            (
                "list_documents",
                (folder, limit, collection, *_filter_tuple(filter_kwargs)),
            )
        )
        return "Found 1 documents"

    def index_stats(self, collection: str | None = None) -> str:
        self.calls.append(("index_stats", (collection,)))
        return "# Index Statistics"

    def reindex(self, collection: str | None = None, force: bool = False) -> str:
        self.calls.append(("reindex", (collection, force)))
        return "Reindex complete."

    def doctor(
        self,
        sample_query: str | None = None,
        collection: str | None = None,
    ) -> str:
        self.calls.append(("doctor", (sample_query, collection)))
        return "# Trace Doctor"


@pytest.fixture()
def fake_operations() -> FakeOperations:
    return FakeOperations()


def run_with_fake(
    argv: list[str],
    fake_operations: FakeOperations,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    code = run_cli(
        argv,
        operations_factory=lambda: fake_operations,
        serve=lambda: None,
    )
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_bare_trace_starts_server(capsys):
    served = False

    def serve() -> None:
        nonlocal served
        served = True

    code = run_cli([], operations_factory=FakeOperations, serve=serve)

    assert code == 0
    assert served
    assert capsys.readouterr().out == ""


def test_serve_subcommand_starts_server(capsys):
    served = False

    def serve() -> None:
        nonlocal served
        served = True

    code = run_cli(["serve"], operations_factory=FakeOperations, serve=serve)

    assert code == 0
    assert served
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("argv", "expected_call", "expected_output"),
    [
        (
            ["search", "frontmatter", "--top-k", "3", "--collection", "docs"],
            ("search", ("frontmatter", 3, "docs", None, None, None)),
            "# Search",
        ),
        (
            ["semantic-search", "meaning", "--top-k", "4"],
            ("semantic_search", ("meaning", 4, None, None, None, None)),
            "# Semantic",
        ),
        (
            ["keyword-search", "exact", "--max-results", "7", "--collection", "wiki"],
            ("keyword_search", ("exact", 7, "wiki", None, None, None)),
            "# Keyword",
        ),
        (
            ["hybrid-search", "mixed", "--top-k", "5"],
            ("search_hybrid", ("mixed", 5, None, None, None, None)),
            "# Hybrid",
        ),
        (
            ["get-document", "guide.md", "--collection", "docs"],
            ("get_document", ("guide.md", "docs")),
            "# Document",
        ),
        (
            [
                "list-documents",
                "--folder",
                "guides",
                "--limit",
                "9",
                "--collection",
                "docs",
            ],
            ("list_documents", ("guides", 9, "docs", None, None, None)),
            "Found 1 documents",
        ),
        (
            [
                "search",
                "router",
                "--path-prefix",
                "architecture/",
                "--path-prefix",
                "rfcs/",
                "--extensions",
                ".md",
                "--since",
                "2026-01-01T00:00:00Z",
            ],
            (
                "search",
                (
                    "router",
                    10,
                    None,
                    ["architecture/", "rfcs/"],
                    [".md"],
                    "2026-01-01T00:00:00Z",
                ),
            ),
            "# Search",
        ),
        (
            [
                "list-documents",
                "--extensions",
                ".md,.py",
                "--since",
                "2026-01-01T00:00:00",
            ],
            (
                "list_documents",
                (None, 50, None, None, [".md,.py"], "2026-01-01T00:00:00"),
            ),
            "Found 1 documents",
        ),
        (
            ["index-stats", "--collection", "docs"],
            ("index_stats", ("docs",)),
            "# Index Statistics",
        ),
        (
            ["reindex", "--collection", "docs"],
            ("reindex", ("docs", False)),
            "Reindex complete.",
        ),
        (
            ["reindex", "--collection", "docs", "--force"],
            ("reindex", ("docs", True)),
            "Reindex complete.",
        ),
        (
            ["doctor", "sample", "query", "--collection", "docs"],
            ("doctor", ("sample query", "docs")),
            "# Trace Doctor",
        ),
    ],
)
def test_cli_commands_dispatch_to_matching_operation(
    argv,
    expected_call,
    expected_output,
    fake_operations,
    capsys,
):
    code, out, err = run_with_fake(argv, fake_operations, capsys)

    assert code == 0
    assert fake_operations.calls == [expected_call]
    assert expected_output in out
    assert err == ""


def test_operation_errors_return_nonzero(capsys):
    def failing_factory() -> FakeOperations:
        raise ValueError("Set KB_COLLECTIONS or KB_PATH")

    code = run_cli(
        ["search", "anything"],
        operations_factory=failing_factory,
        serve=lambda: None,
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "Set KB_COLLECTIONS or KB_PATH" in captured.err


def test_doctor_config_errors_keep_doctor_report(capsys):
    def failing_factory() -> FakeOperations:
        raise ValueError("Set KB_COLLECTIONS or KB_PATH")

    code = run_cli(["doctor"], operations_factory=failing_factory, serve=lambda: None)

    captured = capsys.readouterr()
    assert code == 1
    assert "# Trace Doctor" in captured.out
    assert "Set KB_COLLECTIONS or KB_PATH" in captured.out
    assert captured.err == ""


def test_invalid_numeric_argument_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        run_cli(["search", "anything", "--top-k", "0"], serve=lambda: None)

    assert exc_info.value.code != 0
