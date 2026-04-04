# Task 21: Google Tasks Integration - Analysis & Requirements

## Objective
Add Google Tasks as a tool integration in mcp-toolbox, exposing task list management and task CRUD/ordering capabilities as MCP tools for LLM clients.

---

## API Technical Details

### Google Tasks API v1 -- REST
- **Base URL:** `https://tasks.googleapis.com/tasks/v1`
- **Auth:** Google Service Account with JSON key file + domain-wide delegation. Use `google-auth` library (`google.oauth2.service_account.Credentials`) to acquire OAuth 2.0 access tokens with delegation to a target user. Token passed as `Authorization: Bearer <access_token>` header.
- **Scopes:** `https://www.googleapis.com/auth/tasks` (full read/write access to tasks and task lists)
- **Format:** JSON request/response
- **API Version:** v1 (stable, current)

### Authentication Flow
1. Load service account credentials from JSON key file via `google.oauth2.service_account.Credentials.from_service_account_file()`
2. Scope the credentials to `https://www.googleapis.com/auth/tasks`
3. **Apply domain-wide delegation** via `credentials.with_subject(GTASKS_DELEGATED_USER)` -- this is required because the Tasks API is a per-user API (unlike Sheets which operates on shared documents). The service account must impersonate a real user to access their task lists.
4. Call `credentials.refresh(google.auth.transport.requests.Request())` to obtain/refresh the access token
5. Use `credentials.token` as the Bearer token in httpx request headers
6. Token auto-expires (typically 1 hour); refresh before each request if expired via `credentials.valid` check

**Why delegation is required:** Google Tasks is fundamentally a per-user service. There is no concept of "shared task lists" that a service account can own. Without delegation, the service account would only see its own empty task lists. Domain-wide delegation lets the service account act on behalf of a real Google Workspace user, accessing their personal tasks.

**Prerequisite:** The Google Workspace admin must grant the service account domain-wide delegation authority in the Admin Console (Security > API Controls > Domain-wide Delegation) with the scope `https://www.googleapis.com/auth/tasks`.

### Rate Limits

| Metric | Limit |
|--------|-------|
| Queries per day | 50,000 per project |
| Queries per minute per user | 500 |

- HTTP 429 on exceed -- use exponential backoff; quota refills per minute for per-user limits
- HTTP 403 with `rateLimitExceeded` reason also indicates quota breach
- No `Retry-After` header; implement client-side backoff

### REST Resources

The Tasks API v1 has 2 REST resources:

| Resource | Description |
|----------|-------------|
| `tasks.tasklists` | Task list operations (list, get, insert, update, delete, patch) |
| `tasks.tasks` | Task operations within a task list (list, get, insert, update, delete, patch, move, clear) |

### Key Quirks

- **RFC 3339 timestamps** -- All datetime fields (`due`, `updated`, `completed`) use RFC 3339 format (e.g., `2024-01-15T09:00:00.000Z`). The `due` field stores only the date portion; time is always `00:00:00.000Z` regardless of what you send.
- **Task status values** -- Only two statuses: `needsAction` (incomplete) and `completed`. Setting status to `completed` auto-populates the `completed` timestamp. Setting status back to `needsAction` clears the `completed` field.
- **Task ordering via position** -- Tasks have a `position` field (string, lexicographic ordering). Do NOT set this directly; use the `move` endpoint to reorder tasks.
- **Parent/child relationships** -- Tasks can be nested (indented) under other tasks via the `parent` field. A task's `parent` is the ID of its parent task (not task list). Maximum nesting depth is not documented but practically limited. Use the `move` endpoint with `parent` parameter to indent/outdent.
- **Move endpoint controls ordering AND nesting** -- `POST /lists/{tasklist}/tasks/{task}/move?parent={parentTask}&previous={previousTask}` is the only correct way to reorder or re-parent tasks. The `parent` param sets the parent task (omit to move to top level), and `previous` sets the sibling to insert after (omit to place first).
- **Task list limit** -- Users can have up to 2,000 task lists.
- **Tasks per list limit** -- Each task list can hold up to 100,000 tasks.
- **Default task list** -- Every user has a default task list with the special ID `@default`. This is the "My Tasks" list.
- **Hidden tasks** -- Completed tasks can be "hidden" (cleared). The `clear` endpoint hides all completed tasks in a list. Hidden tasks are still retrievable with `showHidden=true` parameter.
- **Deleted tasks** -- Deleted tasks remain accessible for a period with `showDeleted=true`. They have `deleted: true` flag.
- **No batch API** -- Unlike Sheets, there is no batch endpoint. Each operation is a separate HTTP request.
- **Patch vs Update** -- `PATCH` does partial update (only fields sent are modified); `PUT` does full replacement (missing fields are cleared). Both are useful.
- **ETag support** -- Resources include an `etag` field for optimistic concurrency. Can be sent in `If-Match` header for conditional updates, but this is optional.
- **Links field** -- Tasks have a `links` array containing contextual links (e.g., links to emails that generated the task). This is read-only and auto-populated by Google.
- **Notes field** -- The `notes` field contains the task description/body text. Plain text only, no formatting.
- **Service account sharing** -- Unlike Sheets, you cannot "share" tasks. Domain-wide delegation is the only mechanism for service account access.

---

## Google Tasks Object Model

```
User
  |-- TaskLists[] (up to 2,000)
  |     |-- id (string, auto-generated)
  |     |-- title (string)
  |     |-- updated (RFC 3339 datetime)
  |     |-- etag (string)
  |     |-- selfLink (URL)
  |     |-- kind ("tasks#taskList")
  |     |
  |     |-- Tasks[] (up to 100,000 per list)
  |           |-- id (string, auto-generated)
  |           |-- title (string)
  |           |-- notes (string, plain text body)
  |           |-- status ("needsAction" | "completed")
  |           |-- due (RFC 3339, date only)
  |           |-- completed (RFC 3339, auto-set when status=completed)
  |           |-- updated (RFC 3339, auto-updated)
  |           |-- parent (task ID of parent, or empty for top-level)
  |           |-- position (string, lexicographic sort key)
  |           |-- hidden (bool, true if cleared completed task)
  |           |-- deleted (bool, true if soft-deleted)
  |           |-- links[] (read-only contextual links)
  |           |-- etag (string)
  |           |-- selfLink (URL)
  |           |-- kind ("tasks#task")
```

---

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes | Path to service account JSON key file (reused from Sheets) |
| `GTASKS_DELEGATED_USER` | Yes | Email of the Google Workspace user to impersonate (e.g., `user@company.com`) |

### Config Module Addition (`config.py`)

```python
GTASKS_DELEGATED_USER: str | None = os.getenv("GTASKS_DELEGATED_USER")
```

`GOOGLE_SERVICE_ACCOUNT_JSON` is already exported from `config.py`.

---

## Tool Specifications

### Tier 1: Task List Operations (6 tools)

#### `gtasks_list_tasklists`
List all task lists for the delegated user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `max_results` | int | No | Maximum number of task lists to return (default: 20, max: 100) |
| `page_token` | str | No | Token for pagination |

**Returns:** Array of task list objects with `id`, `title`, `updated`.
**Endpoint:** `GET /users/@me/lists`
**Query params:** `maxResults`, `pageToken`

---

#### `gtasks_get_tasklist`
Get a specific task list by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | Yes | Task list ID (use `@default` for the default "My Tasks" list) |

**Returns:** Task list object with `id`, `title`, `updated`, `etag`.
**Endpoint:** `GET /users/@me/lists/{tasklist}`

---

#### `gtasks_insert_tasklist`
Create a new task list.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | str | Yes | Title for the new task list |

**Returns:** Created task list object with auto-generated `id`.
**Endpoint:** `POST /users/@me/lists`
**Body:**
```json
{
  "title": "My New List"
}
```

---

#### `gtasks_update_tasklist`
Full update of a task list (replaces all mutable fields).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | Yes | Task list ID |
| `title` | str | Yes | New title for the task list |

**Returns:** Updated task list object.
**Endpoint:** `PUT /users/@me/lists/{tasklist}`
**Body:**
```json
{
  "title": "Updated Title"
}
```

---

#### `gtasks_patch_tasklist`
Partial update of a task list (only sent fields are modified).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | Yes | Task list ID |
| `title` | str | No | New title (only field that can be patched) |

**Returns:** Updated task list object.
**Endpoint:** `PATCH /users/@me/lists/{tasklist}`
**Body:**
```json
{
  "title": "Patched Title"
}
```

**Note:** For task lists, `patch` and `update` are effectively identical since `title` is the only mutable field. Both are included for API completeness.

---

#### `gtasks_delete_tasklist`
Permanently delete a task list and all its tasks.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | Yes | Task list ID to delete |

**Returns:** Confirmation of deletion (HTTP 204 No Content).
**Endpoint:** `DELETE /users/@me/lists/{tasklist}`

**Warning:** This cannot be undone. All tasks within the list are also deleted.

---

### Tier 2: Task CRUD Operations (6 tools)

#### `gtasks_list_tasks`
List tasks in a task list.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | No | Task list ID (default: `@default`) |
| `max_results` | int | No | Maximum number of tasks to return (default: 20, max: 100) |
| `page_token` | str | No | Token for pagination |
| `due_min` | str | No | Lower bound for due date (RFC 3339, e.g., `2024-01-01T00:00:00Z`) |
| `due_max` | str | No | Upper bound for due date (RFC 3339) |
| `completed_min` | str | No | Lower bound for completion date (RFC 3339) |
| `completed_max` | str | No | Upper bound for completion date (RFC 3339) |
| `updated_min` | str | No | Lower bound for last modification date (RFC 3339) |
| `show_completed` | bool | No | Whether to show completed tasks (default: true) |
| `show_deleted` | bool | No | Whether to show deleted tasks (default: false) |
| `show_hidden` | bool | No | Whether to show hidden/cleared tasks (default: false) |

**Returns:** Array of task objects with pagination info.
**Endpoint:** `GET /lists/{tasklist}/tasks`
**Query params:** `maxResults`, `pageToken`, `dueMin`, `dueMax`, `completedMin`, `completedMax`, `updatedMin`, `showCompleted`, `showDeleted`, `showHidden`

---

#### `gtasks_get_task`
Get a specific task by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | No | Task list ID (default: `@default`) |
| `task_id` | str | Yes | Task ID |

**Returns:** Full task object.
**Endpoint:** `GET /lists/{tasklist}/tasks/{task}`

---

#### `gtasks_insert_task`
Create a new task in a task list.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | No | Task list ID (default: `@default`) |
| `title` | str | Yes | Task title |
| `notes` | str | No | Task description/body (plain text) |
| `due` | str | No | Due date in RFC 3339 format (only date portion is stored, e.g., `2024-01-15T00:00:00Z`) |
| `status` | str | No | Task status: `needsAction` (default) or `completed` |
| `parent` | str | No | Parent task ID to create as a subtask. Sets the task as a child of the specified task. |
| `previous` | str | No | Previous sibling task ID. Positions the new task after this sibling. |

**Returns:** Created task object with auto-generated `id`.
**Endpoint:** `POST /lists/{tasklist}/tasks`
**Query params:** `parent`, `previous` (these are query params, NOT body fields)
**Body:**
```json
{
  "title": "Buy groceries",
  "notes": "Milk, eggs, bread",
  "due": "2024-01-15T00:00:00.000Z",
  "status": "needsAction"
}
```

**Important:** The `parent` and `previous` parameters are passed as query parameters on the insert endpoint, NOT in the request body. This controls initial positioning of the new task.

---

#### `gtasks_update_task`
Full update of a task (replaces all mutable fields; unset fields are cleared).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | No | Task list ID (default: `@default`) |
| `task_id` | str | Yes | Task ID |
| `title` | str | Yes | Task title |
| `notes` | str | No | Task description (omit to clear) |
| `due` | str | No | Due date RFC 3339 (omit to clear) |
| `status` | str | No | `needsAction` or `completed` (default: `needsAction`) |

**Returns:** Updated task object.
**Endpoint:** `PUT /lists/{tasklist}/tasks/{task}`
**Body:**
```json
{
  "id": "task_id",
  "title": "Updated title",
  "notes": "Updated notes",
  "due": "2024-02-01T00:00:00.000Z",
  "status": "needsAction"
}
```

**Note:** The task `id` MUST be included in the request body for PUT. This is a full replacement -- omitted optional fields will be cleared.

---

#### `gtasks_patch_task`
Partial update of a task (only sent fields are modified; omitted fields are untouched).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | No | Task list ID (default: `@default`) |
| `task_id` | str | Yes | Task ID |
| `title` | str | No | Task title |
| `notes` | str | No | Task description |
| `due` | str | No | Due date RFC 3339 |
| `status` | str | No | `needsAction` or `completed` |

**Returns:** Updated task object.
**Endpoint:** `PATCH /lists/{tasklist}/tasks/{task}`
**Body:** Only include fields to change:
```json
{
  "status": "completed"
}
```

**Note:** This is the preferred method for toggling task completion or updating individual fields without affecting others.

---

#### `gtasks_delete_task`
Delete a task from a task list.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | No | Task list ID (default: `@default`) |
| `task_id` | str | Yes | Task ID to delete |

**Returns:** Confirmation of deletion (HTTP 204 No Content).
**Endpoint:** `DELETE /lists/{tasklist}/tasks/{task}`

---

### Tier 3: Task Ordering & Bulk Operations (2 tools)

#### `gtasks_move_task`
Move a task to a different position and/or change its parent (indent/outdent).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | No | Task list ID (default: `@default`) |
| `task_id` | str | Yes | Task ID to move |
| `parent` | str | No | New parent task ID. Omit or empty string to move to top level (outdent). |
| `previous` | str | No | Task ID of the sibling to place after. Omit to place first among siblings. |

**Returns:** Updated task object with new `position` and `parent` values.
**Endpoint:** `POST /lists/{tasklist}/tasks/{task}/move`
**Query params:** `parent`, `previous`
**Body:** Empty (all params are query parameters)

**Use cases:**
- **Reorder:** Move task after a specific sibling: `move(task_id, previous=sibling_id)`
- **Indent:** Make task a subtask: `move(task_id, parent=parent_task_id)`
- **Outdent:** Move subtask to top level: `move(task_id)` (omit parent)
- **Move to first position:** `move(task_id, parent=parent_id)` (omit previous)

---

#### `gtasks_clear_tasks`
Clear (hide) all completed tasks from a task list. Completed tasks are hidden from the default view but remain accessible with `show_hidden=true` in `gtasks_list_tasks`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist_id` | str | No | Task list ID (default: `@default`) |

**Returns:** Confirmation of success (HTTP 204 No Content).
**Endpoint:** `POST /lists/{tasklist}/clear`
**Body:** Empty

**Note:** This does NOT delete completed tasks. It hides them. They can still be retrieved with `show_hidden=true`.

---

## Tool Count Summary

| Tier | Resource | Tools | Names |
|------|----------|-------|-------|
| Tier 1 | Task Lists | 6 | `gtasks_list_tasklists`, `gtasks_get_tasklist`, `gtasks_insert_tasklist`, `gtasks_update_tasklist`, `gtasks_patch_tasklist`, `gtasks_delete_tasklist` |
| Tier 2 | Tasks CRUD | 6 | `gtasks_list_tasks`, `gtasks_get_task`, `gtasks_insert_task`, `gtasks_update_task`, `gtasks_patch_task`, `gtasks_delete_task` |
| Tier 3 | Ordering & Bulk | 2 | `gtasks_move_task`, `gtasks_clear_tasks` |
| **Total** | | **14** | |

---

## Architecture Decisions

### 1. File Location
`src/mcp_toolbox/tools/gtasks_tool.py` -- follows naming convention (`{integration}_tool.py`). Prefixed `g` to distinguish from potential generic "tasks" integrations.

### 2. Auth: Service Account with Domain-Wide Delegation
- Reuse `GOOGLE_SERVICE_ACCOUNT_JSON` from Sheets integration (same key file).
- Add `GTASKS_DELEGATED_USER` as a new required config variable. Unlike Sheets (which operates on shared documents the service account is invited to), Tasks is inherently per-user and requires impersonation.
- Use `credentials.with_subject(email)` to create delegated credentials. This returns a new Credentials instance scoped to the target user.
- Maintain a separate `_credentials` singleton for Tasks (different scope and subject than Sheets).

### 3. HTTP Client Pattern
Follow the exact `sheets_tool.py` pattern:
- Module-level `_credentials` and `_client` singletons
- `_get_token()` synchronous function (imports google.auth lazily)
- `_get_client()` async wrapper using `asyncio.to_thread(_get_token)`
- `_req()` async helper for all HTTP calls with error handling
- Singleton `httpx.AsyncClient` with `base_url="https://tasks.googleapis.com/tasks/v1"`

### 4. Default Task List
- All task endpoints accept optional `tasklist_id` parameter defaulting to `@default`
- Task list endpoints that require an ID (get, update, patch, delete) keep it required -- no sensible default for "which list to delete"
- Helper function: `_tlid(tasklist_id: str | None) -> str` returns the ID or `"@default"`

### 5. Response Format
Follow `_success()` pattern from sheets_tool.py:
```python
def _success(sc: int, **kw) -> str:
    return json.dumps({"status": "success", "status_code": sc, **kw})
```

For 204 No Content responses (delete, clear): return `_success(204, message="...")`.

### 6. Error Handling
Same as sheets_tool.py:
- HTTP 429 -> `ToolError("Google Tasks rate limit exceeded.")`
- HTTP 4xx/5xx -> `ToolError(f"Google Tasks error ({status_code}): {message}")`
- Parse error JSON `response.json().get("error", {}).get("message")` for readable errors

### 7. Patch vs Update
Both are included because they serve different purposes:
- **Update (PUT):** Full replacement. Use when you want to set the complete state of a task.
- **Patch (PATCH):** Partial update. Use when you want to change one field (e.g., mark complete) without touching others.

The LLM caller benefits from having both options to avoid accidentally clearing fields.

### 8. Query Params for Insert/Move
The `insert` and `move` endpoints use query parameters for `parent` and `previous` (not body fields). The `_req()` helper already supports `params` dict, so this works naturally.

### 9. No Batch Support
Unlike Sheets (which has batchUpdate), Tasks API has no batch endpoint. Each operation is a separate HTTP call. This is acceptable given the API's rate limits (500/min/user).

### 10. Pyright Compatibility
The `google.oauth2` and `google.auth` packages have type stubs via `google-auth-stubs` or inline types. The same approach as sheets_tool.py should work. If pyright issues arise, exclude the file in pyright config as done for other Google integrations.

### 11. Dependencies
No new dependencies. Reuses:
- `httpx` (already installed)
- `google-auth[requests]` (already installed for Sheets)

### 12. Registration
Add to `tools/__init__.py` `register_all_tools()`:
```python
from .gtasks_tool import register_tools as register_gtasks_tools
register_gtasks_tools(mcp)
```

---

## Testing Strategy

### Unit Tests (`tests/test_gtasks_tool.py`)
- Mock `_get_token()` to return a fake token (avoid real auth)
- Mock `httpx.AsyncClient.request` to return canned responses
- Test all 14 tools with valid inputs
- Test default `@default` task list fallback
- Test error handling (429, 404, 500)
- Test `parent`/`previous` query params on insert and move
- Test that PATCH sends partial body vs PUT sends full body

### Test Coverage Targets
- All 14 tools exercised with happy-path inputs
- Error paths: missing config, rate limit, API errors
- Edge cases: empty task list, `@default` shortcut, RFC 3339 date formatting

---

## Implementation Checklist

1. Add `GTASKS_DELEGATED_USER` to `config.py`
2. Create `src/mcp_toolbox/tools/gtasks_tool.py` with:
   - Auth helpers (`_get_token`, `_get_client`, `_req`, `_success`, `_tlid`)
   - `register_tools(mcp)` function
   - All 14 tools in 3 tiers
3. Register in `tools/__init__.py`
4. Create `tests/test_gtasks_tool.py`
5. Run `uv run pytest` -- all tests pass
6. Run `uv run ruff check src/tests/` -- no lint errors
7. Run `uv run pyright src/` -- clean (or exclude file if needed)
8. Update `CLAUDE.md` with Google Tasks entry
