"""MCP tool output text is a public contract that agents parse."""

from __future__ import annotations

import os
from pathlib import Path

from tests.test_runtime_hardening import FakeBackend
from trace_search.server.mcp_tools import build_multi_mcp

FIXTURE_KB = Path(__file__).parent / "fixtures" / "eval_kb"
GOLDEN = Path(__file__).parent / "fixtures" / "mcp_output_golden.md"


def _render(tmp_path: Path, monkeypatch) -> str:
    monkeypatch.setattr(
        "trace_search.collections.collection_registry.build_embedding_backend",
        lambda config: FakeBackend(),
    )
    _, tools = build_multi_mcp("trace-golden", {"docs": FIXTURE_KB}, tmp_path)
    calls = [
        ('search("BM25 ranking", top_k=3)', tools["search"]("BM25 ranking", top_k=3)),
        (
            'keyword_search("embedding model", max_results=3)',
            tools["keyword_search"]("embedding model", max_results=3),
        ),
        (
            'get_document("search/hybrid-search.md")',
            tools["get_document"]("search/hybrid-search.md"),
        ),
    ]
    return "".join(f"<!-- {call} -->\n{output}\n\n" for call, output in calls)


def test_mcp_output_matches_golden(tmp_path, monkeypatch):
    actual = _render(tmp_path, monkeypatch)
    if os.environ.get("TRACE_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(actual)
    assert actual == GOLDEN.read_text(), (
        "MCP output text changed, and agents parse it. If the change is intended, run "
        "`TRACE_UPDATE_GOLDEN=1 just test-file tests/test_mcp_output_golden.py` "
        "and review the diff of tests/fixtures/mcp_output_golden.md."
    )
