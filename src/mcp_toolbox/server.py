"""MCP Toolbox server — main entry point."""

from mcp.server.fastmcp import FastMCP

from mcp_toolbox.config import LOG_LEVEL
from mcp_toolbox.tools import register_all_tools

mcp = FastMCP("mcp-toolbox", log_level=LOG_LEVEL)

register_all_tools(mcp)


def main() -> None:
    """Run the MCP server (STDIO transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
