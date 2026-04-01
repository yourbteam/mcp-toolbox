# Task 03: ClickUp Integration (All 4 Tiers) - Implementation Plan

## Overview
Implement 25 ClickUp tools across 4 tiers in 8 sequential steps. Uses `httpx` directly for native async HTTP — no SDK wrapping needed.

---

## Step 1: Dependencies & Configuration

### 1a. Add `respx` to dev dependencies in `pyproject.toml`
```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
    "pyright>=1.1.0",
    "respx>=0.21.0",
]
```

### 1b. Add ClickUp config to `src/mcp_toolbox/config.py`
Append after the SendGrid variables:
```python
# ClickUp
CLICKUP_API_TOKEN: str | None = os.getenv("CLICKUP_API_TOKEN")
CLICKUP_TEAM_ID: str | None = os.getenv("CLICKUP_TEAM_ID")
```

### 1c. Update `.env.example`
Append after SendGrid section:
```env
# ClickUp Integration
CLICKUP_API_TOKEN=pk_your-api-token-here
CLICKUP_TEAM_ID=your-workspace-id
```

### 1d. Run `uv sync`
```bash
uv sync --dev --all-extras
```

---

## Step 2: Tool Module Foundation

Create `src/mcp_toolbox/tools/clickup_tool.py` with shared infrastructure.

```python
"""ClickUp integration — project management, tasks, time tracking tools."""

import json
import logging
from datetime import datetime, timezone

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import CLICKUP_API_TOKEN, CLICKUP_TEAM_ID

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Get or create the httpx client. Raises ToolError if API token is missing."""
    global _client
    if not CLICKUP_API_TOKEN:
        raise ToolError(
            "CLICKUP_API_TOKEN is not configured. "
            "Set it in your environment or .env file."
        )
    if _client is None:
        _client = httpx.AsyncClient(
            base_url="https://api.clickup.com/api/v2",
            headers={"Authorization": CLICKUP_API_TOKEN},
            timeout=30.0,
        )
    return _client


def _get_team_id(override: str | None = None) -> str:
    """Resolve team/workspace ID: override > config > error."""
    team_id = override or CLICKUP_TEAM_ID
    if not team_id:
        raise ToolError(
            "No team_id provided. Either pass team_id or set "
            "CLICKUP_TEAM_ID in your environment."
        )
    return team_id


def _to_ms(value: str | int | None) -> int | None:
    """Convert ISO datetime or Unix seconds/ms to Unix milliseconds."""
    if value is None:
        return None
    if isinstance(value, int):
        # If it looks like seconds (before year 2100 in seconds), convert to ms
        if value < 10_000_000_000:
            return value * 1000
        return value
    # Parse ISO datetime string
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _success(status_code: int, **kwargs) -> str:
    """Build a success JSON response."""
    return json.dumps({"status": "success", "status_code": status_code, **kwargs})


async def _request(method: str, path: str, **kwargs) -> dict | list:
    """Make an authenticated ClickUp API request with error handling."""
    client = _get_client()
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"ClickUp API request failed: {e}") from e

    if response.status_code == 429:
        reset = response.headers.get("X-RateLimit-Reset", "unknown")
        raise ToolError(
            f"ClickUp rate limit exceeded. Resets at: {reset}. "
            "Try again after the reset time."
        )

    if response.status_code >= 400:
        try:
            error_body = response.json()
            error_msg = error_body.get("err", error_body.get("error", response.text))
        except Exception:
            error_msg = response.text
        raise ToolError(
            f"ClickUp API error ({response.status_code}): {error_msg}"
        )

    if response.status_code == 204:
        return {}

    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def register_tools(mcp: FastMCP) -> None:
    """Register all ClickUp tools with the MCP server."""

    if not CLICKUP_API_TOKEN:
        logger.warning(
            "CLICKUP_API_TOKEN not set — ClickUp tools will be registered "
            "but will fail at invocation until configured."
        )

    # --- Tier 1: Core Task Management ---
    # (Step 3)

    # --- Tier 2: Task Details ---
    # (Step 4)

    # --- Tier 3: Time Tracking ---
    # (Step 5)

    # --- Tier 4: Organizational ---
    # (Step 6)
```

Key design decisions:
- **`_request()` helper** centralizes HTTP calls, error parsing, and rate limit handling — every tool calls this instead of raw `client.get/post/put/delete`
- **`_get_team_id()`** resolves team_id from parameter or config, consistent with SendGrid's `_get_from_email()`
- **`_to_ms()`** handles ClickUp's millisecond timestamps — accepts ISO strings, Unix seconds, or Unix ms
- **No `asyncio.to_thread()`** needed — httpx is natively async

---

## Step 3: Tier 1 — Core Task Management (9 tools)

Add inside `register_tools()`, replacing Tier 1 placeholder:

```python
    @mcp.tool()
    async def clickup_get_workspaces() -> str:
        """List accessible ClickUp workspaces/teams."""
        data = await _request("GET", "/team")
        teams = data.get("teams", []) if isinstance(data, dict) else data
        return _success(200, data=teams, count=len(teams))

    @mcp.tool()
    async def clickup_get_spaces(team_id: str | None = None) -> str:
        """List spaces in a ClickUp workspace.

        Args:
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("GET", f"/team/{tid}/space", params={"archived": "false"})
        spaces = data.get("spaces", []) if isinstance(data, dict) else data
        return _success(200, data=spaces, count=len(spaces))

    @mcp.tool()
    async def clickup_get_lists(
        space_id: str | None = None,
        folder_id: str | None = None,
    ) -> str:
        """Get lists in a ClickUp space or folder.

        Args:
            space_id: Space ID (for folderless lists)
            folder_id: Folder ID (for lists in a folder)
        """
        if folder_id:
            data = await _request("GET", f"/folder/{folder_id}/list", params={"archived": "false"})
        elif space_id:
            data = await _request("GET", f"/space/{space_id}/list", params={"archived": "false"})
        else:
            raise ToolError("Either 'space_id' or 'folder_id' is required.")
        lists = data.get("lists", []) if isinstance(data, dict) else data
        return _success(200, data=lists, count=len(lists))

    @mcp.tool()
    async def clickup_create_task(
        list_id: str,
        name: str,
        description: str | None = None,
        assignees: list[int] | None = None,
        status: str | None = None,
        priority: int | None = None,
        due_date: str | int | None = None,
        start_date: str | int | None = None,
        tags: list[str] | None = None,
        parent: str | None = None,
        time_estimate: int | None = None,
    ) -> str:
        """Create a task in a ClickUp list. Pass parent to create a subtask.

        Args:
            list_id: List to create the task in
            name: Task name
            description: Task description (markdown supported)
            assignees: User IDs to assign
            status: Status name (case-sensitive, must match list config)
            priority: 1=Urgent, 2=High, 3=Normal, 4=Low
            due_date: ISO datetime or Unix ms timestamp
            start_date: ISO datetime or Unix ms timestamp
            tags: Tag names to apply
            parent: Parent task ID (creates a subtask)
            time_estimate: Estimated time in milliseconds
        """
        body: dict = {"name": name}
        if description is not None:
            body["description"] = description
        if assignees is not None:
            body["assignees"] = assignees
        if status is not None:
            body["status"] = status
        if priority is not None:
            body["priority"] = priority
        if due_date is not None:
            body["due_date"] = _to_ms(due_date)
        if start_date is not None:
            body["start_date"] = _to_ms(start_date)
        if tags is not None:
            body["tags"] = tags
        if parent is not None:
            body["parent"] = parent
        if time_estimate is not None:
            body["time_estimate"] = time_estimate

        logger.info("Creating task '%s' in list %s", name, list_id)
        data = await _request("POST", f"/list/{list_id}/task", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_get_task(
        task_id: str,
        include_subtasks: bool = False,
    ) -> str:
        """Get ClickUp task details by ID.

        Args:
            task_id: Task ID
            include_subtasks: Include subtasks in response
        """
        params = {}
        if include_subtasks:
            params["include_subtasks"] = "true"
        data = await _request("GET", f"/task/{task_id}", params=params)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_update_task(
        task_id: str,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: int | None = None,
        due_date: str | int | None = None,
        start_date: str | int | None = None,
        assignees_add: list[int] | None = None,
        assignees_remove: list[int] | None = None,
    ) -> str:
        """Update ClickUp task properties.

        Args:
            task_id: Task ID
            name: New task name
            description: New description
            status: New status (case-sensitive, must match list config)
            priority: 1=Urgent, 2=High, 3=Normal, 4=Low
            due_date: ISO datetime or Unix ms timestamp
            start_date: ISO datetime or Unix ms timestamp
            assignees_add: User IDs to add as assignees
            assignees_remove: User IDs to remove from assignees
        """
        body: dict = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if status is not None:
            body["status"] = status
        if priority is not None:
            body["priority"] = priority
        if due_date is not None:
            body["due_date"] = _to_ms(due_date)
        if start_date is not None:
            body["start_date"] = _to_ms(start_date)
        if assignees_add is not None or assignees_remove is not None:
            body["assignees"] = {}
            if assignees_add:
                body["assignees"]["add"] = assignees_add
            if assignees_remove:
                body["assignees"]["rem"] = assignees_remove

        if not body:
            raise ToolError("At least one field to update must be provided.")

        logger.info("Updating task %s", task_id)
        data = await _request("PUT", f"/task/{task_id}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_get_tasks(
        list_id: str,
        page: int = 0,
        statuses: list[str] | None = None,
        assignees: list[int] | None = None,
        include_closed: bool = False,
        subtasks: bool = False,
        order_by: str | None = None,
    ) -> str:
        """List tasks in a ClickUp list with filtering and pagination.

        Args:
            list_id: List ID
            page: Page number (default 0, max 100 tasks per page)
            statuses: Filter by status names
            assignees: Filter by assignee user IDs
            include_closed: Include closed tasks
            subtasks: Include subtasks
            order_by: Sort by 'created', 'updated', or 'due_date'
        """
        params: dict = {"page": str(page)}
        if include_closed:
            params["include_closed"] = "true"
        if subtasks:
            params["subtasks"] = "true"
        if order_by:
            params["order_by"] = order_by
        if statuses:
            for s in statuses:
                params.setdefault("statuses[]", [])
                if isinstance(params["statuses[]"], list):
                    params["statuses[]"].append(s)
        if assignees:
            for a in assignees:
                params.setdefault("assignees[]", [])
                if isinstance(params["assignees[]"], list):
                    params["assignees[]"].append(str(a))

        data = await _request("GET", f"/list/{list_id}/task", params=params)
        tasks = data.get("tasks", []) if isinstance(data, dict) else data
        return _success(200, data=tasks, count=len(tasks), page=page)

    @mcp.tool()
    async def clickup_search_tasks(
        team_id: str | None = None,
        page: int = 0,
        statuses: list[str] | None = None,
        assignees: list[int] | None = None,
        tags: list[str] | None = None,
        space_ids: list[str] | None = None,
        list_ids: list[str] | None = None,
        include_closed: bool = False,
    ) -> str:
        """Search tasks across a ClickUp workspace.

        Args:
            team_id: Workspace ID (uses default if not provided)
            page: Page number (default 0)
            statuses: Filter by statuses
            assignees: Filter by assignee user IDs
            tags: Filter by tag names
            space_ids: Filter by space IDs
            list_ids: Filter by list IDs
            include_closed: Include closed tasks
        """
        tid = _get_team_id(team_id)
        params: dict = {"page": str(page)}
        if include_closed:
            params["include_closed"] = "true"
        if statuses:
            for s in statuses:
                params.setdefault("statuses[]", [])
                if isinstance(params["statuses[]"], list):
                    params["statuses[]"].append(s)
        if assignees:
            for a in assignees:
                params.setdefault("assignees[]", [])
                if isinstance(params["assignees[]"], list):
                    params["assignees[]"].append(str(a))
        if tags:
            for t in tags:
                params.setdefault("tags[]", [])
                if isinstance(params["tags[]"], list):
                    params["tags[]"].append(t)
        if space_ids:
            for sid in space_ids:
                params.setdefault("space_ids[]", [])
                if isinstance(params["space_ids[]"], list):
                    params["space_ids[]"].append(sid)
        if list_ids:
            for lid in list_ids:
                params.setdefault("list_ids[]", [])
                if isinstance(params["list_ids[]"], list):
                    params["list_ids[]"].append(lid)

        data = await _request("GET", f"/team/{tid}/task", params=params)
        tasks = data.get("tasks", []) if isinstance(data, dict) else data
        return _success(200, data=tasks, count=len(tasks), page=page)

    @mcp.tool()
    async def clickup_delete_task(task_id: str) -> str:
        """Delete a ClickUp task.

        Args:
            task_id: Task ID to delete
        """
        logger.info("Deleting task %s", task_id)
        await _request("DELETE", f"/task/{task_id}")
        return _success(200, deleted_task_id=task_id)
```

---

## Step 4: Tier 2 — Task Details (6 tools)

```python
    @mcp.tool()
    async def clickup_add_comment(
        task_id: str,
        comment_text: str,
        assignee: int | None = None,
    ) -> str:
        """Add a comment to a ClickUp task.

        Args:
            task_id: Task ID
            comment_text: Comment text (plain text)
            assignee: User ID to assign the comment to
        """
        body: dict = {"comment_text": comment_text}
        if assignee is not None:
            body["assignee"] = assignee

        data = await _request("POST", f"/task/{task_id}/comment", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_get_comments(task_id: str) -> str:
        """List comments on a ClickUp task.

        Args:
            task_id: Task ID
        """
        data = await _request("GET", f"/task/{task_id}/comment")
        comments = data.get("comments", []) if isinstance(data, dict) else data
        return _success(200, data=comments, count=len(comments))

    @mcp.tool()
    async def clickup_create_checklist(task_id: str, name: str) -> str:
        """Add a checklist to a ClickUp task.

        Args:
            task_id: Task ID
            name: Checklist name
        """
        data = await _request("POST", f"/task/{task_id}/checklist", json={"name": name})
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_add_checklist_item(
        checklist_id: str,
        name: str,
        assignee: int | None = None,
    ) -> str:
        """Add an item to a ClickUp checklist.

        Args:
            checklist_id: Checklist ID
            name: Item text
            assignee: User ID to assign
        """
        body: dict = {"name": name}
        if assignee is not None:
            body["assignee"] = assignee

        data = await _request(
            "POST", f"/checklist/{checklist_id}/checklist_item", json=body
        )
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_add_tag(task_id: str, tag_name: str) -> str:
        """Add a tag to a ClickUp task.

        Args:
            task_id: Task ID
            tag_name: Tag name
        """
        await _request("POST", f"/task/{task_id}/tag/{tag_name}", json={})
        return _success(200, task_id=task_id, tag=tag_name, action="added")

    @mcp.tool()
    async def clickup_remove_tag(task_id: str, tag_name: str) -> str:
        """Remove a tag from a ClickUp task.

        Args:
            task_id: Task ID
            tag_name: Tag name
        """
        await _request("DELETE", f"/task/{task_id}/tag/{tag_name}")
        return _success(200, task_id=task_id, tag=tag_name, action="removed")
```

---

## Step 5: Tier 3 — Time Tracking (4 tools)

```python
    @mcp.tool()
    async def clickup_log_time(
        task_id: str,
        duration: int,
        description: str | None = None,
        start: str | int | None = None,
        end: str | int | None = None,
    ) -> str:
        """Log a time entry on a ClickUp task.

        Args:
            task_id: Task ID
            duration: Duration in milliseconds
            description: Description of work done
            start: Start time (ISO datetime or Unix ms)
            end: End time (ISO datetime or Unix ms)
        """
        body: dict = {"duration": duration}
        if description is not None:
            body["description"] = description
        if start is not None:
            body["start"] = _to_ms(start)
        if end is not None:
            body["end"] = _to_ms(end)

        data = await _request("POST", f"/task/{task_id}/time", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_get_time_entries(
        team_id: str | None = None,
        start_date: str | int | None = None,
        end_date: str | int | None = None,
        assignees: list[int] | None = None,
    ) -> str:
        """Get time entries for a ClickUp workspace.

        Args:
            team_id: Workspace ID (uses default if not provided)
            start_date: Filter start (ISO datetime or Unix ms)
            end_date: Filter end (ISO datetime or Unix ms)
            assignees: Filter by user IDs
        """
        tid = _get_team_id(team_id)
        params: dict = {}
        if start_date is not None:
            params["start_date"] = str(_to_ms(start_date))
        if end_date is not None:
            params["end_date"] = str(_to_ms(end_date))
        if assignees:
            params["assignee"] = ",".join(str(a) for a in assignees)

        data = await _request("GET", f"/team/{tid}/time_entries", params=params)
        entries = data.get("data", []) if isinstance(data, dict) else data
        return _success(200, data=entries, count=len(entries))

    @mcp.tool()
    async def clickup_start_timer(
        task_id: str,
        team_id: str | None = None,
        description: str | None = None,
    ) -> str:
        """Start a running timer on a ClickUp task.

        Args:
            task_id: Task to track time on
            team_id: Workspace ID (uses default if not provided)
            description: Timer description
        """
        tid = _get_team_id(team_id)
        body: dict = {"tid": task_id}
        if description is not None:
            body["description"] = description

        data = await _request("POST", f"/team/{tid}/time_entries/start", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_stop_timer(team_id: str | None = None) -> str:
        """Stop the running ClickUp timer.

        Args:
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("POST", f"/team/{tid}/time_entries/stop", json={})
        return _success(200, data=data)
```

---

## Step 6: Tier 4 — Organizational (6 tools)

```python
    @mcp.tool()
    async def clickup_create_space(
        name: str,
        team_id: str | None = None,
    ) -> str:
        """Create a new space in a ClickUp workspace.

        Args:
            name: Space name
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("POST", f"/team/{tid}/space", json={"name": name})
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_create_list(
        name: str,
        space_id: str | None = None,
        folder_id: str | None = None,
    ) -> str:
        """Create a new list in a ClickUp space or folder.

        Args:
            name: List name
            space_id: Space ID (for folderless list)
            folder_id: Folder ID
        """
        if folder_id:
            path = f"/folder/{folder_id}/list"
        elif space_id:
            path = f"/space/{space_id}/list"
        else:
            raise ToolError("Either 'space_id' or 'folder_id' is required.")

        data = await _request("POST", path, json={"name": name})
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_create_folder(space_id: str, name: str) -> str:
        """Create a folder in a ClickUp space.

        Args:
            space_id: Space ID
            name: Folder name
        """
        data = await _request("POST", f"/space/{space_id}/folder", json={"name": name})
        return _success(200, data=data)

    @mcp.tool()
    async def clickup_get_members(team_id: str | None = None) -> str:
        """List workspace members in ClickUp.

        Args:
            team_id: Workspace ID (uses default if not provided)
        """
        tid = _get_team_id(team_id)
        data = await _request("GET", f"/team/{tid}")
        members = data.get("team", {}).get("members", []) if isinstance(data, dict) else []
        return _success(200, data=members, count=len(members))

    @mcp.tool()
    async def clickup_get_custom_fields(list_id: str) -> str:
        """Get accessible custom fields for a ClickUp list.

        Args:
            list_id: List ID
        """
        data = await _request("GET", f"/list/{list_id}/field")
        fields = data.get("fields", []) if isinstance(data, dict) else data
        return _success(200, data=fields, count=len(fields))

    @mcp.tool()
    async def clickup_set_custom_field(
        task_id: str,
        field_id: str,
        value: str | int | float | bool | list | None = None,
    ) -> str:
        """Set a custom field value on a ClickUp task.

        Args:
            task_id: Task ID
            field_id: Custom field ID
            value: Field value (type depends on field definition)
        """
        data = await _request(
            "POST", f"/task/{task_id}/field/{field_id}", json={"value": value}
        )
        return _success(200, data=data)
```

---

## Step 7: Register ClickUp Tools

### 7a. Update `src/mcp_toolbox/tools/__init__.py`
```python
"""Tool registration hub — imports all tool modules and registers them."""

from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools import clickup_tool, example_tool, sendgrid_tool


def register_all_tools(mcp: FastMCP) -> None:
    """Register all tool modules with the MCP server."""
    example_tool.register_tools(mcp)
    sendgrid_tool.register_tools(mcp)
    clickup_tool.register_tools(mcp)
```

### 7b. Update `pyproject.toml` pyright exclude
Add `clickup_tool.py` alongside `sendgrid_tool.py` in the exclude list (httpx dynamic response types trigger similar pyright false positives):
```toml
[tool.pyright]
pythonVersion = "3.10"
typeCheckingMode = "basic"
exclude = ["src/mcp_toolbox/tools/sendgrid_tool.py", "src/mcp_toolbox/tools/clickup_tool.py"]
```

---

## Step 8: Tests

Create `tests/test_clickup_tool.py`. Uses `respx` for HTTP mocking — cleaner than `unittest.mock.patch` since we're calling httpx directly.

### 8a. Test Infrastructure & Fixtures

```python
"""Tests for ClickUp tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.clickup_tool import register_tools

CLICKUP_BASE = "https://api.clickup.com/api/v2"


def _get_result_data(result) -> dict:
    """Extract and parse JSON from call_tool result."""
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    """Create a test MCP server with ClickUp tools registered."""
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.clickup_tool.CLICKUP_API_TOKEN", "pk_test-token"), \
         patch("mcp_toolbox.tools.clickup_tool.CLICKUP_TEAM_ID", "team_123"), \
         patch("mcp_toolbox.tools.clickup_tool._client", None):
        register_tools(mcp)
        yield mcp
```

### 8b. Tier 1 Tests

```python
# --- Missing API Token ---

@pytest.mark.asyncio
async def test_missing_api_token():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.clickup_tool.CLICKUP_API_TOKEN", None), \
         patch("mcp_toolbox.tools.clickup_tool.CLICKUP_TEAM_ID", "team_123"), \
         patch("mcp_toolbox.tools.clickup_tool._client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="CLICKUP_API_TOKEN"):
            await mcp.call_tool("clickup_get_workspaces", {})


# --- Core Task Management ---

@pytest.mark.asyncio
@respx.mock
async def test_get_workspaces(server):
    respx.get(f"{CLICKUP_BASE}/team").mock(
        return_value=httpx.Response(200, json={"teams": [
            {"id": "t1", "name": "My Workspace"}
        ]})
    )
    result = await server.call_tool("clickup_get_workspaces", {})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_spaces(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/space").mock(
        return_value=httpx.Response(200, json={"spaces": [
            {"id": "s1", "name": "Engineering"}
        ]})
    )
    result = await server.call_tool("clickup_get_spaces", {})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_lists_from_space(server):
    respx.get(f"{CLICKUP_BASE}/space/s1/list").mock(
        return_value=httpx.Response(200, json={"lists": [
            {"id": "l1", "name": "Sprint 1"}
        ]})
    )
    result = await server.call_tool("clickup_get_lists", {"space_id": "s1"})
    data = _get_result_data(result)
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_get_lists_missing_ids(server):
    with pytest.raises(Exception, match="space_id.*folder_id"):
        await server.call_tool("clickup_get_lists", {})


@pytest.mark.asyncio
@respx.mock
async def test_create_task(server):
    respx.post(f"{CLICKUP_BASE}/list/l1/task").mock(
        return_value=httpx.Response(200, json={
            "id": "task_abc", "name": "My Task", "status": {"status": "open"}
        })
    )
    result = await server.call_tool("clickup_create_task", {
        "list_id": "l1",
        "name": "My Task",
        "priority": 3,
    })
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["data"]["id"] == "task_abc"


@pytest.mark.asyncio
@respx.mock
async def test_get_task(server):
    respx.get(f"{CLICKUP_BASE}/task/task_abc").mock(
        return_value=httpx.Response(200, json={"id": "task_abc", "name": "My Task"})
    )
    result = await server.call_tool("clickup_get_task", {"task_id": "task_abc"})
    data = _get_result_data(result)
    assert data["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_task(server):
    respx.put(f"{CLICKUP_BASE}/task/task_abc").mock(
        return_value=httpx.Response(200, json={"id": "task_abc", "status": {"status": "done"}})
    )
    result = await server.call_tool("clickup_update_task", {
        "task_id": "task_abc",
        "status": "done",
    })
    data = _get_result_data(result)
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_update_task_no_fields(server):
    with pytest.raises(Exception, match="At least one field"):
        await server.call_tool("clickup_update_task", {"task_id": "task_abc"})


@pytest.mark.asyncio
@respx.mock
async def test_get_tasks(server):
    respx.get(f"{CLICKUP_BASE}/list/l1/task").mock(
        return_value=httpx.Response(200, json={"tasks": [
            {"id": "t1", "name": "Task 1"},
            {"id": "t2", "name": "Task 2"},
        ]})
    )
    result = await server.call_tool("clickup_get_tasks", {"list_id": "l1"})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_search_tasks(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/task").mock(
        return_value=httpx.Response(200, json={"tasks": [
            {"id": "t1", "name": "Found Task"},
        ]})
    )
    result = await server.call_tool("clickup_search_tasks", {})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_delete_task(server):
    respx.delete(f"{CLICKUP_BASE}/task/task_abc").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("clickup_delete_task", {"task_id": "task_abc"})
    data = _get_result_data(result)
    assert data["status"] == "success"
```

### 8c. Tier 2 Tests

```python
@pytest.mark.asyncio
@respx.mock
async def test_add_comment(server):
    respx.post(f"{CLICKUP_BASE}/task/task_abc/comment").mock(
        return_value=httpx.Response(200, json={"id": "comment_1"})
    )
    result = await server.call_tool("clickup_add_comment", {
        "task_id": "task_abc",
        "comment_text": "Looks good!",
    })
    data = _get_result_data(result)
    assert data["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_comments(server):
    respx.get(f"{CLICKUP_BASE}/task/task_abc/comment").mock(
        return_value=httpx.Response(200, json={"comments": [
            {"id": "c1", "comment_text": "Hello"}
        ]})
    )
    result = await server.call_tool("clickup_get_comments", {"task_id": "task_abc"})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_create_checklist(server):
    respx.post(f"{CLICKUP_BASE}/task/task_abc/checklist").mock(
        return_value=httpx.Response(200, json={"checklist": {"id": "cl_1", "name": "TODO"}})
    )
    result = await server.call_tool("clickup_create_checklist", {
        "task_id": "task_abc", "name": "TODO",
    })
    data = _get_result_data(result)
    assert data["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_add_checklist_item(server):
    respx.post(f"{CLICKUP_BASE}/checklist/cl_1/checklist_item").mock(
        return_value=httpx.Response(200, json={"checklist": {"id": "cl_1"}})
    )
    result = await server.call_tool("clickup_add_checklist_item", {
        "checklist_id": "cl_1", "name": "Buy milk",
    })
    data = _get_result_data(result)
    assert data["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_add_tag(server):
    respx.post(f"{CLICKUP_BASE}/task/task_abc/tag/urgent").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await server.call_tool("clickup_add_tag", {
        "task_id": "task_abc", "tag_name": "urgent",
    })
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["action"] == "added"


@pytest.mark.asyncio
@respx.mock
async def test_remove_tag(server):
    respx.delete(f"{CLICKUP_BASE}/task/task_abc/tag/urgent").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await server.call_tool("clickup_remove_tag", {
        "task_id": "task_abc", "tag_name": "urgent",
    })
    data = _get_result_data(result)
    assert data["action"] == "removed"
```

### 8d. Tier 3 Tests

```python
@pytest.mark.asyncio
@respx.mock
async def test_log_time(server):
    respx.post(f"{CLICKUP_BASE}/task/task_abc/time").mock(
        return_value=httpx.Response(200, json={"data": {"id": "te_1"}})
    )
    result = await server.call_tool("clickup_log_time", {
        "task_id": "task_abc", "duration": 3600000,
    })
    data = _get_result_data(result)
    assert data["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_time_entries(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/time_entries").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "te_1", "duration": "3600000"}
        ]})
    )
    result = await server.call_tool("clickup_get_time_entries", {})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_start_timer(server):
    respx.post(f"{CLICKUP_BASE}/team/team_123/time_entries/start").mock(
        return_value=httpx.Response(200, json={"data": {"id": "te_2"}})
    )
    result = await server.call_tool("clickup_start_timer", {"task_id": "task_abc"})
    data = _get_result_data(result)
    assert data["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_stop_timer(server):
    respx.post(f"{CLICKUP_BASE}/team/team_123/time_entries/stop").mock(
        return_value=httpx.Response(200, json={"data": {"id": "te_2", "duration": "1800000"}})
    )
    result = await server.call_tool("clickup_stop_timer", {})
    data = _get_result_data(result)
    assert data["status"] == "success"
```

### 8e. Tier 4 Tests

```python
@pytest.mark.asyncio
@respx.mock
async def test_create_space(server):
    respx.post(f"{CLICKUP_BASE}/team/team_123/space").mock(
        return_value=httpx.Response(200, json={"id": "s_new", "name": "New Space"})
    )
    result = await server.call_tool("clickup_create_space", {"name": "New Space"})
    data = _get_result_data(result)
    assert data["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_list(server):
    respx.post(f"{CLICKUP_BASE}/space/s1/list").mock(
        return_value=httpx.Response(200, json={"id": "l_new", "name": "Backlog"})
    )
    result = await server.call_tool("clickup_create_list", {
        "name": "Backlog", "space_id": "s1",
    })
    data = _get_result_data(result)
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_create_list_missing_ids(server):
    with pytest.raises(Exception, match="space_id.*folder_id"):
        await server.call_tool("clickup_create_list", {"name": "Test"})


@pytest.mark.asyncio
@respx.mock
async def test_create_folder(server):
    respx.post(f"{CLICKUP_BASE}/space/s1/folder").mock(
        return_value=httpx.Response(200, json={"id": "f_new", "name": "Sprint 2"})
    )
    result = await server.call_tool("clickup_create_folder", {
        "space_id": "s1", "name": "Sprint 2",
    })
    data = _get_result_data(result)
    assert data["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_members(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123").mock(
        return_value=httpx.Response(200, json={"team": {
            "id": "team_123",
            "members": [{"user": {"id": 1, "username": "john"}}]
        }})
    )
    result = await server.call_tool("clickup_get_members", {})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_custom_fields(server):
    respx.get(f"{CLICKUP_BASE}/list/l1/field").mock(
        return_value=httpx.Response(200, json={"fields": [
            {"id": "cf_1", "name": "Priority Score", "type": "number"}
        ]})
    )
    result = await server.call_tool("clickup_get_custom_fields", {"list_id": "l1"})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_set_custom_field(server):
    respx.post(f"{CLICKUP_BASE}/task/task_abc/field/cf_1").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await server.call_tool("clickup_set_custom_field", {
        "task_id": "task_abc", "field_id": "cf_1", "value": 42,
    })
    data = _get_result_data(result)
    assert data["status"] == "success"
```

### 8f. API Error Tests

```python
@pytest.mark.asyncio
@respx.mock
async def test_api_error_401(server):
    respx.get(f"{CLICKUP_BASE}/team").mock(
        return_value=httpx.Response(401, json={"err": "Token invalid", "ECODE": "OAUTH_025"})
    )
    with pytest.raises(Exception, match="ClickUp API error.*401.*Token invalid"):
        await server.call_tool("clickup_get_workspaces", {})


@pytest.mark.asyncio
@respx.mock
async def test_api_error_429(server):
    respx.get(f"{CLICKUP_BASE}/team").mock(
        return_value=httpx.Response(429, headers={"X-RateLimit-Reset": "1700000000"})
    )
    with pytest.raises(Exception, match="rate limit"):
        await server.call_tool("clickup_get_workspaces", {})
```

### 8g. Update `test_server.py`

Update the expected tool set:
```python
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
```

---

## Step 9: Documentation & Validation

### 9a. Update `CLAUDE.md`
Add ClickUp to the Source Layout and Integrations sections.

### 9b. Run validation
```bash
uv sync --dev --all-extras
uv run pytest -v
uv run ruff check src/ tests/
uv run pyright src/
```

---

## Execution Order

| Order | Step | Description | Depends On |
|-------|------|-------------|------------|
| 1 | Dependencies & config | pyproject.toml, config.py, .env.example | — |
| 2 | Tool module foundation | clickup_tool.py scaffolding + helpers | Step 1 |
| 3 | Tier 1 tools | 9 core task management tools | Step 2 |
| 4 | Tier 2 tools | 6 task detail tools | Step 2 |
| 5 | Tier 3 tools | 4 time tracking tools | Step 2 |
| 6 | Tier 4 tools | 6 organizational tools | Step 2 |
| 7 | Registration | tools/__init__.py, pyright exclude | Steps 3-6 |
| 8 | Tests | test_clickup_tool.py (all tiers + errors) | Steps 3-7 |
| 9 | Docs & validation | CLAUDE.md, full test run | Steps 1-8 |

Steps 3, 4, 5, 6 are independent of each other.

---

## Risk Notes

- **`respx` mock routing:** respx matches routes by method + URL. If the ClickUp API has query parameters in the URL path (rare but possible), mock routes may need pattern matching.
- **Array query parameters:** ClickUp uses `statuses[]=x&statuses[]=y` format. httpx handles this differently — may need explicit param construction. Verify during implementation.
- **`_to_ms()` heuristic:** Distinguishes seconds vs ms by checking `< 10_000_000_000`. This works for dates before 2286 but is a heuristic — document in tool descriptions.
- **`call_tool` return format:** Same as SendGrid — `result[0][0].text` via `_get_result_data()`.
- **204 No Content:** `clickup_delete_task` returns 204 with empty body. The `_request()` helper returns `{}` for 204s.
