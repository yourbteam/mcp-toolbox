"""Tool registration hub — imports all tool modules and registers them."""

from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools import (
    aws_ssm_tool,
    calendar_tool,
    clickup_tool,
    example_tool,
    http_tool,
    hubspot_tool,
    jira_tool,
    keyvault_tool,
    o365_tool,
    sendgrid_tool,
    slack_tool,
    stripe_tool,
    teams_tool,
)


def register_all_tools(mcp: FastMCP) -> None:
    """Register all tool modules with the MCP server."""
    example_tool.register_tools(mcp)
    sendgrid_tool.register_tools(mcp)
    clickup_tool.register_tools(mcp)
    o365_tool.register_tools(mcp)
    teams_tool.register_tools(mcp)
    keyvault_tool.register_tools(mcp)
    aws_ssm_tool.register_tools(mcp)
    slack_tool.register_tools(mcp)
    http_tool.register_tools(mcp)
    calendar_tool.register_tools(mcp)
    hubspot_tool.register_tools(mcp)
    jira_tool.register_tools(mcp)
    stripe_tool.register_tools(mcp)
