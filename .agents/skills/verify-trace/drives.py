"""Trace verify drives. Each drive builds fresh fixture collections and asserts what a user sees."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODEL_DIR = "models--qdrant--all-MiniLM-L6-v2-onnx"
TOOLS = {
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
NOTES = {
    "deploy.md": "# Deploy previews\n\nDeploy previews use the zinnia staging bucket in eu-north-1.\n",
    "style.md": "# Code style\n\nThe quokka repo uses tabs, never spaces.\n",
    "guides/onboarding.md": "# Onboarding\n\nNew hires pair with a buddy for their first heron sprint.\n",
}
# The audit hook from tests/test_transports.py: log and refuse any non-loopback connection.
GUARD = """
import ipaddress, os, sys

def audit(event, args):
    if event == "socket.connect":
        address = args[1]
        if not isinstance(address, tuple):
            return
        host = address[0]
    elif event == "socket.getaddrinfo":
        host = args[0]
    else:
        return
    if host is None or host in ("localhost", b"localhost"):
        return
    if isinstance(host, bytes):
        host = host.decode()
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    with open(os.environ["TRACE_VERIFY_NETWORK_LOG"], "a") as log:
        log.write(f"{event}: {host}\\n")
    raise RuntimeError(f"External network attempt denied: {host}")

sys.addaudithook(audit)
"""


class Failure(Exception):
    """A drive observed something other than the expected user-visible result."""


@dataclass
class Context:
    name: str
    scratch: Path
    evidence: Path
    env: dict[str, str]
    root: Path
    processes: list[subprocess.Popen[str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.docs = self.scratch / "kb" / "docs"
        self.notes = self.scratch / "kb" / "notes"
        shutil.copytree(self.root / "tests" / "fixtures" / "eval_kb", self.docs)
        for path, text in NOTES.items():
            (self.notes / path).parent.mkdir(parents=True, exist_ok=True)
            (self.notes / path).write_text(text)
        self.evidence.mkdir(parents=True)
        self.env = {
            **self.env,
            "KB_COLLECTIONS": f"docs:{self.docs},notes:{self.notes}",
            "INDEX_PATH": str(self.scratch / "indexes"),
        }
        self.step = 0

    def log(self, label: str, text: str) -> None:
        self.step += 1
        (self.evidence / f"{self.step:02d}-{label}.txt").write_text(text)

    def start(self, args: list[str], log: Path) -> subprocess.Popen[str]:
        with log.open("w") as handle:
            process = subprocess.Popen(
                args,
                cwd=self.scratch,
                env=self.env,
                text=True,
                stdout=handle,
                stderr=handle,
                start_new_session=True,
            )
        self.processes.append(process)
        return process

    def run(
        self, args: list[str], *, cwd: Path | None = None, timeout: float = 60
    ) -> subprocess.CompletedProcess[str]:
        process = subprocess.Popen(
            args,
            cwd=cwd or self.scratch,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self.processes.append(process)
        try:
            out, err = process.communicate(timeout=timeout)
        finally:
            self.stop_processes()
        label = args[1] if len(args) > 1 and not args[1].startswith("-") else Path(args[0]).name
        self.log(
            label,
            f"$ {' '.join(args)}\nexit {process.returncode}\n--- stdout\n{out}\n--- stderr\n{err}",
        )
        return subprocess.CompletedProcess(args, process.returncode, out, err)

    def trace(self, *args: str, code: int = 0) -> str:
        result = self.run([str(Path(sys.executable).with_name("trace")), *args])
        expect(
            result.returncode == code,
            f"trace {' '.join(args)}: expected exit {code}, got {result.returncode}: {(result.stderr or result.stdout)[-300:]}",
        )
        return result.stdout + result.stderr

    def stop_processes(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        self.processes.clear()


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


def top_path(output: str) -> tuple[str, str] | None:
    """Path and collection of result 1 in rendered search output."""
    block = output.split("### 1.", 1)
    if len(block) < 2:
        return None
    path = re.search(r"\*\*Path:\*\* `([^`]+)`", block[1])
    collection = re.search(r"\*\*Collection:\*\* (\S+)", block[1])
    return (path.group(1) if path else "", collection.group(1) if collection else "")


def expect_top(output: str, what: str, path: str, collection: str = "docs") -> None:
    got = top_path(output)
    expect(
        got == (path, collection),
        f"{what}: expected top hit {collection}/{path}, got {got}",
    )


async def drive_search(ctx: Context, keyword_expected: str = "config/reranker.md") -> str:
    built = ctx.trace("reindex")
    expect(
        "**docs**: " in built and "**notes**: " in built,
        f"reindex: expected both collections, got {built[:200]}",
    )
    expect_top(
        ctx.trace("keyword-search", "RERANKER_ENABLED"),
        "keyword-search RERANKER_ENABLED",
        keyword_expected,
    )
    expect_top(ctx.trace("search", "INDEX_PATH"), "search INDEX_PATH", "config/index-path.md")
    expect_top(
        ctx.trace(
            "semantic-search",
            "metric that only cares how high the first correct answer lands",
        ),
        "semantic-search MRR paraphrase",
        "glossary/mrr.md",
    )
    expect_top(
        ctx.trace("hybrid-search", "combine keyword and semantic signals into one ranking"),
        "hybrid-search",
        "search/hybrid-search.md",
    )
    expect_top(
        ctx.trace(
            "semantic-search",
            "where are preview builds stored",
            "--collection",
            "notes",
        ),
        "semantic-search --collection notes",
        "deploy.md",
        "notes",
    )
    document = ctx.trace("get-document", "deploy.md", "--collection", "notes")
    expect(
        NOTES["deploy.md"].strip().splitlines()[-1] in document,
        "get-document: body text missing",
    )
    missing = ctx.trace("get-document", "missing.md", code=1)
    expect(
        "Document not found: missing.md" in missing,
        f"get-document missing: got {missing[-200:]}",
    )
    listed = ctx.trace("list-documents", "--limit", "50")
    expect(
        "Found 27 documents" in listed,
        f"list-documents: expected 27 documents, got {listed.splitlines()[:1]}",
    )
    return "reindex 2 collections; keyword, adaptive, semantic, hybrid, scoped search; get-document; list 27 docs"


async def control(ctx: Context) -> str:
    """Re-drive search expecting a document keyword search does not rank first; passes only on FAIL."""
    return await drive_search(ctx, keyword_expected="glossary/bm25.md")


async def drive_index(ctx: Context) -> str:
    ctx.trace("reindex")
    pelican = "# Pelican rollout\n\nThe pelican rollout gates every release. Pelican owners approve the pelican checklist.\n"
    (ctx.docs / "features" / "pelican-rollout.md").write_text(pelican)
    (ctx.docs / "glossary" / "ndcg.md").unlink()
    edited = ctx.docs / "config" / "reranker.md"
    edited.write_text(
        edited.read_text()
        + "\nThe ostrich switch turns RERANKER_ENABLED off for ostrich batches.\n"
    )
    before = ctx.trace("doctor", code=1)
    expect(
        "Index status:** stale" in before
        and "unchanged=22, added=1, changed=1, removed=1" in before,
        f"doctor before reindex: expected added=1, changed=1, removed=1 for docs, got {re.findall(r'unchanged=.*', before)}",
    )
    ctx.trace("reindex")
    after = ctx.trace("doctor", "pelican")
    expect(
        "unchanged=24, added=0, changed=0, removed=0" in after and "stale" not in after,
        f"doctor after reindex: expected docs fresh with 24 unchanged, got {re.findall(r'unchanged=.*', after)}",
    )
    expect_top(
        ctx.trace("keyword-search", "pelican"),
        "keyword-search new doc",
        "features/pelican-rollout.md",
    )
    edited_hit = ctx.trace("keyword-search", "ostrich", "--path-prefix", "config/")
    expect_top(
        edited_hit,
        "keyword-search --path-prefix config/ edited doc",
        "config/reranker.md",
    )
    ctx.trace("get-document", "glossary/ndcg.md", "--collection", "docs", code=1)
    stats = ctx.trace("index-stats", "--collection", "docs")
    expect(
        "**Documents:** 24" in stats,
        f"index-stats: expected 24 docs, got {re.findall(r'Documents:.*', stats)}",
    )
    return "doctor sees add/change/remove; incremental reindex picks up all three; doctor healthy after"


async def drive_mcp(ctx: Context) -> str:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    trace = str(Path(sys.executable).with_name("trace"))

    async def exercise(client: Client[Any], transport: str) -> None:
        names = {tool.name for tool in await client.list_tools()}
        expect(
            names == TOOLS,
            f"{transport} tools/list: expected {sorted(TOOLS)}, got {sorted(names)}",
        )
        found = await client.call_tool_mcp("search", {"query": "INDEX_PATH"})
        ctx.log(f"{transport}-search", str(found.content))
        expect(
            not found.is_error
            and top_path(str(found.content[0].text)) == ("config/index-path.md", "docs"),
            f"{transport} search: expected docs/config/index-path.md first, got {str(found.content)[:300]}",
        )
        document = await client.call_tool_mcp(
            "get_document", {"path": "style.md", "collection": "notes"}
        )
        expect(
            not document.is_error and "quokka repo uses tabs" in str(document.content),
            f"{transport} get_document: got {str(document.content)[:200]}",
        )
        missing = await client.call_tool_mcp("get_document", {"path": "missing.md"})
        expect(
            missing.is_error and "Document not found" in str(missing.content),
            f"{transport} missing document: expected an error",
        )

    with (ctx.evidence / "stdio-server.log").open("w") as log:
        transport = StdioTransport(
            command=trace,
            args=["serve"],
            env=ctx.env,
            cwd=str(ctx.scratch),
            log_file=log,
        )
        async with Client(transport, timeout=30, init_timeout=30) as client:
            built = await client.call_tool_mcp("reindex", {"force": True})
            expect(not built.is_error, f"stdio reindex: {str(built.content)[:300]}")
            await exercise(client, "stdio")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = ctx.start(
        [trace, "serve", "--transport", "http", "--port", str(port)],
        ctx.evidence / "http-server.log",
    )
    for _ in range(300):
        expect(
            server.poll() is None,
            f"http server exited {server.returncode}; see http-server.log",
        )
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            break
        except OSError:
            await asyncio.sleep(0.1)
    else:
        raise Failure("http server did not listen within 30s")
    async with Client(f"http://127.0.0.1:{port}/mcp", timeout=30) as client:
        await exercise(client, "http")
    return "trace serve over stdio and HTTP: 9 tools, reindex, search, get_document, missing-document error"


async def drive_package(ctx: Context) -> str:
    result = ctx.run([sys.executable, "-m", "tools.verify_package"], cwd=ctx.root, timeout=600)
    expect(
        result.returncode == 0 and "Package verification passed" in result.stdout,
        f"package: expected the wheel check to pass, got exit {result.returncode}: {(result.stderr or result.stdout)[-400:]}",
    )
    return "wheel builds and installs outside the checkout with its typed public API"


@dataclass(frozen=True)
class Drive:
    proves: str
    paths: list[str]
    run: Callable[[Context], Awaitable[str]]
    timeout: float = 60.0


SRC = "src/trace_search"
DRIVES = {
    "search": Drive(
        "The trace CLI indexes two collections and every search mode, get-document, and list-documents return the right files",
        [
            f"{SRC}/retrieval/*",
            f"{SRC}/collections/*",
            f"{SRC}/extraction/*",
            f"{SRC}/indexing/*",
            f"{SRC}/config.py",
            f"{SRC}/server/cli.py",
            "tests/fixtures/eval_kb/*",
        ],
        drive_search,
    ),
    "index": Drive(
        "Doctor reports added, changed, and removed files, and an incremental reindex applies all three",
        [
            f"{SRC}/indexing/*",
            f"{SRC}/extraction/*",
            f"{SRC}/collections/*",
            f"{SRC}/filesystem_paths.py",
        ],
        drive_index,
    ),
    "mcp": Drive(
        "trace serve answers MCP over stdio and HTTP with the stable tool set and real results",
        [
            f"{SRC}/server/*",
            f"{SRC}/collections/operations.py",
            f"{SRC}/retrieval/formatting.py",
        ],
        drive_mcp,
    ),
    "package": Drive(
        "The built wheel installs outside the checkout and exposes the public API",
        ["tools/verify_package.py", f"{SRC}/__init__.py", f"{SRC}/py.typed"],
        drive_package,
        180.0,
    ),
}
SMOKE = "search"
