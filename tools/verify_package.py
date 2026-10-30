"""Verify a wheel and its typed public API outside the source checkout."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory


class VerificationError(RuntimeError):
    """A package check failed with an actionable diagnostic."""


def run_command(
    label: str,
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
    *,
    expected_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
    )
    if (result.returncode == 0) == expected_failure:
        details = (result.stderr.strip() or result.stdout.strip()).splitlines()
        detail = details[-1] if details else "No diagnostic output"
        raise VerificationError(f"{label}: exit {result.returncode}. {detail}")
    print(f"PASS {label}", flush=True)
    return result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def verify_package() -> None:
    repository = Path(__file__).resolve().parents[1]
    project = tomllib.loads((repository / "pyproject.toml").read_text())["project"]
    distribution_name = str(project["name"])
    expected_version = str(project["version"])
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "MYPYPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        environment.pop(name, None)

    with TemporaryDirectory(prefix="trace-wheel-verification-") as name:
        temporary = Path(name)
        wheel_directory = temporary / "wheels"
        run_command(
            "wheel build",
            ["uv", "build", "--wheel", "--out-dir", str(wheel_directory)],
            repository,
            environment,
        )
        wheels = list(wheel_directory.glob("*.whl"))
        require(len(wheels) == 1, "Expected exactly one built wheel")
        requirements = temporary / "runtime-requirements.txt"
        run_command(
            "locked runtime dependency export",
            [
                "uv",
                "export",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--no-hashes",
                "--output-file",
                str(requirements),
            ],
            repository,
            environment,
        )
        isolated_environment = temporary / "venv"
        run_command(
            "fresh virtual environment",
            ["uv", "venv", "--python", sys.executable, str(isolated_environment)],
            temporary,
            environment,
        )
        python = isolated_environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        executable = isolated_environment / (
            "Scripts/trace.exe" if os.name == "nt" else "bin/trace"
        )
        run_command(
            "locked runtime dependencies",
            ["uv", "pip", "sync", "--python", str(python), str(requirements)],
            temporary,
            environment,
        )
        run_command(
            "wheel install without editable source or dev dependencies",
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                str(wheels[0]),
            ],
            temporary,
            environment,
        )
        check_import = """
import importlib.metadata
import importlib.resources
import pathlib
import sys
import trace_search

package = pathlib.Path(trace_search.__file__).resolve()
assert package.is_relative_to(pathlib.Path(sys.prefix).resolve()), package
assert sys.prefix != sys.base_prefix
assert trace_search.__version__ == importlib.metadata.version(sys.argv[1]) == sys.argv[2]
assert importlib.resources.files("trace_search").joinpath("py.typed").is_file()
for name in (
    "WikiIndexer", "CollectionRegistry", "AdaptiveSearch", "SemanticSearch", "KeywordSearch",
    "HybridSearch", "format_results", "format_search_context", "DocumentRef", "ChunkRef",
    "SearchHit", "SearchResponse", "SearchFilters",
):
    assert hasattr(trace_search, name), name
assert "fastmcp" not in sys.modules, "Public import loaded the server framework"
assert "fastembed" not in sys.modules, "Public import loaded the embedding runtime"
"""
        run_command(
            "installed public imports, version, py.typed, and lazy runtime imports",
            [str(python), "-c", check_import, distribution_name, expected_version],
            temporary,
            environment,
        )
        run_command("installed CLI help", [str(executable), "--help"], temporary, environment)
        knowledge_base = temporary / "documents"
        knowledge_base.mkdir()
        (knowledge_base / "hello.md").write_text("# Hello\n\nInstalled wheel fixture")
        runtime_environment = environment.copy()
        runtime_environment.pop("KB_COLLECTIONS", None)
        runtime_environment["KB_PATH"] = str(knowledge_base)
        runtime_environment["INDEX_PATH"] = str(temporary / "indexes")
        document = run_command(
            "installed CLI document fetch",
            [str(executable), "get-document", "hello.md"],
            temporary,
            runtime_environment,
        )
        require(
            "Installed wheel fixture" in document.stdout,
            "CLI did not return the installed fixture",
        )
        missing = run_command(
            "installed CLI missing-document nonzero exit",
            [str(executable), "get-document", "missing.md"],
            temporary,
            runtime_environment,
            expected_failure=True,
        )
        require(
            "Document not found" in missing.stderr
            and not missing.stdout
            and "Traceback" not in missing.stderr,
            "Missing-document CLI result did not preserve its error contract",
        )
        protocol = """
import asyncio
import os
import sys
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

async def check():
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "trace_search.server.trace_server", "serve"],
        env=os.environ.copy(),
        cwd=os.getcwd(),
    )
    async with Client(transport, timeout=10, init_timeout=20) as client:
        tools = await client.list_tools()
        assert len(tools) == 9
        document = await client.call_tool_mcp("get_document", {"path": "hello.md"})
        assert not document.is_error
        assert "Installed wheel fixture" in str(document.content)
        missing = await client.call_tool_mcp("get_document", {"path": "missing.md"})
        assert missing.is_error

asyncio.run(check())
"""
        run_command(
            "installed stdio protocol discovery and document/error responses",
            [str(python), "-c", protocol],
            temporary,
            runtime_environment,
        )
        good_consumer = temporary / "consumer_good.py"
        good_consumer.write_text("""
from trace_search import ChunkRef, DocumentRef, SearchFilters, SearchResponse

document = DocumentRef(collection="documents", path="hello.md")
chunk = ChunkRef(document=document, generation=None, chunk_index=0)
filters = SearchFilters(path_prefix=("guides/",), extensions=(".md",))
response = SearchResponse(hits=())
path: str = chunk.document.path
""")
        (temporary / "pyrightconfig.json").write_text('{"typeCheckingMode": "strict"}')
        basedpyright = [
            sys.executable,
            "-m",
            "basedpyright",
            "--pythonpath",
            str(python),
        ]
        run_command(
            "installed typed public API consumer",
            [*basedpyright, str(good_consumer)],
            temporary,
            environment,
        )
        bad_consumer = temporary / "consumer_bad.py"
        bad_consumer.write_text("""
from trace_search import DocumentRef

document = DocumentRef(collection=123, path="hello.md")
""")
        rejected = run_command(
            "installed public API rejects incorrect argument types",
            [*basedpyright, str(bad_consumer)],
            temporary,
            environment,
            expected_failure=True,
        )
        require(
            "reportArgumentType" in rejected.stdout and '"collection"' in rejected.stdout,
            "The incorrect type check failed for an unrelated reason",
        )
    print("Package verification passed. Temporary build and environments removed.")


def main() -> int:
    try:
        verify_package()
    except (VerificationError, OSError, subprocess.TimeoutExpired) as error:
        print(f"Package verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
