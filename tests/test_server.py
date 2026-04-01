"""Tests for server initialization."""

from mcp_toolbox.server import mcp


def test_server_name():
    assert mcp.name == "mcp-toolbox"


def test_server_has_tools():
    # After import, tools should be registered (2 example + 14 sendgrid)
    tools = mcp._tool_manager._tools
    assert len(tools) >= 16
