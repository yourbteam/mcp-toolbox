# Task 03: ClickUp Integration - Analysis & Requirements

## Objective
Add ClickUp as the second tool integration in mcp-toolbox, exposing project management capabilities as MCP tools for LLM clients.

---

## API Technical Details

### API v2 — REST
- **Base URL:** `https://api.clickup.com/api/v2`
- **Auth:** Personal API Token via `Authorization: pk_XXXXXXX` header (also supports OAuth2)
- **Format:** JSON request/response
- **Rate Limits:**

| Plan | Limit |
|------|-------|
| Free / Unlimited / Business | 100 requests/minute per token |
| Business Plus | 1,000 requests/minute per token |
| Enterprise | 10,000 requests/minute per token |

- Rate limit headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- HTTP 429 on exceed

### No Official Python SDK
ClickUp does not maintain an official Python SDK. Community packages (`pyclickup`, etc.) are not actively maintained. **Recommendation:** Use `httpx` (already in our dependencies) for direct async HTTP calls — simpler, more reliable, and we control the async pattern.

### Key Quirks
- **"Team" = "Workspace"** — API uses `team_id` everywhere but it means workspace ID
- **Timestamps in milliseconds** — all dates are Unix ms, not seconds
- **Custom task IDs vs internal IDs** — tasks have a human-readable ID (e.g., `#abc123`) and an internal ID. API uses internal ID by default; pass `?custom_task_ids=true&team_id={team_id}` to use custom IDs
- **Status names are case-sensitive** — must exactly match list configuration
- **Subtasks hidden by default** — need `?subtasks=true` to include them
- **Pagination** — max 100 tasks per page, paginate with `?page=0`, `?page=1`, etc.
- **No Docs API** — ClickUp Docs cannot be created/edited via API
- **No bulk endpoints** — most operations require individual API calls

---

## ClickUp Hierarchy

```
Workspace (Team)
  └── Space
        └── Folder (optional)
              └── List
                    └── Task
                          └── Subtask (nested task)
                                └── Checklist
```

---

## Available API Capabilities

| Capability | API Support | Plan | Useful for MCP Tools? |
|-----------|-------------|------|----------------------|
| **Workspaces/Teams** | Read | All | Yes — workspace discovery |
| **Spaces** | Full CRUD | All | Yes — project organization |
| **Folders** | Full CRUD | All | Medium — organizational |
| **Lists** | Full CRUD | All | Yes — task containers |
| **Tasks** | Full CRUD + search + filter | All | **Critical** — core value |
| **Subtasks** | Via parent param | All | Yes — task breakdown |
| **Comments** | Full CRUD | All | Yes — collaboration |
| **Time Tracking** | Full CRUD + timers | All | Yes — productivity |
| **Goals** | Full CRUD + key results | Business+ | Lower priority |
| **Tags** | Full CRUD | All | Yes — organization |
| **Checklists** | Full CRUD | All | Yes — task detail |
| **Views** | Full CRUD | All | Lower priority |
| **Webhooks** | Full CRUD | All | Not applicable (push, not pull) |
| **Docs** | No API | N/A | Not possible |
| **Custom Fields** | Read + set/remove | Business+ | Medium |
| **Members/Users** | Read only | All | Yes — assignment |

---

## Tool Specifications

### Tier 1: Core Task Management (9 tools)

#### `clickup_get_workspaces`
List accessible workspaces/teams.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | | | Uses authenticated user's token |

**Returns:** List of workspaces with IDs, names, members.
**Endpoint:** `GET /team`

#### `clickup_get_spaces`
List spaces in a workspace.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to `CLICKUP_TEAM_ID`) |

**Returns:** List of spaces with IDs, names, features.
**Endpoint:** `GET /team/{team_id}/space?archived=false`
**Requires team_id:** Yes (from param or config)

#### `clickup_get_lists`
Get lists in a space or folder.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Conditional | Space ID (for folderless lists) |
| `folder_id` | str | Conditional | Folder ID (for lists in a folder) |

One of `space_id` or `folder_id` is required.
**Returns:** List of lists with IDs, names, statuses.
**Endpoint:** `GET /space/{space_id}/list` or `GET /folder/{folder_id}/list`

#### `clickup_create_task`
Create a task in a list. Pass `parent` to create a subtask.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `list_id` | str | Yes | List to create the task in |
| `name` | str | Yes | Task name |
| `description` | str | No | Task description (markdown supported) |
| `assignees` | list[int] | No | User IDs to assign |
| `status` | str | No | Status name (case-sensitive, must match list config) |
| `priority` | int | No | 1=Urgent, 2=High, 3=Normal, 4=Low, null=none |
| `due_date` | str | No | ISO datetime or Unix ms timestamp |
| `start_date` | str | No | ISO datetime or Unix ms timestamp |
| `tags` | list[str] | No | Tag names to apply |
| `parent` | str | No | Parent task ID (creates a subtask) |
| `time_estimate` | int | No | Estimated time in milliseconds |

**Returns:** Created task with ID, name, status, URL.
**Endpoint:** `POST /list/{list_id}/task`

#### `clickup_get_task`
Get task details by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `include_subtasks` | bool | No | Include subtasks (default false) |

**Returns:** Full task object with all properties.
**Endpoint:** `GET /task/{task_id}`

#### `clickup_update_task`
Update task properties.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `name` | str | No | New task name |
| `description` | str | No | New description |
| `status` | str | No | New status (case-sensitive) |
| `priority` | int | No | 1=Urgent, 2=High, 3=Normal, 4=Low |
| `due_date` | str | No | ISO datetime or Unix ms timestamp |
| `start_date` | str | No | ISO datetime or Unix ms timestamp |
| `assignees_add` | list[int] | No | User IDs to add |
| `assignees_remove` | list[int] | No | User IDs to remove |

**Returns:** Updated task object.
**Endpoint:** `PUT /task/{task_id}`

#### `clickup_get_tasks`
List tasks in a list with filtering and pagination.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `list_id` | str | Yes | List ID |
| `page` | int | No | Page number (default 0, max 100 per page) |
| `statuses` | list[str] | No | Filter by status names |
| `assignees` | list[int] | No | Filter by assignee user IDs |
| `include_closed` | bool | No | Include closed tasks (default false) |
| `subtasks` | bool | No | Include subtasks (default false) |
| `order_by` | str | No | `created`, `updated`, `due_date` |

**Returns:** List of tasks (max 100 per page).
**Endpoint:** `GET /list/{list_id}/task`

#### `clickup_search_tasks`
Search tasks across a workspace.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to `CLICKUP_TEAM_ID`) |
| `page` | int | No | Page number (default 0) |
| `statuses` | list[str] | No | Filter by statuses |
| `assignees` | list[int] | No | Filter by assignees |
| `tags` | list[str] | No | Filter by tags |
| `space_ids` | list[str] | No | Filter by spaces |
| `list_ids` | list[str] | No | Filter by lists |
| `include_closed` | bool | No | Include closed tasks |

**Returns:** List of tasks matching filters.
**Endpoint:** `GET /team/{team_id}/task`
**Requires team_id:** Yes (from param or config)

#### `clickup_delete_task`
Delete a task.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |

**Returns:** Confirmation of deletion.
**Endpoint:** `DELETE /task/{task_id}`

---

### Tier 2: Task Details (6 tools)

#### `clickup_add_comment`
Add a comment to a task.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `comment_text` | str | Yes | Comment text (plain text) |
| `assignee` | int | No | User ID to assign the comment to |

**Returns:** Created comment with ID.
**Endpoint:** `POST /task/{task_id}/comment`

#### `clickup_get_comments`
List comments on a task.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |

**Returns:** List of comments with text, author, date.
**Endpoint:** `GET /task/{task_id}/comment`

#### `clickup_create_checklist`
Add a checklist to a task.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `name` | str | Yes | Checklist name |

**Returns:** Created checklist with ID.
**Endpoint:** `POST /task/{task_id}/checklist`

#### `clickup_add_checklist_item`
Add an item to a checklist.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `checklist_id` | str | Yes | Checklist ID |
| `name` | str | Yes | Item text |
| `assignee` | int | No | User ID to assign |

**Returns:** Created checklist item.
**Endpoint:** `POST /checklist/{checklist_id}/checklist_item`

#### `clickup_add_tag`
Add a tag to a task.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `tag_name` | str | Yes | Tag name |

**Returns:** Confirmation.
**Endpoint:** `POST /task/{task_id}/tag/{tag_name}`

#### `clickup_remove_tag`
Remove a tag from a task.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `tag_name` | str | Yes | Tag name |

**Returns:** Confirmation.
**Endpoint:** `DELETE /task/{task_id}/tag/{tag_name}`

---

### Tier 3: Time Tracking (4 tools)

#### `clickup_log_time`
Log a time entry on a task.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `duration` | int | Yes | Duration in milliseconds |
| `description` | str | No | Description of work done |
| `start` | str | No | Start time (ISO datetime or Unix ms) |
| `end` | str | No | End time (ISO datetime or Unix ms) |

**Returns:** Created time entry.
**Endpoint:** `POST /task/{task_id}/time`

#### `clickup_get_time_entries`
Get time entries for a workspace.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |
| `start_date` | str | No | Filter start (ISO datetime or Unix ms) |
| `end_date` | str | No | Filter end (ISO datetime or Unix ms) |
| `assignees` | list[int] | No | Filter by user IDs |

**Returns:** List of time entries.
**Endpoint:** `GET /team/{team_id}/time_entries`
**Requires team_id:** Yes (from param or config)

#### `clickup_start_timer`
Start a running timer for the authenticated user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |
| `task_id` | str | Yes | Task to track time on |
| `description` | str | No | Timer description |

**Returns:** Timer entry details.
**Endpoint:** `POST /team/{team_id}/time_entries/start`
**Requires team_id:** Yes (from param or config)

#### `clickup_stop_timer`
Stop the running timer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |

**Returns:** Stopped timer details with duration.
**Endpoint:** `POST /team/{team_id}/time_entries/stop`
**Requires team_id:** Yes (from param or config)

---

### Tier 4: Organizational (6 tools)

#### `clickup_create_space`
Create a new space in a workspace.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |
| `name` | str | Yes | Space name |

**Returns:** Created space with ID.
**Endpoint:** `POST /team/{team_id}/space`
**Requires team_id:** Yes (from param or config)

#### `clickup_create_list`
Create a new list in a space or folder.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Conditional | Space ID (for folderless list) |
| `folder_id` | str | Conditional | Folder ID |
| `name` | str | Yes | List name |

One of `space_id` or `folder_id` required.
**Endpoint:** `POST /space/{space_id}/list` or `POST /folder/{folder_id}/list`

#### `clickup_create_folder`
Create a folder in a space.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `space_id` | str | Yes | Space ID |
| `name` | str | Yes | Folder name |

**Returns:** Created folder with ID.
**Endpoint:** `POST /space/{space_id}/folder`

#### `clickup_get_members`
List workspace members.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | No | Workspace ID (falls back to config) |

**Returns:** List of members with IDs, names, emails, roles.
**Endpoint:** Extracted from `GET /team/{team_id}` response.
**Requires team_id:** Yes (from param or config)

#### `clickup_get_custom_fields`
Get accessible custom fields for a list.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `list_id` | str | Yes | List ID |

**Returns:** List of custom fields with IDs, names, types.
**Endpoint:** `GET /list/{list_id}/field`

#### `clickup_set_custom_field`
Set a custom field value on a task.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `field_id` | str | Yes | Custom field ID |
| `value` | any | Yes | Field value (type depends on field definition) |

**Returns:** Confirmation.
**Endpoint:** `POST /task/{task_id}/field/{field_id}`

---

## Architecture Decisions

### A1: Direct HTTP with httpx (no SDK)
Since there's no official Python SDK, we'll use `httpx` (already a project dependency) for async HTTP calls directly. This gives us:
- Native async support (no `asyncio.to_thread()` wrapping needed)
- Full control over error handling and response parsing
- No dependency on unmaintained community packages

### A2: Shared httpx Client
Create a shared `httpx.AsyncClient` with base URL and auth headers. Reuse across all tool calls.

```python
import httpx

_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    if not CLICKUP_API_TOKEN:
        raise ToolError("CLICKUP_API_TOKEN is not configured.")
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url="https://api.clickup.com/api/v2",
            headers={"Authorization": CLICKUP_API_TOKEN},
            timeout=30.0,
        )
    return _client
```

**Lifecycle:** The `AsyncClient` is process-scoped — it lives for the duration of the MCP server process and is cleaned up on exit. For STDIO transport (single-user, short-lived process), explicit `aclose()` is not needed. For Streamable HTTP (long-lived, multi-client), the server would need a shutdown hook. This is acceptable for the current transport model.

### A3: Tool Naming Convention
All ClickUp tools prefixed with `clickup_` to distinguish from SendGrid tools and future integrations.

### A4: Error Handling
Same pattern as SendGrid: catch `httpx` exceptions, convert to `ToolError` with human-readable messages. 429 responses result in a ToolError with rate limit details (remaining count, reset time from headers). No automatic retry — the calling LLM can retry if appropriate. Status validation is delegated to the ClickUp API — invalid status names produce a descriptive 400 error that is surfaced as a ToolError.

### A8: Pagination
Tools return a single page of results. Callers can request specific pages via a `page` parameter (default 0). No auto-pagination to keep response sizes bounded. Max 100 items per page (ClickUp API limit).

### A5: Response Format
Same JSON convention as SendGrid: `{"status": "success", ...}` or `{"status": "error", ...}`.

### A6: Timestamp Handling
ClickUp uses Unix timestamps in **milliseconds**. Provide helper to convert ISO datetime strings to ms timestamps and vice versa.

### A7: Missing API Key Strategy
Same as SendGrid: register tools regardless, fail at invocation with clear `ToolError`.

---

## Configuration Requirements

### Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `CLICKUP_API_TOKEN` | Personal API token (format: `pk_xxxxx`) | Yes (at invocation) | `None` |
| `CLICKUP_TEAM_ID` | Default workspace/team ID | No (but needed by many tools) | `None` |

### Config Pattern
```python
CLICKUP_API_TOKEN: str | None = os.getenv("CLICKUP_API_TOKEN")
CLICKUP_TEAM_ID: str | None = os.getenv("CLICKUP_TEAM_ID")
```

### team_id Dependency
Many tools require `team_id`. Each accepts it as an optional parameter with fallback to `CLICKUP_TEAM_ID` config. If neither is available, tools raise `ToolError`.

**Tools requiring team_id:** `clickup_get_spaces`, `clickup_search_tasks`, `clickup_get_time_entries`, `clickup_start_timer`, `clickup_stop_timer`, `clickup_create_space`, `clickup_get_members`

**Tools NOT requiring team_id:** All task CRUD (uses task_id/list_id directly), comments, checklists, tags, custom fields

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/config.py` | Modify | Add `CLICKUP_API_TOKEN`, `CLICKUP_TEAM_ID` |
| `.env.example` | Modify | Add ClickUp variables |
| `src/mcp_toolbox/tools/clickup_tool.py` | **New** | All ClickUp tools |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register clickup_tool |
| `tests/test_clickup_tool.py` | **New** | Tests for all ClickUp tools |
| `CLAUDE.md` | Modify | Document ClickUp integration |

---

## Testing Strategy

### Approach
Use `pytest` with `httpx`'s built-in mock/transport support or `respx` library for mocking HTTP calls. Since we're using `httpx` directly (not an SDK), mocking is cleaner:

```python
import respx

@respx.mock
async def test_create_task():
    respx.post("https://api.clickup.com/api/v2/list/123/task").mock(
        return_value=httpx.Response(200, json={"id": "task_abc", "name": "My Task"})
    )
    result = await server.call_tool("clickup_create_task", {...})
    assert ...
```

Alternative: use `httpx.MockTransport` to inject into the shared client.

### Test Coverage
Same discipline as SendGrid:
1. Happy path for every tool
2. Missing API token → ToolError
3. API errors (401, 404, 429)
4. Input normalization (timestamps, lists)

---

## Dependencies

| Package | Purpose | Already in project? |
|---------|---------|-------------------|
| `httpx` | Async HTTP client | Yes |
| `respx` | httpx mock library (dev) | **New** — add to dev deps |

---

## Success Criteria

1. `uv sync` installs without errors (no new runtime deps needed)
2. All 25 ClickUp tools register and are discoverable via MCP Inspector
3. Tools return meaningful errors when API token is missing
4. All tools return consistent JSON responses
5. New tests pass and full regression suite remains green
6. Config handles missing API token gracefully

---

## Scope Decision

**All 4 tiers (25 tools)** — full integration covering task management, task details, time tracking, and organizational tools.

---

## Tool Summary (25 tools total)

### Tier 1 — Core Task Management (9 tools)
1. `clickup_get_workspaces` — List accessible workspaces
2. `clickup_get_spaces` — List spaces in a workspace
3. `clickup_get_lists` — Get lists in a space or folder
4. `clickup_create_task` — Create a task with name, description, assignees, priority, due date, status
5. `clickup_get_task` — Get task details by ID
6. `clickup_update_task` — Update task properties (status, priority, assignees, due date, etc.)
7. `clickup_get_tasks` — List/filter tasks in a list with pagination
8. `clickup_search_tasks` — Search tasks across a workspace with filters
9. `clickup_delete_task` — Delete a task

### Tier 2 — Task Details (6 tools)
10. `clickup_add_comment` — Add a comment to a task
11. `clickup_get_comments` — List comments on a task
12. `clickup_create_checklist` — Add a checklist to a task
13. `clickup_add_checklist_item` — Add item to a checklist
14. `clickup_add_tag` — Add a tag to a task
15. `clickup_remove_tag` — Remove a tag from a task

### Tier 3 — Time Tracking (4 tools)
16. `clickup_log_time` — Log a time entry on a task
17. `clickup_get_time_entries` — Get time entries for a task or workspace
18. `clickup_start_timer` — Start a running timer
19. `clickup_stop_timer` — Stop the running timer

### Tier 4 — Organizational (6 tools)
20. `clickup_create_space` — Create a new space in a workspace
21. `clickup_create_list` — Create a new list in a space or folder
22. `clickup_create_folder` — Create a folder in a space
23. `clickup_get_members` — List workspace members
24. `clickup_get_custom_fields` — Get custom fields for a list
25. `clickup_set_custom_field` — Set a custom field value on a task
