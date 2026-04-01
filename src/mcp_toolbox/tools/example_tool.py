"""Example tool — validates the scaffolding works end-to-end."""

import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_tools(mcp: FastMCP) -> None:
    """Register example tools with the MCP server."""

    @mcp.tool()
    async def hello(name: str = "World") -> str:
        """Say hello. Use this to verify the MCP server is working."""
        logger.info("hello tool called with name=%s", name)
        return f"Hello, {name}! MCP Toolbox is running."

    @mcp.tool()
    async def add(a: float, b: float) -> float:
        """Add two numbers together."""
        return a + b
