"""Tests for server initialization."""

from mcp_toolbox.server import mcp


def test_server_name():
    assert mcp.name == "mcp-toolbox"


def test_server_has_tools():
    # After import, tools should be registered (2 example + 14 sendgrid + 25 clickup)
    tools = mcp._tool_manager._tools
    assert len(tools) == 41
    expected_tools = {
        # Example tools
        "hello", "add",
        # SendGrid tools
        "send_email", "send_template_email", "send_email_with_attachment",
        "schedule_email", "list_templates", "get_template", "get_email_stats",
        "get_bounces", "get_spam_reports", "manage_suppressions",
        "add_contacts", "search_contacts", "get_contact", "manage_lists",
        # ClickUp tools
        "clickup_get_workspaces", "clickup_get_spaces", "clickup_get_lists",
        "clickup_create_task", "clickup_get_task", "clickup_update_task",
        "clickup_get_tasks", "clickup_search_tasks", "clickup_delete_task",
        "clickup_add_comment", "clickup_get_comments", "clickup_create_checklist",
        "clickup_add_checklist_item", "clickup_add_tag", "clickup_remove_tag",
        "clickup_log_time", "clickup_get_time_entries", "clickup_start_timer",
        "clickup_stop_timer", "clickup_create_space", "clickup_create_list",
        "clickup_create_folder", "clickup_get_members", "clickup_get_custom_fields",
        "clickup_set_custom_field",
    }
    assert set(tools.keys()) == expected_tools
