"""Tests for server initialization."""

from mcp_toolbox.server import mcp


def test_server_name():
    assert mcp.name == "mcp-toolbox"


def test_server_has_tools():
    # After import, tools should be registered (2 example + 14 sendgrid)
    tools = mcp._tool_manager._tools
    assert len(tools) == 16
    expected_tools = {"hello", "add", "send_email", "send_template_email",
                      "send_email_with_attachment", "schedule_email",
                      "list_templates", "get_template", "get_email_stats",
                      "get_bounces", "get_spam_reports", "manage_suppressions",
                      "add_contacts", "search_contacts", "get_contact", "manage_lists"}
    assert set(tools.keys()) == expected_tools
