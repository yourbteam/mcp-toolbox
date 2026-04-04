"""Google Tasks integration — task lists, tasks, ordering."""

import asyncio
import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import GOOGLE_SERVICE_ACCOUNT_JSON, GTASKS_DELEGATED_USER

logger = logging.getLogger(__name__)

_credentials = None
_client: httpx.AsyncClient | None = None

BASE = "https://tasks.googleapis.com/tasks/v1"


def _get_token() -> str:
    global _credentials
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ToolError(
            "GOOGLE_SERVICE_ACCOUNT_JSON not configured."
        )
    if not GTASKS_DELEGATED_USER:
        raise ToolError(
            "GTASKS_DELEGATED_USER not configured. "
            "Tasks API requires domain-wide delegation."
        )
    if _credentials is None:
        import google.auth.transport.requests
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=["https://www.googleapis.com/auth/tasks"],
        )
        _credentials = creds.with_subject(GTASKS_DELEGATED_USER)
    if not _credentials.valid:
        import google.auth.transport.requests

        _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token


async def _get_client() -> httpx.AsyncClient:
    global _client
    token = await asyncio.to_thread(_get_token)
    if _client is None:
        _client = httpx.AsyncClient(base_url=BASE, timeout=30.0)
    _client.headers["Authorization"] = f"Bearer {token}"
    return _client


def _success(sc: int, **kw) -> str:
    return json.dumps({"status": "success", "status_code": sc, **kw})


def _tl(tasklist_id: str | None) -> str:
    return tasklist_id or "@default"


async def _req(
    method: str, url: str, json_body: dict | None = None,
    params: dict | None = None,
) -> dict | list:
    client = await _get_client()
    kwargs: dict = {}
    if json_body is not None:
        kwargs["json"] = json_body
    if params:
        kwargs["params"] = params
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"Google Tasks request failed: {e}") from e
    if response.status_code == 429:
        raise ToolError("Google Tasks rate limit exceeded.")
    if response.status_code == 403:
        try:
            err = response.json().get("error", {})
            reason = ""
            for e_item in err.get("errors", []):
                if e_item.get("reason") == "rateLimitExceeded":
                    raise ToolError("Google Tasks rate limit exceeded.")
                reason = e_item.get("reason", "")
            msg = err.get("message", response.text)
        except ToolError:
            raise
        except Exception:
            msg = response.text
            reason = ""
        raise ToolError(
            f"Google Tasks error (403"
            f"{f' {reason}' if reason else ''}): {msg}"
        )
    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
            msg = err.get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(
            f"Google Tasks error ({response.status_code}): {msg}"
        )
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def register_tools(mcp: FastMCP) -> None:
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        logger.warning(
            "GOOGLE_SERVICE_ACCOUNT_JSON not set — Tasks tools will fail."
        )

    # === TIER 1: TASK LIST OPERATIONS ===

    @mcp.tool()
    async def gtasks_list_tasklists(
        max_results: int = 20,
        page_token: str | None = None,
    ) -> str:
        """List all task lists for the user.
        Args:
            max_results: Max results (default 20, max 100)
            page_token: Pagination token
        """
        p: dict = {"maxResults": str(max_results)}
        if page_token is not None:
            p["pageToken"] = page_token
        data = await _req("GET", "/users/@me/lists", params=p)
        items = data.get("items", []) if isinstance(data, dict) else data
        npt = data.get("nextPageToken") if isinstance(data, dict) else None
        return _success(
            200, data=items, count=len(items), next_page_token=npt,
        )

    @mcp.tool()
    async def gtasks_get_tasklist(tasklist_id: str) -> str:
        """Get a specific task list.
        Args:
            tasklist_id: Task list ID (use @default for My Tasks)
        """
        data = await _req("GET", f"/users/@me/lists/{tasklist_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def gtasks_insert_tasklist(title: str) -> str:
        """Create a new task list.
        Args:
            title: Title for the new task list
        """
        data = await _req(
            "POST", "/users/@me/lists", json_body={"title": title},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gtasks_update_tasklist(
        tasklist_id: str, title: str,
    ) -> str:
        """Full update of a task list.
        Args:
            tasklist_id: Task list ID
            title: New title
        """
        data = await _req(
            "PUT", f"/users/@me/lists/{tasklist_id}",
            json_body={"title": title},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gtasks_patch_tasklist(
        tasklist_id: str, title: str | None = None,
    ) -> str:
        """Partial update of a task list.
        Args:
            tasklist_id: Task list ID
            title: New title
        """
        body: dict = {}
        if title is not None:
            body["title"] = title
        if not body:
            raise ToolError("At least one field must be provided.")
        data = await _req(
            "PATCH", f"/users/@me/lists/{tasklist_id}",
            json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gtasks_delete_tasklist(tasklist_id: str) -> str:
        """Delete a task list and all its tasks.
        Args:
            tasklist_id: Task list ID to delete
        """
        await _req("DELETE", f"/users/@me/lists/{tasklist_id}")
        return _success(204, message="Task list deleted.")

    # === TIER 2: TASK CRUD OPERATIONS ===

    @mcp.tool()
    async def gtasks_list_tasks(
        tasklist_id: str | None = None,
        max_results: int = 20,
        page_token: str | None = None,
        due_min: str | None = None,
        due_max: str | None = None,
        completed_min: str | None = None,
        completed_max: str | None = None,
        updated_min: str | None = None,
        show_completed: bool | None = None,
        show_deleted: bool | None = None,
        show_hidden: bool | None = None,
    ) -> str:
        """List tasks in a task list.
        Args:
            tasklist_id: Task list ID (default: @default)
            max_results: Max results (default 20, max 100)
            page_token: Pagination token
            due_min: Lower bound for due date (RFC 3339)
            due_max: Upper bound for due date (RFC 3339)
            completed_min: Lower bound for completion date
            completed_max: Upper bound for completion date
            updated_min: Lower bound for last modification
            show_completed: Show completed tasks (default true)
            show_deleted: Show deleted tasks (default false)
            show_hidden: Show hidden/cleared tasks (default false)
        """
        tl = _tl(tasklist_id)
        p: dict = {"maxResults": str(max_results)}
        if page_token is not None:
            p["pageToken"] = page_token
        if due_min is not None:
            p["dueMin"] = due_min
        if due_max is not None:
            p["dueMax"] = due_max
        if completed_min is not None:
            p["completedMin"] = completed_min
        if completed_max is not None:
            p["completedMax"] = completed_max
        if updated_min is not None:
            p["updatedMin"] = updated_min
        if show_completed is not None:
            p["showCompleted"] = str(show_completed).lower()
        if show_deleted is not None:
            p["showDeleted"] = str(show_deleted).lower()
        if show_hidden is not None:
            p["showHidden"] = str(show_hidden).lower()
        data = await _req("GET", f"/lists/{tl}/tasks", params=p)
        items = data.get("items", []) if isinstance(data, dict) else data
        npt = data.get("nextPageToken") if isinstance(data, dict) else None
        return _success(
            200, data=items, count=len(items), next_page_token=npt,
        )

    @mcp.tool()
    async def gtasks_get_task(
        task_id: str, tasklist_id: str | None = None,
    ) -> str:
        """Get a specific task.
        Args:
            task_id: Task ID
            tasklist_id: Task list ID (default: @default)
        """
        tl = _tl(tasklist_id)
        data = await _req("GET", f"/lists/{tl}/tasks/{task_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def gtasks_insert_task(
        title: str,
        tasklist_id: str | None = None,
        notes: str | None = None,
        due: str | None = None,
        status: str | None = None,
        parent: str | None = None,
        previous: str | None = None,
    ) -> str:
        """Create a new task.
        Args:
            title: Task title
            tasklist_id: Task list ID (default: @default)
            notes: Task description (plain text)
            due: Due date (RFC 3339, only date stored)
            status: needsAction or completed
            parent: Parent task ID (to create as subtask)
            previous: Previous sibling task ID (position after)
        """
        tl = _tl(tasklist_id)
        body: dict = {"title": title}
        if notes is not None:
            body["notes"] = notes
        if due is not None:
            body["due"] = due
        if status is not None:
            body["status"] = status
        p: dict = {}
        if parent is not None:
            p["parent"] = parent
        if previous is not None:
            p["previous"] = previous
        data = await _req(
            "POST", f"/lists/{tl}/tasks",
            json_body=body, params=p or None,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gtasks_update_task(
        task_id: str,
        title: str,
        tasklist_id: str | None = None,
        notes: str | None = None,
        due: str | None = None,
        status: str | None = None,
    ) -> str:
        """Full update of a task (omitted optional fields are cleared).
        Args:
            task_id: Task ID
            title: Task title (required for full update)
            tasklist_id: Task list ID (default: @default)
            notes: Task description (omit to clear)
            due: Due date RFC 3339 (omit to clear)
            status: needsAction or completed
        """
        tl = _tl(tasklist_id)
        body: dict = {"id": task_id, "title": title}
        if notes is not None:
            body["notes"] = notes
        if due is not None:
            body["due"] = due
        if status is not None:
            body["status"] = status
        data = await _req(
            "PUT", f"/lists/{tl}/tasks/{task_id}", json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gtasks_patch_task(
        task_id: str,
        tasklist_id: str | None = None,
        title: str | None = None,
        notes: str | None = None,
        due: str | None = None,
        status: str | None = None,
    ) -> str:
        """Partial update of a task (only provided fields change).
        Args:
            task_id: Task ID
            tasklist_id: Task list ID (default: @default)
            title: Task title
            notes: Task description
            due: Due date RFC 3339
            status: needsAction or completed
        """
        tl = _tl(tasklist_id)
        body: dict = {}
        if title is not None:
            body["title"] = title
        if notes is not None:
            body["notes"] = notes
        if due is not None:
            body["due"] = due
        if status is not None:
            body["status"] = status
        if not body:
            raise ToolError("At least one field must be provided.")
        data = await _req(
            "PATCH", f"/lists/{tl}/tasks/{task_id}", json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gtasks_delete_task(
        task_id: str, tasklist_id: str | None = None,
    ) -> str:
        """Delete a task.
        Args:
            task_id: Task ID
            tasklist_id: Task list ID (default: @default)
        """
        tl = _tl(tasklist_id)
        await _req("DELETE", f"/lists/{tl}/tasks/{task_id}")
        return _success(204, message="Task deleted.")

    # === TIER 3: TASK ORDERING & BULK ===

    @mcp.tool()
    async def gtasks_move_task(
        task_id: str,
        tasklist_id: str | None = None,
        parent: str | None = None,
        previous: str | None = None,
    ) -> str:
        """Move a task (reorder or change parent).
        Args:
            task_id: Task ID to move
            tasklist_id: Task list ID (default: @default)
            parent: New parent task ID (omit to move to top level)
            previous: Sibling task ID to place after (omit for first)
        """
        tl = _tl(tasklist_id)
        p: dict = {}
        if parent is not None:
            p["parent"] = parent
        if previous is not None:
            p["previous"] = previous
        data = await _req(
            "POST", f"/lists/{tl}/tasks/{task_id}/move",
            params=p or None,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gtasks_clear_tasks(
        tasklist_id: str | None = None,
    ) -> str:
        """Hide all completed tasks from a task list.
        Args:
            tasklist_id: Task list ID (default: @default)
        """
        tl = _tl(tasklist_id)
        await _req("POST", f"/lists/{tl}/clear")
        return _success(204, message="Completed tasks cleared.")
