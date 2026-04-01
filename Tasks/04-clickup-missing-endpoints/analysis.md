# Task 04: ClickUp Missing Endpoints - Analysis & Requirements

## Objective
Add all remaining ClickUp API v2 endpoints as tools to the existing `clickup_tool.py`, completing full API coverage.

---

## Current State

The existing `clickup_tool.py` has **25 tools**. This task adds the remaining endpoints that were not included in the initial integration.

### Already Implemented (25 tools)
| Tool | Endpoint |
|------|----------|
| `clickup_get_workspaces` | `GET /team` |
| `clickup_get_spaces` | `GET /team/{team_id}/space` |
| `clickup_get_lists` | `GET /space/{space_id}/list` or `GET /folder/{folder_id}/list` |
| `clickup_create_task` | `POST /list/{list_id}/task` |
| `clickup_get_task` | `GET /task/{task_id}` |
| `clickup_update_task` | `PUT /task/{task_id}` |
| `clickup_get_tasks` | `GET /list/{list_id}/task` |
| `clickup_search_tasks` | `GET /team/{team_id}/task` |
| `clickup_delete_task` | `DELETE /task/{task_id}` |
| `clickup_add_comment` | `POST /task/{task_id}/comment` |
| `clickup_get_comments` | `GET /task/{task_id}/comment` |
| `clickup_create_checklist` | `POST /task/{task_id}/checklist` |
| `clickup_add_checklist_item` | `POST /checklist/{checklist_id}/checklist_item` |
| `clickup_add_tag` | `POST /task/{task_id}/tag/{tag_name}` |
| `clickup_remove_tag` | `DELETE /task/{task_id}/tag/{tag_name}` |
| `clickup_log_time` | `POST /task/{task_id}/time` |
| `clickup_get_time_entries` | `GET /team/{team_id}/time_entries` |
| `clickup_start_timer` | `POST /team/{team_id}/time_entries/start` |
| `clickup_stop_timer` | `POST /team/{team_id}/time_entries/stop` |
| `clickup_create_space` | `POST /team/{team_id}/space` |
| `clickup_create_list` | `POST /space/{space_id}/list` or `POST /folder/{folder_id}/list` |
| `clickup_create_folder` | `POST /space/{space_id}/folder` |
| `clickup_get_members` | `GET /team/{team_id}` (members extracted) |
| `clickup_get_custom_fields` | `GET /list/{list_id}/field` |
| `clickup_set_custom_field` | `POST /task/{task_id}/field/{field_id}` |

---

## Missing Endpoints to Add

### Group A: Space CRUD (3 tools)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_get_space` | `GET /space/{space_id}` | Get single space details |
| `clickup_update_space` | `PUT /space/{space_id}` | Update space name/features |
| `clickup_delete_space` | `DELETE /space/{space_id}` | Delete a space |

#### `clickup_get_space`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Yes | Space ID |

**Returns:** Space object with ID, name, features, statuses.

#### `clickup_update_space`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Yes | Space ID |
| `name` | str | No | New space name |
| `color` | str | No | Space color hex |
| `private` | bool | No | Make space private |
| `admin_can_manage` | bool | No | Admin-only management |

**Returns:** Updated space object.

#### `clickup_delete_space`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Yes | Space ID |

**Returns:** Confirmation of deletion.

---

### Group B: Folder CRUD (4 tools)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_get_folders` | `GET /space/{space_id}/folder` | List folders in a space |
| `clickup_get_folder` | `GET /folder/{folder_id}` | Get single folder details |
| `clickup_update_folder` | `PUT /folder/{folder_id}` | Update folder name |
| `clickup_delete_folder` | `DELETE /folder/{folder_id}` | Delete a folder |

#### `clickup_get_folders`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Yes | Space ID |

**Returns:** List of folders with IDs, names.

#### `clickup_get_folder`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `folder_id` | str | Yes | Folder ID |

**Returns:** Folder object with ID, name, lists, statuses.
**Endpoint:** `GET /folder/{folder_id}`

#### `clickup_update_folder`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `folder_id` | str | Yes | Folder ID |
| `name` | str | Yes | New folder name |

**Returns:** Updated folder object.

#### `clickup_delete_folder`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `folder_id` | str | Yes | Folder ID |

**Returns:** Confirmation of deletion.

---

### Group C: List CRUD (3 tools)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_get_list` | `GET /list/{list_id}` | Get single list details |
| `clickup_update_list` | `PUT /list/{list_id}` | Update list properties |
| `clickup_delete_list` | `DELETE /list/{list_id}` | Delete a list |

#### `clickup_get_list`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `list_id` | str | Yes | List ID |

**Returns:** List object with ID, name, statuses, content.

#### `clickup_update_list`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `list_id` | str | Yes | List ID |
| `name` | str | No | New list name |
| `content` | str | No | List description |
| `status` | str | No | Default status |

**Returns:** Updated list object.

#### `clickup_delete_list`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `list_id` | str | Yes | List ID |

**Returns:** Confirmation of deletion.

---

### Group D: Comment Management (2 tools)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_update_comment` | `PUT /comment/{comment_id}` | Update a comment |
| `clickup_delete_comment` | `DELETE /comment/{comment_id}` | Delete a comment |

#### `clickup_update_comment`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `comment_id` | str | Yes | Comment ID |
| `comment_text` | str | Yes | New comment text |
| `assignee` | int | No | New assignee user ID |

**Returns:** Confirmation of update.

#### `clickup_delete_comment`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `comment_id` | str | Yes | Comment ID |

**Returns:** Confirmation of deletion.

---

### Group E: Checklist Management (4 tools)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_update_checklist` | `PUT /checklist/{checklist_id}` | Rename a checklist |
| `clickup_delete_checklist` | `DELETE /checklist/{checklist_id}` | Delete a checklist |
| `clickup_update_checklist_item` | `PUT /checklist/{checklist_id}/checklist_item/{item_id}` | Update/toggle checklist item |
| `clickup_delete_checklist_item` | `DELETE /checklist/{checklist_id}/checklist_item/{item_id}` | Delete a checklist item |

#### `clickup_update_checklist`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `checklist_id` | str | Yes | Checklist ID |
| `name` | str | Yes | New checklist name |

**Returns:** Updated checklist.

#### `clickup_delete_checklist`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `checklist_id` | str | Yes | Checklist ID |

**Returns:** Confirmation of deletion.

#### `clickup_update_checklist_item`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `checklist_id` | str | Yes | Checklist ID |
| `checklist_item_id` | str | Yes | Item ID |
| `name` | str | No | New item text |
| `resolved` | bool | No | Mark item as resolved/unresolved |
| `assignee` | int | No | Assign to user ID |

**Returns:** Updated checklist item.

#### `clickup_delete_checklist_item`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `checklist_id` | str | Yes | Checklist ID |
| `checklist_item_id` | str | Yes | Item ID |

**Returns:** Confirmation of deletion.

---

### Group F: Time Tracking Extras (5 tools)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_get_task_time` | `GET /task/{task_id}/time` | Get time entries for a specific task |
| `clickup_delete_task_time` | `DELETE /task/{task_id}/time/{interval_id}` | Delete a time entry from a task |
| `clickup_update_time_entry` | `PUT /team/{team_id}/time_entries/{timer_id}` | Update a time entry |
| `clickup_delete_time_entry` | `DELETE /team/{team_id}/time_entries/{timer_id}` | Delete a time entry |
| `clickup_get_running_timer` | `GET /team/{team_id}/time_entries/running` | Get currently running timer |

#### `clickup_get_task_time`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |

**Returns:** List of time entries for the task.

#### `clickup_delete_task_time`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `interval_id` | str | Yes | Time interval ID |

**Returns:** Confirmation of deletion.

#### `clickup_update_time_entry`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |
| `timer_id` | str | Yes | Time entry ID |
| `description` | str | No | New description |
| `duration` | int | No | New duration in milliseconds |
| `start` | str or int | No | New start time |
| `end` | str or int | No | New end time |
| `tags` | list[str] | No | Tags for the entry |

**Returns:** Updated time entry.
**Requires team_id:** Yes (from param or config)

#### `clickup_delete_time_entry`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |
| `timer_id` | str | Yes | Time entry ID |

**Returns:** Confirmation of deletion.
**Requires team_id:** Yes (from param or config)

#### `clickup_get_running_timer`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |

**Returns:** Running timer details or empty if none active.
**Requires team_id:** Yes (from param or config)

---

### Group G: Tag Management (4 tools)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_get_space_tags` | `GET /space/{space_id}/tag` | List tags in a space |
| `clickup_create_space_tag` | `POST /space/{space_id}/tag` | Create a new tag |
| `clickup_update_space_tag` | `PUT /space/{space_id}/tag/{tag_name}` | Update tag properties |
| `clickup_delete_space_tag` | `DELETE /space/{space_id}/tag/{tag_name}` | Delete a tag |

#### `clickup_get_space_tags`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Yes | Space ID |

**Returns:** List of tags with names and colors.

#### `clickup_create_space_tag`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Yes | Space ID |
| `name` | str | Yes | Tag name |
| `tag_fg` | str | No | Foreground color hex |
| `tag_bg` | str | No | Background color hex |

**Returns:** Created tag.

#### `clickup_update_space_tag`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Yes | Space ID |
| `tag_name` | str | Yes | Current tag name |
| `new_name` | str | No | New tag name |
| `tag_fg` | str | No | New foreground color |
| `tag_bg` | str | No | New background color |

**Returns:** Updated tag.

#### `clickup_delete_space_tag`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Yes | Space ID |
| `tag_name` | str | Yes | Tag name to delete |

**Returns:** Confirmation of deletion.

---

### Group H: Custom Field Removal (1 tool)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_remove_custom_field` | `DELETE /task/{task_id}/field/{field_id}` | Remove a custom field value |

#### `clickup_remove_custom_field`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `field_id` | str | Yes | Custom field ID |

**Returns:** Confirmation of removal.

---

### Group I: Goals (8 tools — Business+ only)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_get_goals` | `GET /team/{team_id}/goal` | List goals |
| `clickup_create_goal` | `POST /team/{team_id}/goal` | Create a goal |
| `clickup_get_goal` | `GET /goal/{goal_id}` | Get goal details |
| `clickup_update_goal` | `PUT /goal/{goal_id}` | Update a goal |
| `clickup_delete_goal` | `DELETE /goal/{goal_id}` | Delete a goal |
| `clickup_create_key_result` | `POST /goal/{goal_id}/key_result` | Add a key result to a goal |
| `clickup_update_key_result` | `PUT /key_result/{key_result_id}` | Update a key result |
| `clickup_delete_key_result` | `DELETE /key_result/{key_result_id}` | Delete a key result |

#### `clickup_get_goals`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |

**Returns:** List of goals.
**Requires team_id:** Yes

#### `clickup_create_goal`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |
| `name` | str | Yes | Goal name |
| `due_date` | str or int | No | Goal deadline |
| `description` | str | No | Goal description |
| `color` | str | No | Goal color hex |

**Returns:** Created goal.
**Requires team_id:** Yes

#### `clickup_get_goal`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `goal_id` | str | Yes | Goal ID |

**Returns:** Goal details with key results.

#### `clickup_update_goal`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `goal_id` | str | Yes | Goal ID |
| `name` | str | No | New goal name |
| `due_date` | str or int | No | New deadline |
| `description` | str | No | New description |
| `color` | str | No | New color |

**Returns:** Updated goal.

#### `clickup_delete_goal`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `goal_id` | str | Yes | Goal ID |

**Returns:** Confirmation of deletion.

#### `clickup_create_key_result`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `goal_id` | str | Yes | Goal ID |
| `name` | str | Yes | Key result name |
| `type` | str | Yes | `number`, `currency`, `boolean`, `percentage`, or `automatic` |
| `steps_start` | int | No | Starting value (for number/currency/percentage) |
| `steps_end` | int | No | Target value |
| `unit` | str | No | Unit label (e.g., "$", "tasks") |

**Returns:** Created key result.

#### `clickup_update_key_result`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `key_result_id` | str | Yes | Key result ID |
| `steps_current` | int | No | Current progress value |
| `note` | str | No | Progress note |

**Returns:** Updated key result.

#### `clickup_delete_key_result`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `key_result_id` | str | Yes | Key result ID |

**Returns:** Confirmation of deletion.
**Endpoint:** `DELETE /key_result/{key_result_id}`

---

### Group J: Time Entry Details (2 tools)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_get_time_entry` | `GET /team/{team_id}/time_entries/{timer_id}` | Get a single time entry |
| `clickup_get_time_entry_history` | `GET /team/{team_id}/time_entries/{timer_id}/history` | Get edit history of a time entry |

#### `clickup_get_time_entry`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `timer_id` | str | Yes | Time entry ID |
| `team_id` | str | No | Workspace ID (falls back to config) |

**Returns:** Time entry details.
**Requires team_id:** Yes (from param or config)

#### `clickup_get_time_entry_history`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `timer_id` | str | Yes | Time entry ID |
| `team_id` | str | No | Workspace ID (falls back to config) |

**Returns:** List of history entries showing edits.
**Requires team_id:** Yes (from param or config)

---

### Group K: Time Entry Tags (4 tools)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_get_time_entry_tags` | `GET /team/{team_id}/time_entries/tags` | List all time entry tags |
| `clickup_add_time_entry_tags` | `POST /team/{team_id}/time_entries/tags` | Add tags to time entries |
| `clickup_remove_time_entry_tags` | `DELETE /team/{team_id}/time_entries/tags` | Remove tags from time entries |
| `clickup_rename_time_entry_tag` | `PUT /team/{team_id}/time_entries/tags` | Rename a time entry tag |

#### `clickup_get_time_entry_tags`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |

**Returns:** List of time entry tags with names and colors.
**Requires team_id:** Yes

#### `clickup_add_time_entry_tags`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |
| `time_entry_ids` | list[str] | Yes | Time entry IDs to tag |
| `tags` | list[dict] | Yes | Tags to add (each: `{"name": "tag_name"}`) |

**Returns:** Confirmation.
**Requires team_id:** Yes

#### `clickup_remove_time_entry_tags`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |
| `time_entry_ids` | list[str] | Yes | Time entry IDs to untag |
| `tags` | list[dict] | Yes | Tags to remove (each: `{"name": "tag_name"}`) |

**Returns:** Confirmation.
**Requires team_id:** Yes

#### `clickup_rename_time_entry_tag`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |
| `name` | str | Yes | Current tag name |
| `new_name` | str | Yes | New tag name |

**Returns:** Confirmation.
**Requires team_id:** Yes

---

### Group L: Views (12 tools)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_get_workspace_views` | `GET /team/{team_id}/view` | List workspace-level views |
| `clickup_create_workspace_view` | `POST /team/{team_id}/view` | Create workspace-level view |
| `clickup_get_space_views` | `GET /space/{space_id}/view` | List space-level views |
| `clickup_create_space_view` | `POST /space/{space_id}/view` | Create space-level view |
| `clickup_get_folder_views` | `GET /folder/{folder_id}/view` | List folder-level views |
| `clickup_create_folder_view` | `POST /folder/{folder_id}/view` | Create folder-level view |
| `clickup_get_list_views` | `GET /list/{list_id}/view` | List list-level views |
| `clickup_create_list_view` | `POST /list/{list_id}/view` | Create list-level view |
| `clickup_get_view` | `GET /view/{view_id}` | Get individual view details |
| `clickup_update_view` | `PUT /view/{view_id}` | Update view config |
| `clickup_delete_view` | `DELETE /view/{view_id}` | Delete a view |
| `clickup_get_view_tasks` | `GET /view/{view_id}/task` | Get tasks visible in a view |

#### `clickup_get_workspace_views`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |

**Returns:** List of views.
**Requires team_id:** Yes

#### `clickup_create_workspace_view`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |
| `name` | str | Yes | View name |
| `type` | str | Yes | View type: `list`, `board`, `calendar`, `gantt`, `table`, `timeline`, `workload`, `map`, `activity` |

**Returns:** Created view.
**Requires team_id:** Yes

#### `clickup_get_space_views`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Yes | Space ID |

**Returns:** List of views.

#### `clickup_create_space_view`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Yes | Space ID |
| `name` | str | Yes | View name |
| `type` | str | Yes | View type |

**Returns:** Created view.

#### `clickup_get_folder_views`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `folder_id` | str | Yes | Folder ID |

**Returns:** List of views.

#### `clickup_create_folder_view`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `folder_id` | str | Yes | Folder ID |
| `name` | str | Yes | View name |
| `type` | str | Yes | View type |

**Returns:** Created view.

#### `clickup_get_list_views`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `list_id` | str | Yes | List ID |

**Returns:** List of views.

#### `clickup_create_list_view`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `list_id` | str | Yes | List ID |
| `name` | str | Yes | View name |
| `type` | str | Yes | View type |

**Returns:** Created view.

#### `clickup_get_view`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `view_id` | str | Yes | View ID |

**Returns:** View details with config (sorting, filtering, grouping, columns).

#### `clickup_update_view`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `view_id` | str | Yes | View ID |
| `name` | str | No | New view name |
| `type` | str | No | New view type |

**Returns:** Updated view.

#### `clickup_delete_view`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `view_id` | str | Yes | View ID |

**Returns:** Confirmation of deletion.

#### `clickup_get_view_tasks`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `view_id` | str | Yes | View ID |
| `page` | int | No | Page number (default 0) |

**Returns:** List of tasks visible in the view (max 100 per page).

---

### Group M: Webhooks (4 tools)

| Tool | Endpoint | Description |
|------|----------|-------------|
| `clickup_get_webhooks` | `GET /team/{team_id}/webhook` | List webhooks |
| `clickup_create_webhook` | `POST /team/{team_id}/webhook` | Create a webhook |
| `clickup_update_webhook` | `PUT /webhook/{webhook_id}` | Update webhook config |
| `clickup_delete_webhook` | `DELETE /webhook/{webhook_id}` | Delete a webhook |

#### `clickup_get_webhooks`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |

**Returns:** List of webhooks with IDs, endpoints, events, health status.
**Requires team_id:** Yes

#### `clickup_create_webhook`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |
| `endpoint` | str | Yes | URL to receive webhook POSTs |
| `events` | list[str] | Yes | Event types (e.g., `taskCreated`, `taskUpdated`, `taskDeleted`, `taskStatusUpdated`, `taskAssigneeUpdated`, `taskCommentPosted`, etc.) |
| `space_id` | str | No | Scope to specific space |
| `folder_id` | str | No | Scope to specific folder |
| `list_id` | str | No | Scope to specific list |

**Returns:** Created webhook with ID and secret.
**Requires team_id:** Yes

#### `clickup_update_webhook`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `webhook_id` | str | Yes | Webhook ID |
| `endpoint` | str | No | New URL |
| `events` | list[str] | No | New event types |
| `status` | str | No | `active` or `inactive` |

**Returns:** Updated webhook.

#### `clickup_delete_webhook`
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `webhook_id` | str | Yes | Webhook ID |

**Returns:** Confirmation of deletion.

---

## Summary

| Group | New Tools |
|-------|-----------|
| A: Space CRUD | 3 |
| B: Folder CRUD | 4 |
| C: List CRUD | 3 |
| D: Comment Management | 2 |
| E: Checklist Management | 4 |
| F: Time Tracking Extras | 5 |
| G: Tag Management | 4 |
| H: Custom Field Removal | 1 |
| I: Goals | 8 |
| J: Time Entry Details | 2 |
| K: Time Entry Tags | 4 |
| L: Views | 12 |
| M: Webhooks | 4 |
| **Total new tools** | **56** |
| **Existing tools** | **25** |
| **Grand total after completion** | **81** |

---

## Architecture

No new patterns needed — all tools follow the existing conventions:
- Use `_request()` helper for all HTTP calls
- Use `_get_team_id()` for team_id resolution
- Use `_to_ms()` for timestamp conversion
- Use `_success()` for consistent JSON responses
- Use `ToolError` for error responses
- Register via `register_tools(mcp)` in the existing function

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/tools/clickup_tool.py` | Modify | Add 56 new tools inside `register_tools()` |
| `tests/test_clickup_tool.py` | Modify | Add tests for all 56 new tools |
| `tests/test_server.py` | Modify | Update tool count to 97 and add new tool names |
| `CLAUDE.md` | Modify | Update ClickUp tool count and tier descriptions |

---

## Testing Strategy

Same as existing ClickUp tests:
- `respx` for HTTP mocking
- `_get_result_data()` helper for result parsing
- Happy path for every tool
- Validation error tests where applicable (missing required params)
- Reuse existing `server` fixture

---

## Success Criteria

1. All 81 ClickUp tools register and are discoverable
2. New tests pass and full regression suite (59 existing + new) remains green
3. `ruff` and `pyright` pass clean
4. `test_server.py` validates all tool names (25 existing clickup + 56 new = 81 clickup, plus 2 example + 14 sendgrid = 97 total)
