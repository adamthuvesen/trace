"""Trace console entrypoint."""

from trace_search.cli import run_cli
from trace_search.config import get_settings
from trace_search.server_app import build_multi_mcp


def run_server() -> None:
    """Run the Trace MCP server."""
    mcp, _ = build_multi_mcp("trace", get_settings().parsed_collections)
    mcp.run()


def main() -> None:
    """Run the Trace CLI."""
    raise SystemExit(run_cli(serve=run_server))


if __name__ == "__main__":
    main()
