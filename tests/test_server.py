"""Tests for server initialization."""

from mcp_toolbox.server import mcp


def test_server_name():
    assert mcp.name == "mcp-toolbox"


def test_server_has_tools():
    # After import, tools should be registered (2 example + 14 sendgrid + 81 clickup = 97)
    tools = mcp._tool_manager._tools
    assert len(tools) == 97
    expected_tools = {
        # Example tools
        "hello", "add",
        # SendGrid tools (14)
        "send_email", "send_template_email", "send_email_with_attachment",
        "schedule_email", "list_templates", "get_template", "get_email_stats",
        "get_bounces", "get_spam_reports", "manage_suppressions",
        "add_contacts", "search_contacts", "get_contact", "manage_lists",
        # ClickUp existing (25)
        "clickup_get_workspaces", "clickup_get_spaces", "clickup_get_lists",
        "clickup_create_task", "clickup_get_task", "clickup_update_task",
        "clickup_get_tasks", "clickup_search_tasks", "clickup_delete_task",
        "clickup_add_comment", "clickup_get_comments", "clickup_create_checklist",
        "clickup_add_checklist_item", "clickup_add_tag", "clickup_remove_tag",
        "clickup_log_time", "clickup_get_time_entries", "clickup_start_timer",
        "clickup_stop_timer", "clickup_create_space", "clickup_create_list",
        "clickup_create_folder", "clickup_get_members", "clickup_get_custom_fields",
        "clickup_set_custom_field",
        # ClickUp Group A: Space CRUD (3)
        "clickup_get_space", "clickup_update_space", "clickup_delete_space",
        # ClickUp Group B: Folder CRUD (4)
        "clickup_get_folders", "clickup_get_folder",
        "clickup_update_folder", "clickup_delete_folder",
        # ClickUp Group C: List CRUD (3)
        "clickup_get_list", "clickup_update_list", "clickup_delete_list",
        # ClickUp Group D: Comment Management (2)
        "clickup_update_comment", "clickup_delete_comment",
        # ClickUp Group E: Checklist Management (4)
        "clickup_update_checklist", "clickup_delete_checklist",
        "clickup_update_checklist_item", "clickup_delete_checklist_item",
        # ClickUp Group F: Time Tracking Extras (5)
        "clickup_get_task_time", "clickup_delete_task_time",
        "clickup_update_time_entry", "clickup_delete_time_entry",
        "clickup_get_running_timer",
        # ClickUp Group G: Tag Management (4)
        "clickup_get_space_tags", "clickup_create_space_tag",
        "clickup_update_space_tag", "clickup_delete_space_tag",
        # ClickUp Group H: Custom Field Removal (1)
        "clickup_remove_custom_field",
        # ClickUp Group I: Goals (8)
        "clickup_get_goals", "clickup_create_goal", "clickup_get_goal",
        "clickup_update_goal", "clickup_delete_goal",
        "clickup_create_key_result", "clickup_update_key_result",
        "clickup_delete_key_result",
        # ClickUp Group J: Time Entry Details (2)
        "clickup_get_time_entry", "clickup_get_time_entry_history",
        # ClickUp Group K: Time Entry Tags (4)
        "clickup_get_time_entry_tags", "clickup_add_time_entry_tags",
        "clickup_remove_time_entry_tags", "clickup_rename_time_entry_tag",
        # ClickUp Group L: Views (12)
        "clickup_get_workspace_views", "clickup_create_workspace_view",
        "clickup_get_space_views", "clickup_create_space_view",
        "clickup_get_folder_views", "clickup_create_folder_view",
        "clickup_get_list_views", "clickup_create_list_view",
        "clickup_get_view", "clickup_update_view", "clickup_delete_view",
        "clickup_get_view_tasks",
        # ClickUp Group M: Webhooks (4)
        "clickup_get_webhooks", "clickup_create_webhook",
        "clickup_update_webhook", "clickup_delete_webhook",
    }
    assert set(tools.keys()) == expected_tools
