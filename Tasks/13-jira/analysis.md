# Task 13: Jira Integration - Analysis & Requirements

## Objective
Add Jira Cloud as a tool integration in mcp-toolbox, exposing issue tracking, project management, agile boards, and sprint capabilities as MCP tools for LLM clients.

---

## API Technical Details

### Jira Cloud Platform REST API v3
- **Base URL:** `https://{your-domain}.atlassian.net/rest/api/3` (platform API)
- **Agile Base URL:** `https://{your-domain}.atlassian.net/rest/agile/1.0` (Jira Software / agile API)
- **Auth:** Basic Authentication — `Authorization: Basic base64(email:api_token)`
- **Format:** JSON request/response
- **ADF:** API v3 uses Atlassian Document Format (ADF) for rich text fields (comments, worklogs, descriptions). For simplicity, tools will accept plain text and convert to minimal ADF structures internally.

### Rate Limits

Jira Cloud enforces three independent rate limiting systems:

| Limit Type | Description |
|------------|-------------|
| **Points-based quota (per-hour)** | Each API call consumes points based on complexity. Base cost: 1 point per request, plus additional points per object involved. Enforced per-app per-tenant. |
| **Burst rate limits (per-second)** | Controls requests per second to a given endpoint per tenant. Short-term spike safeguard. |
| **Per-issue write limits** | Restricts how frequently a single issue can be modified. |

- HTTP 429 `Too Many Requests` on exceed
- Response header: `Retry-After` (seconds to wait)
- Response header: `X-RateLimit-NearLimit` (approaching limit warning)
- Points-based quota enforcement began phased rollout March 2, 2026

### Key Quirks
- **Two separate APIs** — Platform API (`/rest/api/3/`) for issues, projects, users, etc. Agile API (`/rest/agile/1.0/`) for boards, sprints, epics. Same authentication, different base paths.
- **Atlassian Document Format (ADF)** — v3 uses ADF for rich text (comments, descriptions, worklogs). Plain text must be wrapped in ADF structure: `{"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "..."}]}]}`
- **JQL for search** — Issue search uses Jira Query Language, a SQL-like syntax (e.g., `project = PROJ AND status = "In Progress"`). The legacy `/rest/api/3/search` endpoint has been removed; use `/rest/api/3/search/jql` instead, which uses `nextPageToken` pagination rather than `startAt`/`maxResults` offset-based pagination.
- **Pagination** — Most list endpoints use `startAt` + `maxResults` pattern (default 50, max varies by endpoint — typically 50-100)
- **Issue key vs ID** — Issues have both a numeric `id` and a human-readable `key` (e.g., `PROJ-123`). Most endpoints accept either.
- **Transitions are workflow-dependent** — Available transitions depend on the issue's current status and the project's workflow configuration. Must query available transitions before transitioning.
- **Attachment upload** — Uses `multipart/form-data` with `X-Atlassian-Token: no-check` header
- **Account IDs** — Jira Cloud uses `accountId` (not username) for user identification

---

## Tool Specifications

### Tier 1: Issue Management (15 tools)

#### `jira_create_issue`
Create a new issue in a project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_key` | str | Yes | Project key (e.g., `PROJ`) |
| `summary` | str | Yes | Issue summary/title |
| `issue_type` | str | Yes | Issue type name (e.g., `Task`, `Bug`, `Story`, `Epic`) |
| `description` | str | No | Issue description (plain text, converted to ADF) |
| `assignee_account_id` | str | No | Assignee account ID |
| `priority` | str | No | Priority name (e.g., `High`, `Medium`, `Low`) |
| `labels` | list[str] | No | Labels to apply |
| `components` | list[str] | No | Component names |
| `due_date` | str | No | Due date in `YYYY-MM-DD` format |
| `parent_key` | str | No | Parent issue key (for subtasks or child issues) |
| `custom_fields` | dict | No | Custom fields as `{field_id: value}` pairs |

**Returns:** Created issue with key, ID, self URL.
**Endpoint:** `POST /rest/api/3/issue`

#### `jira_get_issue`
Get full issue details by key or ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key (e.g., `PROJ-123`) or numeric ID |
| `fields` | str | No | Comma-separated field names to return (default: all) |
| `expand` | str | No | Comma-separated expansions (e.g., `changelog`, `renderedFields`, `transitions`) |

**Returns:** Full issue object with all requested fields.
**Endpoint:** `GET /rest/api/3/issue/{issueIdOrKey}`

#### `jira_update_issue`
Update issue fields.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `summary` | str | No | New summary |
| `description` | str | No | New description (plain text, converted to ADF) |
| `assignee_account_id` | str | No | New assignee account ID (empty string to unassign) |
| `priority` | str | No | New priority name |
| `labels` | list[str] | No | Replace labels |
| `components` | list[str] | No | Replace components |
| `due_date` | str | No | New due date (`YYYY-MM-DD`) or empty string to clear |
| `custom_fields` | dict | No | Custom fields as `{field_id: value}` pairs |

**Returns:** Confirmation (204 No Content on success).
**Endpoint:** `PUT /rest/api/3/issue/{issueIdOrKey}`

#### `jira_delete_issue`
Delete an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `delete_subtasks` | bool | No | Also delete subtasks (default false) |

**Returns:** Confirmation of deletion.
**Endpoint:** `DELETE /rest/api/3/issue/{issueIdOrKey}?deleteSubtasks={true|false}`

#### `jira_search_issues`
Search for issues using JQL.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `jql` | str | Yes | JQL query string (e.g., `project = PROJ AND status = "To Do"`) |
| `fields` | list[str] | No | List of field names to return |
| `max_results` | int | No | Maximum results to return (default 50, max 100) |
| `next_page_token` | str | No | Page token from previous response (for pagination) |

**Returns:** List of matching issues with pagination info (`nextPageToken` for next page).
**Endpoint:** `POST /rest/api/3/search/jql` (the older `/rest/api/3/search` has been removed; this is the current replacement)

#### `jira_transition_issue`
Transition an issue to a new status (change workflow state).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `transition_id` | str | Yes | Transition ID (obtain from `jira_get_transitions`) |
| `comment` | str | No | Comment to add during transition (plain text, converted to ADF) |
| `resolution` | str | No | Resolution name (e.g., `Done`, `Won't Do`) — required for some transitions |

**Returns:** Confirmation (204 No Content on success).
**Endpoint:** `POST /rest/api/3/issue/{issueIdOrKey}/transitions`

#### `jira_assign_issue`
Assign an issue to a user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `account_id` | str | Yes | Assignee account ID (use `-1` or `null` to unassign) |

**Returns:** Confirmation (204 No Content on success).
**Endpoint:** `PUT /rest/api/3/issue/{issueIdOrKey}/assignee`

#### `jira_add_comment`
Add a comment to an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `body` | str | Yes | Comment text (plain text, converted to ADF) |
| `visibility_type` | str | No | Visibility type: `role` or `group` |
| `visibility_value` | str | No | Role name or group name for restricted visibility |

**Returns:** Created comment with ID, author, body, timestamps.
**Endpoint:** `POST /rest/api/3/issue/{issueIdOrKey}/comment`

#### `jira_get_comments`
List comments on an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `start_at` | int | No | Index of first result (default 0) |
| `max_results` | int | No | Maximum results (default 50) |
| `order_by` | str | No | Sort order: `created` (default), `-created` (descending) |

**Returns:** List of comments with IDs, authors, bodies, timestamps.
**Endpoint:** `GET /rest/api/3/issue/{issueIdOrKey}/comment`

#### `jira_update_comment`
Update an existing comment on an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `comment_id` | str | Yes | Comment ID to update |
| `body` | str | Yes | New comment text (plain text, converted to ADF) |

**Returns:** Updated comment with ID, author, body, timestamps.
**Endpoint:** `PUT /rest/api/3/issue/{issueIdOrKey}/comment/{id}`

#### `jira_delete_comment`
Delete a comment from an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `comment_id` | str | Yes | Comment ID to delete |

**Returns:** Confirmation of deletion.
**Endpoint:** `DELETE /rest/api/3/issue/{issueIdOrKey}/comment/{id}`

#### `jira_add_attachment`
Add an attachment to an issue. Accepts a file path on the local filesystem.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `file_path` | str | Yes | Absolute path to the file to attach |

**Returns:** List of created attachments with IDs, filenames, size, mime type.
**Endpoint:** `POST /rest/api/3/issue/{issueIdOrKey}/attachments` (multipart/form-data, requires `X-Atlassian-Token: no-check` header)

#### `jira_get_attachments`
List attachments on an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |

**Returns:** List of attachments with IDs, filenames, size, mime type, content URL.
**Endpoint:** Extracted from `GET /rest/api/3/issue/{issueIdOrKey}?fields=attachment` response.

#### `jira_delete_attachment`
Delete an attachment by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `attachment_id` | str | Yes | Attachment ID to delete |

**Returns:** Confirmation of deletion.
**Endpoint:** `DELETE /rest/api/3/attachment/{id}`

#### `jira_get_transitions`
List available transitions for an issue (what status changes are possible).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |

**Returns:** List of available transitions with IDs, names, target status.
**Endpoint:** `GET /rest/api/3/issue/{issueIdOrKey}/transitions`

---

### Tier 2: Project Management (2 tools)

#### `jira_list_projects`
List accessible projects.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `start_at` | int | No | Index of first result (default 0) |
| `max_results` | int | No | Maximum results (default 50) |
| `query` | str | No | Filter projects by name (contains match) |
| `order_by` | str | No | Order by field (e.g., `name`, `-name`, `key`) |

**Returns:** List of projects with keys, names, IDs, lead, project type.
**Endpoint:** `GET /rest/api/3/project/search`

#### `jira_get_project`
Get project details.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_key` | str | Yes | Project key or numeric ID |
| `expand` | str | No | Comma-separated expansions (e.g., `description`, `lead`, `issueTypes`) |

**Returns:** Project details including key, name, description, lead, issue types, roles.
**Endpoint:** `GET /rest/api/3/project/{projectIdOrKey}`

---

### Tier 3: Agile — Boards (3 tools)

> These use the Jira Software Agile REST API at `/rest/agile/1.0/`.

#### `jira_list_boards`
List all boards visible to the user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `start_at` | int | No | Index of first result (default 0) |
| `max_results` | int | No | Maximum results (default 50) |
| `type` | str | No | Board type filter: `scrum`, `kanban`, `simple` |
| `name` | str | No | Filter by board name (contains match) |
| `project_key` | str | No | Filter boards by project key |

**Returns:** List of boards with IDs, names, types, project location.
**Endpoint:** `GET /rest/agile/1.0/board`

#### `jira_get_board`
Get board details by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `board_id` | int | Yes | Board ID |

**Returns:** Board details including ID, name, type, project location.
**Endpoint:** `GET /rest/agile/1.0/board/{boardId}`

#### `jira_get_board_issues`
Get issues on a board.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `board_id` | int | Yes | Board ID |
| `start_at` | int | No | Index of first result (default 0) |
| `max_results` | int | No | Maximum results (default 50) |
| `jql` | str | No | Additional JQL filter |
| `fields` | str | No | Comma-separated field names to return |

**Returns:** List of issues on the board with agile fields (sprint, rank, flagged).
**Endpoint:** `GET /rest/agile/1.0/board/{boardId}/issue`

---

### Tier 4: Agile — Sprints (4 tools)

#### `jira_list_sprints`
List sprints for a board.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `board_id` | int | Yes | Board ID |
| `start_at` | int | No | Index of first result (default 0) |
| `max_results` | int | No | Maximum results (default 50) |
| `state` | str | No | Filter by state: `future`, `active`, `closed` |

**Returns:** List of sprints with IDs, names, states, start/end dates, goal.
**Endpoint:** `GET /rest/agile/1.0/board/{boardId}/sprint`

#### `jira_get_sprint`
Get sprint details by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sprint_id` | int | Yes | Sprint ID |

**Returns:** Sprint details including ID, name, state, start/end/complete dates, goal.
**Endpoint:** `GET /rest/agile/1.0/sprint/{sprintId}`

#### `jira_get_sprint_issues`
Get issues in a sprint.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sprint_id` | int | Yes | Sprint ID |
| `start_at` | int | No | Index of first result (default 0) |
| `max_results` | int | No | Maximum results (default 50) |
| `jql` | str | No | Additional JQL filter |
| `fields` | str | No | Comma-separated field names to return |

**Returns:** List of issues in the sprint with agile fields.
**Endpoint:** `GET /rest/agile/1.0/sprint/{sprintId}/issue`

#### `jira_move_issues_to_sprint`
Move one or more issues to a sprint.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sprint_id` | int | Yes | Target sprint ID |
| `issue_keys` | list[str] | Yes | List of issue keys or IDs to move |

**Returns:** Confirmation (204 No Content on success).
**Endpoint:** `POST /rest/agile/1.0/sprint/{sprintId}/issue`

---

### Tier 5: Users (2 tools)

#### `jira_search_users`
Search for users by query string.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | Yes | Search string (matches display name, email) |
| `start_at` | int | No | Index of first result (default 0) |
| `max_results` | int | No | Maximum results (default 50) |

**Returns:** List of users with account IDs, display names, email addresses, avatars, active status.
**Endpoint:** `GET /rest/api/3/user/search?query={query}`

#### `jira_get_user`
Get user details by account ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `account_id` | str | Yes | User account ID |

**Returns:** User details including account ID, display name, email, avatars, active status, timezone.
**Endpoint:** `GET /rest/api/3/user?accountId={accountId}`

---

### Tier 6: Metadata — Priorities & Statuses (2 tools)

#### `jira_list_priorities`
List all issue priorities.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | | | Returns all configured priorities |

**Returns:** List of priorities with IDs, names, descriptions, icon URLs, sort order.
**Endpoint:** `GET /rest/api/3/priority/search`

#### `jira_list_statuses`
List statuses, optionally filtered by project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_id` | str | No | Filter statuses by numeric project ID (note: this endpoint requires `projectId`, not project key) |
| `start_at` | int | No | Index of first result (default 0) |
| `max_results` | int | No | Maximum results (default 200) |

**Returns:** List of statuses with IDs, names, status categories, scope.
**Endpoint:** `GET /rest/api/3/statuses/search`

---

### Tier 7: Worklogs (4 tools)

#### `jira_add_worklog`
Add a worklog entry to an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `time_spent` | str | Yes | Time in Jira duration format (e.g., `2h 30m`, `1d`, `45m`) |
| `comment` | str | No | Worklog comment (plain text, converted to ADF) |
| `started` | str | No | When work started, ISO datetime (default: now) |

**Returns:** Created worklog with ID, author, time spent, started timestamp.
**Endpoint:** `POST /rest/api/3/issue/{issueIdOrKey}/worklog`

#### `jira_get_worklogs`
List worklogs on an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `start_at` | int | No | Index of first result (default 0) |
| `max_results` | int | No | Maximum results (default 5000) |

**Returns:** List of worklogs with IDs, authors, time spent, comments, timestamps.
**Endpoint:** `GET /rest/api/3/issue/{issueIdOrKey}/worklog`

#### `jira_update_worklog`
Update an existing worklog entry on an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `worklog_id` | str | Yes | Worklog ID to update |
| `time_spent` | str | No | Time in Jira duration format (e.g., `2h 30m`) |
| `started` | str | No | When work started, ISO datetime |
| `comment` | str | No | Worklog comment (plain text, converted to ADF) |

**Returns:** Updated worklog with ID, author, time spent, started timestamp.
**Endpoint:** `PUT /rest/api/3/issue/{issueIdOrKey}/worklog/{id}`

#### `jira_delete_worklog`
Delete a worklog entry from an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `worklog_id` | str | Yes | Worklog ID to delete |

**Returns:** Confirmation of deletion.
**Endpoint:** `DELETE /rest/api/3/issue/{issueIdOrKey}/worklog/{id}`

---

### Tier 8: Watchers (3 tools)

#### `jira_get_watchers`
Get the list of watchers for an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |

**Returns:** List of watchers with account IDs, display names, active status.
**Endpoint:** `GET /rest/api/3/issue/{issueIdOrKey}/watchers`

#### `jira_add_watcher`
Add a user as a watcher on an issue.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `account_id` | str | Yes | User account ID to add as watcher |

**Returns:** Confirmation (204 No Content on success).
**Endpoint:** `POST /rest/api/3/issue/{issueIdOrKey}/watchers`

#### `jira_remove_watcher`
Remove a user from an issue's watcher list.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issue_key` | str | Yes | Issue key or ID |
| `account_id` | str | Yes | User account ID to remove from watchers |

**Returns:** Confirmation (204 No Content on success).
**Endpoint:** `DELETE /rest/api/3/issue/{issueIdOrKey}/watchers?accountId={accountId}`

---

### Tier 9: Issue Links (3 tools)

#### `jira_create_issue_link`
Create a link between two issues.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `type_name` | str | Yes | Link type name (e.g., `Blocks`, `Duplicates`, `Relates`) |
| `inward_issue_key` | str | Yes | Inward issue key (e.g., `PROJ-123`) |
| `outward_issue_key` | str | Yes | Outward issue key (e.g., `PROJ-456`) |

**Returns:** Confirmation (201 Created on success).
**Endpoint:** `POST /rest/api/3/issueLink`

#### `jira_delete_issue_link`
Delete an issue link by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `link_id` | str | Yes | Issue link ID to delete |

**Returns:** Confirmation of deletion.
**Endpoint:** `DELETE /rest/api/3/issueLink/{linkId}`

#### `jira_list_issue_link_types`
List all available issue link types.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | | | Returns all configured issue link types |

**Returns:** List of issue link types with IDs, names, inward/outward descriptions.
**Endpoint:** `GET /rest/api/3/issueLinkType`

---

### Tier 10: Components (2 tools)

#### `jira_list_components`
List components for a project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_key` | str | Yes | Project key or numeric ID |

**Returns:** List of components with IDs, names, descriptions, leads, assignee types.
**Endpoint:** `GET /rest/api/3/project/{projectIdOrKey}/component`

#### `jira_create_component`
Create a new component in a project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_key` | str | Yes | Project key (sent in body as `project`) |
| `name` | str | Yes | Component name |
| `description` | str | No | Component description |
| `lead_account_id` | str | No | Account ID of the component lead |

**Returns:** Created component with ID, name, description, lead.
**Endpoint:** `POST /rest/api/3/component`

---

### Tier 11: Versions (2 tools)

#### `jira_list_versions`
List versions (releases) for a project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_key` | str | Yes | Project key or numeric ID |

**Returns:** List of versions with IDs, names, descriptions, release dates, released status.
**Endpoint:** `GET /rest/api/3/project/{projectIdOrKey}/versions`

#### `jira_create_version`
Create a new version (release) in a project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_id` | str | Yes | Numeric project ID |
| `name` | str | Yes | Version name |
| `description` | str | No | Version description |
| `start_date` | str | No | Start date in `YYYY-MM-DD` format |
| `release_date` | str | No | Release date in `YYYY-MM-DD` format |
| `released` | bool | No | Whether the version is released |

**Returns:** Created version with ID, name, description, dates, released status.
**Endpoint:** `POST /rest/api/3/version`

---

### Tier 12: Labels (1 tool)

#### `jira_list_labels`
List all labels used across the Jira instance.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `start_at` | int | No | Index of first result (default 0) |
| `max_results` | int | No | Maximum results (default 50) |

**Returns:** List of label strings with pagination info.
**Endpoint:** `GET /rest/api/3/label`

---

### Tier 13: Bulk Operations (1 tool)

#### `jira_bulk_create_issues`
Create multiple issues in a single request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `issues` | list[dict] | Yes | List of issue create payloads (each following the same structure as `jira_create_issue`) |

**Returns:** List of created issues with keys, IDs, self URLs; list of any errors.
**Endpoint:** `POST /rest/api/3/issue/bulk`

---

## Architecture Decisions

### A1: Direct HTTP with httpx (no SDK)
There is no official Jira Python SDK for REST API v3 Cloud. The `jira` PyPI package targets Server/DC and has incomplete Cloud v3 support. **Recommendation:** Use `httpx` (already a project dependency) for direct async HTTP calls, consistent with the ClickUp integration pattern.

### A2: Shared httpx Client with Basic Auth
Create a shared `httpx.AsyncClient` with Basic auth (email:token) configured. Since Jira uses two base URLs (platform and agile), the client will use the domain as base and construct full paths.

```python
import base64
import httpx

_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    if not JIRA_BASE_URL or not JIRA_EMAIL or not JIRA_API_TOKEN:
        raise ToolError(
            "Jira configuration incomplete. Set JIRA_BASE_URL, "
            "JIRA_EMAIL, and JIRA_API_TOKEN in your environment or .env file."
        )
    global _client
    if _client is None:
        credentials = base64.b64encode(
            f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()
        ).decode()
        _client = httpx.AsyncClient(
            base_url=JIRA_BASE_URL.rstrip("/"),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    return _client
```

**Lifecycle:** Same as ClickUp — process-scoped `AsyncClient`, cleaned up on exit. Acceptable for STDIO transport.

### A3: Two API Base Paths
Platform API endpoints use `/rest/api/3/...` and Agile API endpoints use `/rest/agile/1.0/...`. The `JIRA_BASE_URL` will be set to the instance root (e.g., `https://mycompany.atlassian.net`), and each request helper will construct the full path. Two internal helpers:

```python
async def _api_request(method: str, path: str, **kwargs):
    """Platform API request — path relative to /rest/api/3/"""
    return await _request(method, f"/rest/api/3/{path.lstrip('/')}", **kwargs)

async def _agile_request(method: str, path: str, **kwargs):
    """Agile API request — path relative to /rest/agile/1.0/"""
    return await _request(method, f"/rest/agile/1.0/{path.lstrip('/')}", **kwargs)
```

### A4: ADF Helper
Since API v3 requires Atlassian Document Format for rich text fields, provide a helper to wrap plain text:

```python
def _to_adf(text: str) -> dict:
    """Convert plain text to minimal ADF document."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }
```

### A5: Tool Naming Convention
All Jira tools prefixed with `jira_` to distinguish from other integrations.

### A6: Error Handling
Same pattern as ClickUp: catch `httpx` exceptions, convert to `ToolError` with human-readable messages. 429 responses include `Retry-After` header value in the error message. No automatic retry.

### A7: Pagination
Tools return a single page of results. Callers can paginate via `start_at` and `max_results` parameters. No auto-pagination to keep response sizes bounded.

### A8: Response Format
Consistent JSON convention: `{"status": "success", ...}` or `{"status": "error", ...}`.

### A9: Missing Config Strategy
Same as ClickUp: register all tools regardless of configuration. Fail at invocation time with a clear `ToolError` if any of the three required config values are missing.

---

## Configuration Requirements

### Environment Variables

| Variable | Description | Required | Example |
|----------|-------------|----------|---------|
| `JIRA_BASE_URL` | Jira Cloud instance URL | Yes (at invocation) | `https://mycompany.atlassian.net` |
| `JIRA_EMAIL` | Atlassian account email for Basic auth | Yes (at invocation) | `user@company.com` |
| `JIRA_API_TOKEN` | Atlassian API token (generated at id.atlassian.com) | Yes (at invocation) | `ATATT3x...` |

### Config Pattern
```python
JIRA_BASE_URL: str | None = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL: str | None = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN: str | None = os.getenv("JIRA_API_TOKEN")
```

### Authentication Flow
1. User generates API token at `https://id.atlassian.com/manage-profile/security/api-tokens`
2. Token is combined with email as `email:token`
3. Base64-encoded and sent as `Authorization: Basic {encoded}` header
4. httpx `AsyncClient` is configured once with this header

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/config.py` | Modify | Add `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` |
| `.env.example` | Modify | Add Jira variables with descriptions |
| `src/mcp_toolbox/tools/jira_tool.py` | **New** | All Jira tools (platform + agile) |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register jira_tool |
| `tests/test_jira_tool.py` | **New** | Tests for all Jira tools |
| `CLAUDE.md` | Modify | Document Jira integration |

---

## Dependencies

| Package | Purpose | Already in project? |
|---------|---------|-------------------|
| `httpx` | Async HTTP client | Yes |
| `respx` | httpx mock library (dev) | Yes (added for ClickUp) |

No new runtime dependencies required.

---

## Testing Strategy

### Approach
Use `pytest` with `respx` for mocking HTTP calls, consistent with ClickUp test patterns.

```python
import respx

@respx.mock
async def test_create_issue():
    respx.post("https://mycompany.atlassian.net/rest/api/3/issue").mock(
        return_value=httpx.Response(201, json={
            "id": "10001", "key": "PROJ-1", "self": "https://..."
        })
    )
    result = await server.call_tool("jira_create_issue", {...})
    assert "PROJ-1" in result
```

### Test Coverage
1. Happy path for every tool (44 tools)
2. Missing configuration (any of JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN) raises ToolError
3. API errors: 401 Unauthorized, 403 Forbidden, 404 Not Found, 429 Rate Limited
4. ADF conversion helper
5. Pagination parameter forwarding
6. Multipart attachment upload

---

## Success Criteria

1. `uv sync` installs without errors (no new runtime deps needed)
2. All **44 Jira tools** register and are discoverable via MCP Inspector
3. Tools return meaningful errors when any config variable is missing
4. All tools return consistent JSON responses (`{"status": "success", ...}`)
5. ADF helper correctly wraps plain text for comments, descriptions, and worklogs
6. Both Platform API and Agile API endpoints are correctly routed
7. New tests pass and full regression suite remains green
8. Total toolbox tool count reaches **268** (224 existing + 44 new)

---

## Tool Summary (44 tools total)

### Tier 1 — Issue Management (15 tools)
1. `jira_create_issue` — Create a new issue with summary, type, description, assignee, priority, labels
2. `jira_get_issue` — Get full issue details by key or ID
3. `jira_update_issue` — Update issue fields (summary, description, assignee, priority, labels, etc.)
4. `jira_delete_issue` — Delete an issue, optionally with subtasks
5. `jira_search_issues` — Search issues using JQL with token-based pagination
6. `jira_transition_issue` — Change issue status via workflow transition
7. `jira_assign_issue` — Assign or unassign an issue
8. `jira_add_comment` — Add a comment to an issue
9. `jira_get_comments` — List comments on an issue
10. `jira_update_comment` — Update an existing comment on an issue
11. `jira_delete_comment` — Delete a comment from an issue
12. `jira_add_attachment` — Upload a file attachment to an issue
13. `jira_get_attachments` — List attachments on an issue
14. `jira_delete_attachment` — Delete an attachment by ID
15. `jira_get_transitions` — List available workflow transitions for an issue

### Tier 2 — Project Management (2 tools)
16. `jira_list_projects` — List accessible projects with search and pagination
17. `jira_get_project` — Get project details by key or ID

### Tier 3 — Agile: Boards (3 tools)
18. `jira_list_boards` — List boards with type, name, and project filters
19. `jira_get_board` — Get board details by ID
20. `jira_get_board_issues` — Get issues on a board with JQL filter

### Tier 4 — Agile: Sprints (4 tools)
21. `jira_list_sprints` — List sprints for a board with state filter
22. `jira_get_sprint` — Get sprint details by ID
23. `jira_get_sprint_issues` — Get issues in a sprint with JQL filter
24. `jira_move_issues_to_sprint` — Move issues to a target sprint

### Tier 5 — Users (2 tools)
25. `jira_search_users` — Search users by display name or email
26. `jira_get_user` — Get user details by account ID

### Tier 6 — Metadata (2 tools)
27. `jira_list_priorities` — List all configured issue priorities
28. `jira_list_statuses` — List statuses with optional project filter

### Tier 7 — Worklogs (4 tools)
29. `jira_add_worklog` — Log time spent on an issue
30. `jira_get_worklogs` — List worklog entries on an issue
31. `jira_update_worklog` — Update an existing worklog entry on an issue
32. `jira_delete_worklog` — Delete a worklog entry from an issue

### Tier 8 — Watchers (3 tools)
33. `jira_get_watchers` — Get the list of watchers for an issue
34. `jira_add_watcher` — Add a user as a watcher on an issue
35. `jira_remove_watcher` — Remove a user from an issue's watcher list

### Tier 9 — Issue Links (3 tools)
36. `jira_create_issue_link` — Create a link between two issues
37. `jira_delete_issue_link` — Delete an issue link by ID
38. `jira_list_issue_link_types` — List all available issue link types

### Tier 10 — Components (2 tools)
39. `jira_list_components` — List components for a project
40. `jira_create_component` — Create a new component in a project

### Tier 11 — Versions (2 tools)
41. `jira_list_versions` — List versions (releases) for a project
42. `jira_create_version` — Create a new version (release) in a project

### Tier 12 — Labels (1 tool)
43. `jira_list_labels` — List all labels used across the Jira instance

### Tier 13 — Bulk Operations (1 tool)
44. `jira_bulk_create_issues` — Create multiple issues in a single request
