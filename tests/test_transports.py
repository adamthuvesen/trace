"""Protocol checks against real Trace subprocesses, with external sockets denied."""

from __future__ import annotations

import asyncio
import http.client
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from tests.polling import wait_until

TOOL_NAMES = {
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
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def server_environment(tmp_path):
    kb = tmp_path / "documents"
    kb.mkdir()
    (kb / "hello.md").write_text("# Hello\n\nProtocol fixture content")
    guard = tmp_path / "network-guard"
    guard.mkdir()
    attempts = tmp_path / "external-attempts.log"
    attempts.touch()
    (guard / "sitecustomize.py").write_text("""
import ipaddress
import os
import sys


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
    with open(os.environ["TRACE_TEST_EXTERNAL_ATTEMPTS"], "a") as log:
        log.write(f"{event}: {host}\\n")
    raise RuntimeError(f"External network attempt denied: {host}")


sys.addaudithook(audit)
""")
    environment = os.environ.copy()
    environment.pop("KB_COLLECTIONS", None)
    environment.pop("FASTMCP_CHECK_FOR_UPDATES", None)
    environment.update(
        KB_PATH=str(kb),
        INDEX_PATH=str(tmp_path / "indexes"),
        PYTHONPATH=os.pathsep.join([str(guard), str(REPO_ROOT / "src")]),
        TRACE_TEST_EXTERNAL_ATTEMPTS=str(attempts),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        NO_PROXY="127.0.0.1,localhost,::1",
    )
    yield environment
    assert attempts.read_text() == "", "Trace attempted external network access"


async def assert_document_protocol(client):
    tools = await client.list_tools()
    assert {tool.name for tool in tools} == TOOL_NAMES
    document = await client.call_tool_mcp("get_document", {"path": "hello.md"})
    assert not document.is_error
    assert "Protocol fixture content" in str(document.content)
    missing = await client.call_tool_mcp("get_document", {"path": "missing.md"})
    assert missing.is_error
    assert "Document not found" in str(missing.content)
    unknown = await client.call_tool_mcp(
        "get_document", {"path": "hello.md", "collection": "unknown"}
    )
    assert unknown.is_error
    invalid_limit = await client.call_tool_mcp("list_documents", {"limit": 0})
    assert invalid_limit.is_error
    boolean_limit = await client.call_tool_mcp("list_documents", {"limit": True})
    assert boolean_limit.is_error


@pytest.mark.transport
@pytest.mark.parametrize(
    ("mode", "expected_version"),
    [("auto", "2026-07-28"), ("legacy", "2025-11-25"), ("2026-07-28", "2026-07-28")],
)
def test_stdio_protocol_in_real_subprocess(server_environment, tmp_path, mode, expected_version):
    async def check():
        with (tmp_path / "stdio-stderr.log").open("w") as log:
            transport = StdioTransport(
                command=sys.executable,
                args=["-m", "trace_search.server.trace_server", "serve"],
                env=server_environment,
                cwd=str(REPO_ROOT),
                log_file=log,
            )
            async with Client(transport, timeout=10, init_timeout=20, mode=mode) as client:
                assert client.protocol_version == expected_version
                await assert_document_protocol(client)

    asyncio.run(check())


@pytest.mark.slow
def test_cached_model_indexes_and_searches_without_external_network(server_environment, tmp_path):
    async def check():
        with (tmp_path / "offline-stderr.log").open("w") as log:
            transport = StdioTransport(
                command=sys.executable,
                args=["-m", "trace_search.server.trace_server", "serve"],
                env=server_environment,
                cwd=str(REPO_ROOT),
                log_file=log,
            )
            async with Client(transport, timeout=60, init_timeout=20) as client:
                built = await client.call_tool_mcp("reindex", {"force": True})
                assert not built.is_error, built.content
                result = await client.call_tool_mcp(
                    "semantic_search", {"query": "protocol fixture", "top_k": 1}
                )
                assert not result.is_error, result.content
                assert "hello.md" in str(result.content)
                assert "Protocol fixture content" in str(result.content)

    asyncio.run(check())


def available_port():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return reservation.getsockname()[1]


@contextmanager
def http_server(environment, port, log_path):
    with log_path.open("a") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "trace_search.server.trace_server",
                "serve",
                "--transport",
                "http",
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            env=environment,
            stdout=log,
            stderr=log,
        )
        try:

            def accepts_connections() -> bool:
                if process.poll() is not None:
                    pytest.fail(f"HTTP server exited: {log_path.read_text()}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        return True
                except OSError:
                    return False

            try:
                wait_until(
                    accepts_connections, timeout=20, what="the HTTP server to accept connections"
                )
            except AssertionError:
                pytest.fail(f"HTTP server did not become ready: {log_path.read_text()}")
            yield process
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.transport
@pytest.mark.parametrize(
    ("mode", "expected_version"),
    [("auto", "2026-07-28"), ("legacy", "2025-11-25"), ("2026-07-28", "2026-07-28")],
)
def test_http_protocol_and_stateless_restart(server_environment, tmp_path, mode, expected_version):
    port = available_port()
    log_path = tmp_path / "http-stderr.log"

    async def check():
        with http_server(server_environment, port, log_path) as first:
            async with Client(
                f"http://127.0.0.1:{port}/mcp", timeout=10, init_timeout=20, mode=mode
            ) as client:
                assert client.protocol_version == expected_version
                await assert_document_protocol(client)
                assert client.transport.get_session_id() is None
                first.terminate()
                first.wait(timeout=10)
                with http_server(server_environment, port, log_path):
                    document = await client.call_tool_mcp("get_document", {"path": "hello.md"})
                    assert not document.is_error
                    assert "Protocol fixture content" in str(document.content)
                    assert client.transport.get_session_id() is None

    asyncio.run(check())


@pytest.mark.transport
@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Host": "attacker.example"}, 421),
        ({"Origin": "https://attacker.example"}, 403),
    ],
)
def test_http_rejects_nonlocal_host_and_origin(server_environment, tmp_path, headers, status):
    port = available_port()
    with http_server(server_environment, port, tmp_path / "http-security.log"):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("POST", "/mcp", body="{}", headers=headers)
            response = connection.getresponse()
            assert response.status == status
        finally:
            connection.close()


def test_fastmcp_inspector_loads_noarg_factory(tmp_path, monkeypatch):
    import fastmcp
    from fastmcp.utilities.inspect import inspect_fastmcp
    from fastmcp.utilities.mcp_server_config.v1.sources.filesystem import (
        FileSystemSource,
    )

    from trace_search.config import get_settings

    kb = tmp_path / "documents"
    kb.mkdir()
    monkeypatch.setenv("KB_PATH", str(kb))
    monkeypatch.delenv("KB_COLLECTIONS", raising=False)
    get_settings.cache_clear()
    previous_update_setting = fastmcp.settings.check_for_updates

    async def check():
        source = FileSystemSource(
            path=str(REPO_ROOT / "src/trace_search/server/trace_server.py") + ":create_mcp"
        )
        server = await source.load_server()
        information = await inspect_fastmcp(server)
        assert information.name == "trace"
        assert {tool.name for tool in information.tools} == TOOL_NAMES
        assert fastmcp.settings.check_for_updates == "off"

    try:
        asyncio.run(check())
    finally:
        fastmcp.settings.check_for_updates = previous_update_setting
        get_settings.cache_clear()
