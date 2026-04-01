"""Tool registration hub — imports all tool modules and registers them."""

from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools import example_tool, sendgrid_tool


def register_all_tools(mcp: FastMCP) -> None:
    """Register all tool modules with the MCP server."""
    example_tool.register_tools(mcp)
    sendgrid_tool.register_tools(mcp)
