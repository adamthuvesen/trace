"""Multi-collection trace MCP server entrypoint."""

from trace_search.config import get_settings
from trace_search.server_app import build_multi_mcp


def main() -> None:
    """Run the multi-collection MCP server."""
    mcp, _ = build_multi_mcp("trace", get_settings().parsed_collections)
    mcp.run()


if __name__ == "__main__":
    main()
