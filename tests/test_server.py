"""Tests for server initialization."""

from mcp_toolbox.server import mcp


def test_server_name():
    assert mcp.name == "mcp-toolbox"


def test_server_has_tools():
    # 2+14+81+19+28+39+13+28+4+23+43 = 294
    tools = mcp._tool_manager._tools
    assert len(tools) == 294
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
        # O365 tools (19)
        "o365_send_email", "o365_send_email_with_attachment",
        "o365_reply", "o365_reply_all", "o365_forward",
        "o365_list_messages", "o365_get_message", "o365_search_messages",
        "o365_list_attachments", "o365_move_message",
        "o365_create_draft", "o365_update_draft", "o365_add_draft_attachment",
        "o365_send_draft", "o365_delete_draft",
        "o365_get_folder", "o365_list_folders", "o365_create_folder",
        "o365_delete_folder",
        # Teams tools (28)
        "teams_list_teams", "teams_get_team", "teams_create_team",
        "teams_update_team", "teams_archive_team", "teams_unarchive_team",
        "teams_list_members", "teams_add_member", "teams_remove_member",
        "teams_list_channels", "teams_get_channel", "teams_create_channel",
        "teams_update_channel", "teams_delete_channel",
        "teams_list_channel_messages", "teams_get_message",
        "teams_list_message_replies", "teams_send_webhook_message",
        "teams_send_channel_message_delegated",
        "teams_create_meeting", "teams_list_meetings",
        "teams_get_meeting", "teams_delete_meeting",
        "teams_get_presence", "teams_get_presence_bulk",
        "teams_list_chats", "teams_get_chat", "teams_list_chat_messages",
        # Key Vault tools (39)
        "kv_set_secret", "kv_get_secret", "kv_list_secrets",
        "kv_list_secret_versions", "kv_update_secret",
        "kv_delete_secret", "kv_recover_secret", "kv_purge_secret",
        "kv_list_deleted_secrets", "kv_backup_secret", "kv_restore_secret",
        "kv_create_key", "kv_get_key", "kv_list_keys", "kv_list_key_versions",
        "kv_update_key", "kv_delete_key", "kv_recover_key", "kv_purge_key",
        "kv_list_deleted_keys", "kv_rotate_key",
        "kv_encrypt", "kv_decrypt", "kv_sign", "kv_verify",
        "kv_wrap_key", "kv_unwrap_key", "kv_backup_key", "kv_restore_key",
        "kv_get_certificate", "kv_list_certificates",
        "kv_list_certificate_versions", "kv_create_certificate",
        "kv_import_certificate", "kv_update_certificate",
        "kv_delete_certificate", "kv_recover_certificate",
        "kv_purge_certificate", "kv_list_deleted_certificates",
        # AWS SSM tools (13)
        "aws_ssm_put_parameter", "aws_ssm_get_parameter",
        "aws_ssm_get_parameters", "aws_ssm_get_parameters_by_path",
        "aws_ssm_describe_parameters",
        "aws_ssm_delete_parameter", "aws_ssm_delete_parameters",
        "aws_ssm_get_parameter_history",
        "aws_ssm_label_parameter_version", "aws_ssm_unlabel_parameter_version",
        "aws_ssm_add_tags", "aws_ssm_remove_tags", "aws_ssm_list_tags",
        # Slack tools (28)
        "slack_send_message", "slack_send_dm", "slack_update_message",
        "slack_delete_message", "slack_schedule_message",
        "slack_get_channel_history", "slack_get_thread_replies",
        "slack_list_channels", "slack_get_channel_info", "slack_create_channel",
        "slack_archive_channel", "slack_unarchive_channel",
        "slack_invite_to_channel", "slack_list_channel_members",
        "slack_set_channel_topic", "slack_set_channel_purpose",
        "slack_list_users", "slack_get_user_info",
        "slack_find_user_by_email", "slack_get_user_presence",
        "slack_add_reaction", "slack_remove_reaction", "slack_get_reactions",
        "slack_pin_message", "slack_unpin_message", "slack_list_pins",
        "slack_upload_file", "slack_delete_file",
        # Generic HTTP tools (4)
        "http_request", "http_request_form", "http_download", "http_upload",
        # Calendar tools (23)
        "calendar_list_calendars", "calendar_get_calendar",
        "calendar_create_calendar", "calendar_delete_calendar",
        "calendar_create_event", "calendar_get_event",
        "calendar_update_event", "calendar_delete_event", "calendar_list_events",
        "calendar_accept_event", "calendar_decline_event",
        "calendar_tentatively_accept_event",
        "calendar_get_schedule", "calendar_find_meeting_times",
        "calendar_list_event_instances",
        "calendar_forward_event", "calendar_cancel_event",
        "calendar_add_event_attachment", "calendar_list_event_attachments",
        "calendar_get_event_attachment", "calendar_delete_event_attachment",
        "calendar_snooze_reminder", "calendar_dismiss_reminder",
        # HubSpot tools (43)
        "hubspot_create_contact", "hubspot_get_contact", "hubspot_update_contact",
        "hubspot_delete_contact", "hubspot_list_contacts", "hubspot_search_contacts",
        "hubspot_create_company", "hubspot_get_company", "hubspot_update_company",
        "hubspot_delete_company", "hubspot_list_companies", "hubspot_search_companies",
        "hubspot_create_deal", "hubspot_get_deal", "hubspot_update_deal",
        "hubspot_delete_deal", "hubspot_list_deals", "hubspot_search_deals",
        "hubspot_create_ticket", "hubspot_get_ticket", "hubspot_update_ticket",
        "hubspot_delete_ticket", "hubspot_list_tickets", "hubspot_search_tickets",
        "hubspot_create_note", "hubspot_get_note", "hubspot_list_notes",
        "hubspot_update_note", "hubspot_delete_note", "hubspot_search_notes",
        "hubspot_create_association", "hubspot_remove_association",
        "hubspot_get_associations", "hubspot_list_association_types",
        "hubspot_list_pipelines", "hubspot_list_pipeline_stages",
        "hubspot_list_owners", "hubspot_get_owner",
        "hubspot_list_properties", "hubspot_get_property", "hubspot_create_property",
        "hubspot_batch_create", "hubspot_batch_update",
    }
    assert set(tools.keys()) == expected_tools
