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
        if value < 10_000_000_000:
            return value * 1000
        return value
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
            data = await _request(
                "GET", f"/folder/{folder_id}/list", params={"archived": "false"}
            )
        elif space_id:
            data = await _request(
                "GET", f"/space/{space_id}/list", params={"archived": "false"}
            )
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
            params["statuses[]"] = statuses
        if assignees:
            params["assignees[]"] = [str(a) for a in assignees]

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
            params["statuses[]"] = statuses
        if assignees:
            params["assignees[]"] = [str(a) for a in assignees]
        if tags:
            params["tags[]"] = tags
        if space_ids:
            params["space_ids[]"] = space_ids
        if list_ids:
            params["list_ids[]"] = list_ids

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

    # --- Tier 2: Task Details ---

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

    # --- Tier 3: Time Tracking ---

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

    # --- Tier 4: Organizational ---

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
        members = (
            data.get("team", {}).get("members", []) if isinstance(data, dict) else []
        )
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
