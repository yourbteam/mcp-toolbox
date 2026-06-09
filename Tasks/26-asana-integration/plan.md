# Task 26: Asana Integration - Implementation Plan

Implements the 67 tools specified in `analysis.md`. Follows the repo's established patterns: singleton `httpx.AsyncClient`, `_success()` serializer, `ToolError`, `register_tools(mcp)`, direct HTTP (no SDK).

## Files

1. **Create** `src/mcp_toolbox/tools/asana_tool.py` — 67 tools + helpers
2. **Modify** `src/mcp_toolbox/config.py` — add `ASANA_ACCESS_TOKEN`, `ASANA_DEFAULT_WORKSPACE_ID`
3. **Modify** `src/mcp_toolbox/tools/__init__.py` — import + register
4. **Create** `tests/test_asana_tool.py` — unit tests for all 67 tools
5. **Modify** `CLAUDE.md` — add Asana to source layout + integrations

---

## 1. config.py changes

Add after the Stripe block (end of file):

```python
# Asana
ASANA_ACCESS_TOKEN: str | None = os.getenv("ASANA_ACCESS_TOKEN")
ASANA_DEFAULT_WORKSPACE_ID: str | None = os.getenv("ASANA_DEFAULT_WORKSPACE_ID")
```

---

## 2. tools/__init__.py changes

Add `asana_tool` to the import tuple (alphabetical, first):

```python
from mcp_toolbox.tools import (
    asana_tool,
    aws_ssm_tool,
    ...
)
```

Add registration call inside `register_all_tools` (place near the top after example):

```python
    asana_tool.register_tools(mcp)
```

---

## 3. src/mcp_toolbox/tools/asana_tool.py (complete)

```python
"""Asana integration — workspaces, teams, projects, sections, tasks, subtasks,
stories, tags, attachments, custom fields, status updates, webhooks, jobs."""

import json
import logging
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import ASANA_ACCESS_TOKEN, ASANA_DEFAULT_WORKSPACE_ID

logger = logging.getLogger(__name__)

BASE_URL = "https://app.asana.com/api/1.0"

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if not ASANA_ACCESS_TOKEN:
        raise ToolError("ASANA_ACCESS_TOKEN not configured.")
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {ASANA_ACCESS_TOKEN}",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
    return _client


def _success(sc: int, **kw) -> str:
    return json.dumps({"status": "success", "status_code": sc, **kw})


def _clean(d: dict) -> dict:
    """Drop None-valued keys (omit optional params instead of sending null)."""
    return {k: v for k, v in d.items() if v is not None}


def _workspace(workspace_gid: str | None) -> str:
    ws = workspace_gid or ASANA_DEFAULT_WORKSPACE_ID
    if not ws:
        raise ToolError(
            "No workspace specified and ASANA_DEFAULT_WORKSPACE_ID not set."
        )
    return ws


async def _req(
    method: str,
    path: str,
    *,
    data: dict | None = None,
    params: dict | None = None,
    files: dict | None = None,
    form: dict | None = None,
) -> tuple[dict | list, dict | None]:
    """Core request wrapper.

    Wraps JSON bodies as {"data": data}; multipart uses files+form (no envelope).
    Returns (payload, next_page) where payload is unwrapped from {"data": ...}
    and next_page is Asana's pagination object (or None).
    """
    client = _get_client()
    kwargs: dict = {}
    if params is not None:
        kwargs["params"] = _clean(params)
    if files is not None:
        kwargs["files"] = files
        if form is not None:
            kwargs["data"] = form
    elif data is not None:
        kwargs["json"] = {"data": data}
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"Asana request failed: {e}") from e
    if response.status_code == 429:
        retry = response.headers.get("Retry-After", "unknown")
        raise ToolError(f"Asana rate limit exceeded. Retry after {retry}s.")
    if response.status_code >= 400:
        msg = response.text
        try:
            err = response.json()
            errors = err.get("errors") if isinstance(err, dict) else None
            if errors and isinstance(errors, list) and errors:
                msg = errors[0].get("message", msg)
        except Exception:
            pass
        raise ToolError(f"Asana error ({response.status_code}): {msg}")
    if response.status_code == 204 or not response.content:
        return {}, None
    try:
        body = response.json()
    except Exception:
        return {"raw": response.text}, None
    if isinstance(body, dict):
        return body.get("data", body), body.get("next_page")
    return body, None


def _single(payload: dict | list, sc: int = 200) -> str:
    return _success(sc, data=payload)


def _list(payload: dict | list, next_page: dict | None) -> str:
    return _success(
        200,
        data=payload,
        count=len(payload) if isinstance(payload, list) else 0,
        next_offset=(next_page or {}).get("offset"),
    )


def register_tools(mcp: FastMCP) -> None:
    if not ASANA_ACCESS_TOKEN:
        logger.warning("ASANA_ACCESS_TOKEN not set — Asana tools will fail.")

    # ============================================================
    # Tier 1: Workspaces, Users & Jobs (6 tools)
    # ============================================================

    @mcp.tool()
    async def asana_list_workspaces(
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List all workspaces/organizations visible to the token.
        Args:
            limit: Max results per page (1-100)
            offset: Pagination offset token from a prior next_offset
            opt_fields: Comma-separated fields to expand
        """
        payload, nxt = await _req(
            "GET", "/workspaces",
            params={"limit": limit, "offset": offset, "opt_fields": opt_fields},
        )
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_get_workspace(
        workspace_gid: str | None = None, opt_fields: str | None = None
    ) -> str:
        """Get a workspace by GID (defaults to ASANA_DEFAULT_WORKSPACE_ID).
        Args:
            workspace_gid: Workspace GID
            opt_fields: Comma-separated fields to expand
        """
        ws = _workspace(workspace_gid)
        payload, _ = await _req(
            "GET", f"/workspaces/{ws}", params={"opt_fields": opt_fields}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_get_me(opt_fields: str | None = None) -> str:
        """Get the user record for the token owner.
        Args:
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", "/users/me", params={"opt_fields": opt_fields}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_list_users(
        workspace_gid: str | None = None,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List users in a workspace.
        Args:
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID)
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        ws = _workspace(workspace_gid)
        payload, nxt = await _req(
            "GET", f"/workspaces/{ws}/users",
            params={"limit": limit, "offset": offset, "opt_fields": opt_fields},
        )
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_get_user(
        user_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get a user by GID ("me" accepted).
        Args:
            user_gid: User GID or "me"
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/users/{user_gid}", params={"opt_fields": opt_fields}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_get_job(
        job_gid: str, opt_fields: str | None = None
    ) -> str:
        """Poll an async job (from duplicate_task/duplicate_project).
        Args:
            job_gid: Job GID
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/jobs/{job_gid}", params={"opt_fields": opt_fields}
        )
        return _single(payload)

    # ============================================================
    # Tier 2: Teams (4 tools)
    # ============================================================

    @mcp.tool()
    async def asana_list_teams(
        workspace_gid: str | None = None,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List teams in a workspace/organization.
        Args:
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID)
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        ws = _workspace(workspace_gid)
        payload, nxt = await _req(
            "GET", f"/workspaces/{ws}/teams",
            params={"limit": limit, "offset": offset, "opt_fields": opt_fields},
        )
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_get_team(
        team_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get a team by GID.
        Args:
            team_gid: Team GID
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/teams/{team_gid}", params={"opt_fields": opt_fields}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_add_user_to_team(team_gid: str, user: str) -> str:
        """Add a user to a team.
        Args:
            team_gid: Team GID
            user: User GID, email, or "me"
        """
        payload, _ = await _req(
            "POST", f"/teams/{team_gid}/addUser", data={"user": user}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_remove_user_from_team(team_gid: str, user: str) -> str:
        """Remove a user from a team.
        Args:
            team_gid: Team GID
            user: User GID, email, or "me"
        """
        payload, _ = await _req(
            "POST", f"/teams/{team_gid}/removeUser", data={"user": user}
        )
        return _single(payload)

    # ============================================================
    # Tier 3: Projects (7 tools)
    # ============================================================

    @mcp.tool()
    async def asana_create_project(
        name: str,
        workspace_gid: str | None = None,
        team_gid: str | None = None,
        notes: str | None = None,
        color: str | None = None,
        public: bool | None = None,
        default_view: str | None = None,
        due_on: str | None = None,
        start_on: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Create a project in a workspace or team.
        Args:
            name: Project name
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID)
            team_gid: Team GID (required when the workspace is an organization)
            notes: Free-form project notes
            color: Project color (e.g. "light-green")
            public: Whether the project is public to the team
            default_view: list/board/calendar/timeline
            due_on: Due date YYYY-MM-DD
            start_on: Start date YYYY-MM-DD
            opt_fields: Comma-separated fields to expand
        """
        body = _clean({
            "name": name,
            "workspace": _workspace(workspace_gid),
            "team": team_gid,
            "notes": notes,
            "color": color,
            "public": public,
            "default_view": default_view,
            "due_on": due_on,
            "start_on": start_on,
        })
        payload, _ = await _req(
            "POST", "/projects", data=body, params={"opt_fields": opt_fields}
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_get_project(
        project_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get a project by GID.
        Args:
            project_gid: Project GID
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/projects/{project_gid}", params={"opt_fields": opt_fields}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_update_project(
        project_gid: str,
        name: str | None = None,
        notes: str | None = None,
        color: str | None = None,
        archived: bool | None = None,
        public: bool | None = None,
        default_view: str | None = None,
        due_on: str | None = None,
        start_on: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Update a project. At least one mutable field required.
        Args:
            project_gid: Project GID
            name: New name
            notes: New notes
            color: New color
            archived: Archive (true) or unarchive (false)
            public: Visibility
            default_view: list/board/calendar/timeline
            due_on: Due date YYYY-MM-DD
            start_on: Start date YYYY-MM-DD
            opt_fields: Comma-separated fields to expand
        """
        body = _clean({
            "name": name, "notes": notes, "color": color, "archived": archived,
            "public": public, "default_view": default_view,
            "due_on": due_on, "start_on": start_on,
        })
        if not body:
            raise ToolError("Provide at least one field to update.")
        payload, _ = await _req(
            "PUT", f"/projects/{project_gid}", data=body,
            params={"opt_fields": opt_fields},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_delete_project(project_gid: str) -> str:
        """Delete a project.
        Args:
            project_gid: Project GID
        """
        await _req("DELETE", f"/projects/{project_gid}")
        return _success(200, deleted=project_gid)

    @mcp.tool()
    async def asana_list_projects(
        workspace_gid: str | None = None,
        team_gid: str | None = None,
        archived: bool | None = None,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List projects in a workspace or team.
        Args:
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID
                when team_gid is not given)
            team_gid: Team GID (scopes to a team instead of a workspace)
            archived: Only archived (true) or only active (false)
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        params: dict = {
            "archived": archived, "limit": limit, "offset": offset,
            "opt_fields": opt_fields,
        }
        if team_gid:
            params["team"] = team_gid
        else:
            params["workspace"] = _workspace(workspace_gid)
        payload, nxt = await _req("GET", "/projects", params=params)
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_duplicate_project(
        project_gid: str,
        name: str,
        team_gid: str | None = None,
        include: str | None = None,
        schedule_dates: dict | None = None,
    ) -> str:
        """Duplicate a project (async — returns a Job; poll with asana_get_job).
        Args:
            project_gid: Source project GID
            name: Name for the new project
            team_gid: Team GID for the new project
            include: Comma-separated elements to copy (e.g. "members,task_notes")
            schedule_dates: Date-shift config object
        """
        body = _clean({
            "name": name, "team": team_gid,
            "include": include, "schedule_dates": schedule_dates,
        })
        payload, _ = await _req(
            "POST", f"/projects/{project_gid}/duplicate", data=body
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_get_project_task_counts(
        project_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get task counts for a project (opt_fields selects which counts).
        Args:
            project_gid: Project GID
            opt_fields: Count fields (default: all)
        """
        fields = opt_fields or (
            "num_tasks,num_incomplete_tasks,num_completed_tasks,"
            "num_milestones,num_incomplete_milestones,num_completed_milestones"
        )
        payload, _ = await _req(
            "GET", f"/projects/{project_gid}/task_counts",
            params={"opt_fields": fields},
        )
        return _single(payload)

    # ============================================================
    # Tier 4: Sections (6 tools)
    # ============================================================

    @mcp.tool()
    async def asana_create_section(
        project_gid: str,
        name: str,
        insert_before: str | None = None,
        insert_after: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Create a section in a project.
        Args:
            project_gid: Project GID
            name: Section name
            insert_before: Section GID to insert before
            insert_after: Section GID to insert after
            opt_fields: Comma-separated fields to expand
        """
        body = _clean({
            "name": name, "insert_before": insert_before,
            "insert_after": insert_after,
        })
        payload, _ = await _req(
            "POST", f"/projects/{project_gid}/sections", data=body,
            params={"opt_fields": opt_fields},
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_get_section(
        section_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get a section by GID.
        Args:
            section_gid: Section GID
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/sections/{section_gid}", params={"opt_fields": opt_fields}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_update_section(
        section_gid: str, name: str | None = None, opt_fields: str | None = None
    ) -> str:
        """Update a section (name).
        Args:
            section_gid: Section GID
            name: New section name
            opt_fields: Comma-separated fields to expand
        """
        body = _clean({"name": name})
        if not body:
            raise ToolError("Provide a field to update (name).")
        payload, _ = await _req(
            "PUT", f"/sections/{section_gid}", data=body,
            params={"opt_fields": opt_fields},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_delete_section(section_gid: str) -> str:
        """Delete a section.
        Args:
            section_gid: Section GID
        """
        await _req("DELETE", f"/sections/{section_gid}")
        return _success(200, deleted=section_gid)

    @mcp.tool()
    async def asana_list_sections(
        project_gid: str,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List sections in a project.
        Args:
            project_gid: Project GID
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        payload, nxt = await _req(
            "GET", f"/projects/{project_gid}/sections",
            params={"limit": limit, "offset": offset, "opt_fields": opt_fields},
        )
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_add_task_to_section(
        section_gid: str,
        task_gid: str,
        insert_before: str | None = None,
        insert_after: str | None = None,
    ) -> str:
        """Move a task into a section (optionally positioned).
        Args:
            section_gid: Target section GID
            task_gid: Task GID to add
            insert_before: Task GID to insert before
            insert_after: Task GID to insert after
        """
        body = _clean({
            "task": task_gid, "insert_before": insert_before,
            "insert_after": insert_after,
        })
        payload, _ = await _req(
            "POST", f"/sections/{section_gid}/addTask", data=body
        )
        return _single(payload)

    # ============================================================
    # Tier 5: Tasks — Core (13 tools)
    # ============================================================

    @mcp.tool()
    async def asana_create_task(
        name: str,
        workspace_gid: str | None = None,
        projects: list[str] | None = None,
        parent: str | None = None,
        assignee: str | None = None,
        notes: str | None = None,
        html_notes: str | None = None,
        due_on: str | None = None,
        due_at: str | None = None,
        start_on: str | None = None,
        completed: bool | None = None,
        followers: list[str] | None = None,
        tags: list[str] | None = None,
        custom_fields: dict | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Create a task. Provide projects, or a workspace (defaulted).
        Args:
            name: Task name
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID;
                inferred from projects if those are given)
            projects: Project GIDs to add the task to
            parent: Parent task GID (makes this a subtask)
            assignee: Assignee GID, email, or "me"
            notes: Plain-text notes
            html_notes: HTML notes (mutually exclusive with notes)
            due_on: Due date YYYY-MM-DD
            due_at: Due datetime ISO 8601 (clears due_on)
            start_on: Start date YYYY-MM-DD
            completed: Completion flag
            followers: Follower GIDs/emails
            tags: Tag GIDs
            custom_fields: {field_gid: value} map
            opt_fields: Comma-separated fields to expand
        """
        body = _clean({
            "name": name, "projects": projects, "parent": parent,
            "assignee": assignee, "notes": notes, "html_notes": html_notes,
            "due_on": due_on, "due_at": due_at, "start_on": start_on,
            "completed": completed, "followers": followers, "tags": tags,
            "custom_fields": custom_fields,
        })
        if not projects and not parent:
            body["workspace"] = _workspace(workspace_gid)
        payload, _ = await _req(
            "POST", "/tasks", data=body, params={"opt_fields": opt_fields}
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_get_task(
        task_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get a task by GID.
        Args:
            task_gid: Task GID
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/tasks/{task_gid}", params={"opt_fields": opt_fields}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_update_task(
        task_gid: str,
        name: str | None = None,
        notes: str | None = None,
        html_notes: str | None = None,
        assignee: str | None = None,
        completed: bool | None = None,
        due_on: str | None = None,
        due_at: str | None = None,
        start_on: str | None = None,
        custom_fields: dict | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Update a task. At least one mutable field required.
        Args:
            task_gid: Task GID
            name: New name
            notes: New plain-text notes
            html_notes: New HTML notes
            assignee: New assignee GID/email/"me"
            completed: Completion flag
            due_on: Due date YYYY-MM-DD
            due_at: Due datetime ISO 8601
            start_on: Start date YYYY-MM-DD
            custom_fields: {field_gid: value} map
            opt_fields: Comma-separated fields to expand
        """
        body = _clean({
            "name": name, "notes": notes, "html_notes": html_notes,
            "assignee": assignee, "completed": completed, "due_on": due_on,
            "due_at": due_at, "start_on": start_on, "custom_fields": custom_fields,
        })
        if not body:
            raise ToolError("Provide at least one field to update.")
        payload, _ = await _req(
            "PUT", f"/tasks/{task_gid}", data=body,
            params={"opt_fields": opt_fields},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_delete_task(task_gid: str) -> str:
        """Delete a task.
        Args:
            task_gid: Task GID
        """
        await _req("DELETE", f"/tasks/{task_gid}")
        return _success(200, deleted=task_gid)

    @mcp.tool()
    async def asana_list_tasks(
        project_gid: str | None = None,
        section_gid: str | None = None,
        tag_gid: str | None = None,
        assignee: str | None = None,
        workspace_gid: str | None = None,
        completed_since: str | None = None,
        modified_since: str | None = None,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List tasks scoped by project, section, tag, OR assignee+workspace.

        Asana's GET /tasks requires EXACTLY ONE scope selector — supply one of
        project_gid, section_gid, tag_gid, or assignee. assignee additionally
        requires a workspace (defaulted). Combining selectors is rejected by the
        API (400), so this enforces the single-choice rule up front.
        Args:
            project_gid: Scope to a project
            section_gid: Scope to a section
            tag_gid: Scope to a tag
            assignee: Scope to an assignee (requires workspace)
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID)
            completed_since: Only tasks completed since (ISO 8601 or "now")
            modified_since: Only tasks modified since (ISO 8601)
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        selectors = [
            bool(project_gid), bool(section_gid), bool(tag_gid), bool(assignee)
        ]
        chosen = sum(selectors)
        if chosen == 0:
            raise ToolError(
                "Specify exactly one of project_gid, section_gid, tag_gid, "
                "or assignee."
            )
        if chosen > 1:
            raise ToolError(
                "Asana allows only one task scope: pass exactly one of "
                "project_gid, section_gid, tag_gid, or assignee."
            )
        params: dict = {
            "project": project_gid, "section": section_gid, "tag": tag_gid,
            "assignee": assignee, "completed_since": completed_since,
            "modified_since": modified_since, "limit": limit, "offset": offset,
            "opt_fields": opt_fields,
        }
        if assignee:
            params["workspace"] = _workspace(workspace_gid)
        payload, nxt = await _req("GET", "/tasks", params=params)
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_search_tasks(
        workspace_gid: str | None = None,
        text: str | None = None,
        completed: bool | None = None,
        assignee_any: str | None = None,
        projects_any: str | None = None,
        tags_any: str | None = None,
        due_on: str | None = None,
        due_before: str | None = None,
        due_after: str | None = None,
        sort_by: str | None = None,
        sort_ascending: bool | None = None,
        limit: int | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Advanced task search in a workspace (paid plans; not offset-paged).
        Args:
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID)
            text: Full-text query
            completed: Filter by completion
            assignee_any: Comma-separated assignee GIDs (any-of)
            projects_any: Comma-separated project GIDs (any-of)
            tags_any: Comma-separated tag GIDs (any-of)
            due_on: Exact due date YYYY-MM-DD
            due_before: Due before YYYY-MM-DD
            due_after: Due after YYYY-MM-DD
            sort_by: due_date/created_at/completed_at/likes/modified_at
            sort_ascending: Sort ascending
            limit: Max results
            opt_fields: Comma-separated fields to expand
        """
        ws = _workspace(workspace_gid)
        params = {
            "text": text, "completed": completed,
            "assignee.any": assignee_any, "projects.any": projects_any,
            "tags.any": tags_any, "due_on": due_on, "due_before": due_before,
            "due_after": due_after, "sort_by": sort_by,
            "sort_ascending": sort_ascending, "limit": limit,
            "opt_fields": opt_fields,
        }
        payload, _ = await _req(
            "GET", f"/workspaces/{ws}/tasks/search", params=params
        )
        return _success(
            200, data=payload,
            count=len(payload) if isinstance(payload, list) else 0,
        )

    @mcp.tool()
    async def asana_duplicate_task(
        task_gid: str, name: str, include: str | None = None
    ) -> str:
        """Duplicate a task (async — returns a Job; poll with asana_get_job).
        Args:
            task_gid: Source task GID
            name: Name for the new task
            include: Comma-separated elements to copy (e.g. "notes,assignee")
        """
        body = _clean({"name": name, "include": include})
        payload, _ = await _req(
            "POST", f"/tasks/{task_gid}/duplicate", data=body
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_add_task_to_project(
        task_gid: str,
        project_gid: str,
        section: str | None = None,
        insert_before: str | None = None,
        insert_after: str | None = None,
    ) -> str:
        """Add a task to a project (optionally in a section/position).
        Args:
            task_gid: Task GID
            project_gid: Project GID
            section: Section GID to place the task in
            insert_before: Task GID to insert before
            insert_after: Task GID to insert after
        """
        body = _clean({
            "project": project_gid, "section": section,
            "insert_before": insert_before, "insert_after": insert_after,
        })
        payload, _ = await _req(
            "POST", f"/tasks/{task_gid}/addProject", data=body
        )
        return _single(payload)

    @mcp.tool()
    async def asana_remove_task_from_project(
        task_gid: str, project_gid: str
    ) -> str:
        """Remove a task from a project.
        Args:
            task_gid: Task GID
            project_gid: Project GID
        """
        payload, _ = await _req(
            "POST", f"/tasks/{task_gid}/removeProject",
            data={"project": project_gid},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_add_task_followers(
        task_gid: str, followers: list[str]
    ) -> str:
        """Add followers to a task.
        Args:
            task_gid: Task GID
            followers: Follower GIDs or emails
        """
        payload, _ = await _req(
            "POST", f"/tasks/{task_gid}/addFollowers",
            data={"followers": followers},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_remove_task_followers(
        task_gid: str, followers: list[str]
    ) -> str:
        """Remove followers from a task.
        Args:
            task_gid: Task GID
            followers: Follower GIDs or emails
        """
        payload, _ = await _req(
            "POST", f"/tasks/{task_gid}/removeFollowers",
            data={"followers": followers},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_add_task_dependencies(
        task_gid: str, dependencies: list[str]
    ) -> str:
        """Mark tasks this task depends on.
        Args:
            task_gid: Task GID
            dependencies: Task GIDs this task depends on
        """
        payload, _ = await _req(
            "POST", f"/tasks/{task_gid}/addDependencies",
            data={"dependencies": dependencies},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_add_task_dependents(
        task_gid: str, dependents: list[str]
    ) -> str:
        """Mark tasks that depend on this task.
        Args:
            task_gid: Task GID
            dependents: Task GIDs that depend on this task
        """
        payload, _ = await _req(
            "POST", f"/tasks/{task_gid}/addDependents",
            data={"dependents": dependents},
        )
        return _single(payload)

    # ============================================================
    # Tier 6: Subtasks (3 tools)
    # ============================================================

    @mcp.tool()
    async def asana_create_subtask(
        parent_task_gid: str,
        name: str,
        assignee: str | None = None,
        notes: str | None = None,
        due_on: str | None = None,
        completed: bool | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Create a subtask under a parent task.
        Args:
            parent_task_gid: Parent task GID
            name: Subtask name
            assignee: Assignee GID/email/"me"
            notes: Plain-text notes
            due_on: Due date YYYY-MM-DD
            completed: Completion flag
            opt_fields: Comma-separated fields to expand
        """
        body = _clean({
            "name": name, "assignee": assignee, "notes": notes,
            "due_on": due_on, "completed": completed,
        })
        payload, _ = await _req(
            "POST", f"/tasks/{parent_task_gid}/subtasks", data=body,
            params={"opt_fields": opt_fields},
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_list_subtasks(
        task_gid: str,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List subtasks of a task.
        Args:
            task_gid: Parent task GID
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        payload, nxt = await _req(
            "GET", f"/tasks/{task_gid}/subtasks",
            params={"limit": limit, "offset": offset, "opt_fields": opt_fields},
        )
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_set_task_parent(
        task_gid: str,
        parent: str | None,
        insert_before: str | None = None,
        insert_after: str | None = None,
    ) -> str:
        """Set (or clear) a task's parent. Pass parent=null to detach.
        Args:
            task_gid: Task GID
            parent: New parent task GID, or null to detach
            insert_before: Sibling subtask GID to insert before
            insert_after: Sibling subtask GID to insert after
        """
        body: dict = {"parent": parent}
        if insert_before is not None:
            body["insert_before"] = insert_before
        if insert_after is not None:
            body["insert_after"] = insert_after
        payload, _ = await _req(
            "POST", f"/tasks/{task_gid}/setParent", data=body
        )
        return _single(payload)

    # ============================================================
    # Tier 7: Stories / Comments (5 tools)
    # ============================================================

    @mcp.tool()
    async def asana_create_story(
        task_gid: str,
        text: str | None = None,
        html_text: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Add a comment to a task. Provide text or html_text.
        Args:
            task_gid: Task GID
            text: Plain-text comment
            html_text: HTML comment (mutually exclusive with text)
            opt_fields: Comma-separated fields to expand
        """
        if not text and not html_text:
            raise ToolError("Provide text or html_text.")
        body = _clean({"text": text, "html_text": html_text})
        payload, _ = await _req(
            "POST", f"/tasks/{task_gid}/stories", data=body,
            params={"opt_fields": opt_fields},
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_get_story(
        story_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get a story by GID.
        Args:
            story_gid: Story GID
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/stories/{story_gid}", params={"opt_fields": opt_fields}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_list_stories(
        task_gid: str,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List stories (comments + activity) on a task.
        Args:
            task_gid: Task GID
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        payload, nxt = await _req(
            "GET", f"/tasks/{task_gid}/stories",
            params={"limit": limit, "offset": offset, "opt_fields": opt_fields},
        )
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_update_story(
        story_gid: str,
        text: str | None = None,
        html_text: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Edit a comment story (only comment stories you authored).
        Args:
            story_gid: Story GID
            text: New plain-text content
            html_text: New HTML content
            opt_fields: Comma-separated fields to expand
        """
        body = _clean({"text": text, "html_text": html_text})
        if not body:
            raise ToolError("Provide text or html_text.")
        payload, _ = await _req(
            "PUT", f"/stories/{story_gid}", data=body,
            params={"opt_fields": opt_fields},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_delete_story(story_gid: str) -> str:
        """Delete a comment story.
        Args:
            story_gid: Story GID
        """
        await _req("DELETE", f"/stories/{story_gid}")
        return _success(200, deleted=story_gid)

    # ============================================================
    # Tier 8: Tags (7 tools)
    # ============================================================

    @mcp.tool()
    async def asana_create_tag(
        name: str,
        workspace_gid: str | None = None,
        color: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Create a tag in a workspace.
        Args:
            name: Tag name
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID)
            color: Tag color (e.g. "dark-green")
            opt_fields: Comma-separated fields to expand
        """
        body = _clean({
            "name": name, "workspace": _workspace(workspace_gid), "color": color,
        })
        payload, _ = await _req(
            "POST", "/tags", data=body, params={"opt_fields": opt_fields}
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_get_tag(
        tag_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get a tag by GID.
        Args:
            tag_gid: Tag GID
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/tags/{tag_gid}", params={"opt_fields": opt_fields}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_update_tag(
        tag_gid: str,
        name: str | None = None,
        color: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Update a tag.
        Args:
            tag_gid: Tag GID
            name: New name
            color: New color
            opt_fields: Comma-separated fields to expand
        """
        body = _clean({"name": name, "color": color})
        if not body:
            raise ToolError("Provide at least one field to update.")
        payload, _ = await _req(
            "PUT", f"/tags/{tag_gid}", data=body,
            params={"opt_fields": opt_fields},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_delete_tag(tag_gid: str) -> str:
        """Delete a tag.
        Args:
            tag_gid: Tag GID
        """
        await _req("DELETE", f"/tags/{tag_gid}")
        return _success(200, deleted=tag_gid)

    @mcp.tool()
    async def asana_list_tags(
        workspace_gid: str | None = None,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List tags in a workspace.
        Args:
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID)
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        ws = _workspace(workspace_gid)
        payload, nxt = await _req(
            "GET", "/tags",
            params={"workspace": ws, "limit": limit, "offset": offset,
                    "opt_fields": opt_fields},
        )
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_add_tag_to_task(task_gid: str, tag_gid: str) -> str:
        """Add a tag to a task.
        Args:
            task_gid: Task GID
            tag_gid: Tag GID
        """
        payload, _ = await _req(
            "POST", f"/tasks/{task_gid}/addTag", data={"tag": tag_gid}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_remove_tag_from_task(task_gid: str, tag_gid: str) -> str:
        """Remove a tag from a task.
        Args:
            task_gid: Task GID
            tag_gid: Tag GID
        """
        payload, _ = await _req(
            "POST", f"/tasks/{task_gid}/removeTag", data={"tag": tag_gid}
        )
        return _single(payload)

    # ============================================================
    # Tier 9: Attachments (4 tools)
    # ============================================================

    @mcp.tool()
    async def asana_list_attachments(
        task_gid: str,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List attachments on a task.
        Args:
            task_gid: Parent task GID
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        payload, nxt = await _req(
            "GET", "/attachments",
            params={"parent": task_gid, "limit": limit, "offset": offset,
                    "opt_fields": opt_fields},
        )
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_get_attachment(
        attachment_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get attachment metadata by GID.
        Args:
            attachment_gid: Attachment GID
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/attachments/{attachment_gid}",
            params={"opt_fields": opt_fields},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_upload_attachment(
        task_gid: str, file_path: str, file_name: str | None = None
    ) -> str:
        """Upload a local file as an attachment on a task (multipart).
        Args:
            task_gid: Task GID to attach to
            file_path: Local filesystem path to the file
            file_name: Override filename (defaults to the file's basename)
        """
        path = Path(file_path)
        if not path.is_file():
            raise ToolError(f"File not found: {file_path}")
        name = file_name or path.name
        files = {"file": (name, path.read_bytes())}
        payload, _ = await _req(
            "POST", "/attachments", files=files, form={"parent": task_gid}
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_delete_attachment(attachment_gid: str) -> str:
        """Delete an attachment.
        Args:
            attachment_gid: Attachment GID
        """
        await _req("DELETE", f"/attachments/{attachment_gid}")
        return _success(200, deleted=attachment_gid)

    # ============================================================
    # Tier 10: Custom Fields (4 tools)
    # ============================================================

    @mcp.tool()
    async def asana_list_custom_fields(
        workspace_gid: str | None = None,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List custom field definitions in a workspace.
        Args:
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID)
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        ws = _workspace(workspace_gid)
        payload, nxt = await _req(
            "GET", f"/workspaces/{ws}/custom_fields",
            params={"limit": limit, "offset": offset, "opt_fields": opt_fields},
        )
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_get_custom_field(
        custom_field_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get a custom field definition by GID.
        Args:
            custom_field_gid: Custom field GID
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/custom_fields/{custom_field_gid}",
            params={"opt_fields": opt_fields},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_create_custom_field(
        name: str,
        field_type: str,
        workspace_gid: str | None = None,
        enum_options: list[str] | None = None,
        precision: int | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Create a custom field in a workspace.
        Args:
            name: Field name
            field_type: text/number/enum/multi_enum/date/people
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID)
            enum_options: Option names (for enum/multi_enum)
            precision: Decimal precision (for number)
            opt_fields: Comma-separated fields to expand
        """
        body: dict = {
            "workspace": _workspace(workspace_gid),
            "name": name,
            "resource_subtype": field_type,
        }
        if enum_options:
            body["enum_options"] = [{"name": o} for o in enum_options]
        if precision is not None:
            body["precision"] = precision
        payload, _ = await _req(
            "POST", "/custom_fields", data=body,
            params={"opt_fields": opt_fields},
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_set_task_custom_field(
        task_gid: str,
        custom_field_gid: str,
        value: str | int | float | list[str] | None,
        opt_fields: str | None = None,
    ) -> str:
        """Set one custom field value on a task.
        Args:
            task_gid: Task GID
            custom_field_gid: Custom field GID
            value: Option GID (enum), list of option GIDs (multi_enum),
                or raw value (text/number/date); null clears the field
            opt_fields: Comma-separated fields to expand
        """
        body = {"custom_fields": {custom_field_gid: value}}
        payload, _ = await _req(
            "PUT", f"/tasks/{task_gid}", data=body,
            params={"opt_fields": opt_fields},
        )
        return _single(payload)

    # ============================================================
    # Tier 11: Status Updates (4 tools)
    # ============================================================

    @mcp.tool()
    async def asana_create_status_update(
        parent_gid: str,
        status_type: str,
        text: str | None = None,
        html_text: str | None = None,
        title: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Create a status update on a project/portfolio/goal.
        Args:
            parent_gid: Project, portfolio, or goal GID
            status_type: on_track/at_risk/off_track/on_hold/complete
            text: Plain-text body
            html_text: HTML body (mutually exclusive with text)
            title: Status update title
            opt_fields: Comma-separated fields to expand
        """
        if not text and not html_text:
            raise ToolError("Provide text or html_text.")
        body = _clean({
            "parent": parent_gid, "status_type": status_type,
            "text": text, "html_text": html_text, "title": title,
        })
        payload, _ = await _req(
            "POST", "/status_updates", data=body,
            params={"opt_fields": opt_fields},
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_get_status_update(
        status_update_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get a status update by GID.
        Args:
            status_update_gid: Status update GID
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/status_updates/{status_update_gid}",
            params={"opt_fields": opt_fields},
        )
        return _single(payload)

    @mcp.tool()
    async def asana_list_status_updates(
        parent_gid: str,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List status updates on a project/portfolio/goal.
        Args:
            parent_gid: Project, portfolio, or goal GID
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        payload, nxt = await _req(
            "GET", "/status_updates",
            params={"parent": parent_gid, "limit": limit, "offset": offset,
                    "opt_fields": opt_fields},
        )
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_delete_status_update(status_update_gid: str) -> str:
        """Delete a status update.
        Args:
            status_update_gid: Status update GID
        """
        await _req("DELETE", f"/status_updates/{status_update_gid}")
        return _success(200, deleted=status_update_gid)

    # ============================================================
    # Tier 12: Webhooks (4 tools)
    # ============================================================

    @mcp.tool()
    async def asana_create_webhook(
        resource_gid: str,
        target_url: str,
        filters: list[dict] | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """Create a webhook on a resource (task/project/etc.).
        Args:
            resource_gid: Resource GID to watch
            target_url: HTTPS endpoint to receive events (must echo X-Hook-Secret)
            filters: Optional list of filter objects
            opt_fields: Comma-separated fields to expand
        """
        body = _clean({
            "resource": resource_gid, "target": target_url, "filters": filters,
        })
        payload, _ = await _req(
            "POST", "/webhooks", data=body, params={"opt_fields": opt_fields}
        )
        return _single(payload, 201)

    @mcp.tool()
    async def asana_get_webhook(
        webhook_gid: str, opt_fields: str | None = None
    ) -> str:
        """Get a webhook by GID.
        Args:
            webhook_gid: Webhook GID
            opt_fields: Comma-separated fields to expand
        """
        payload, _ = await _req(
            "GET", f"/webhooks/{webhook_gid}", params={"opt_fields": opt_fields}
        )
        return _single(payload)

    @mcp.tool()
    async def asana_list_webhooks(
        workspace_gid: str | None = None,
        resource_gid: str | None = None,
        limit: int | None = None,
        offset: str | None = None,
        opt_fields: str | None = None,
    ) -> str:
        """List webhooks in a workspace (workspace is required by the API).
        Args:
            workspace_gid: Workspace GID (defaults to ASANA_DEFAULT_WORKSPACE_ID;
                a workspace is mandatory for this endpoint)
            resource_gid: Filter to a single resource
            limit: Max results per page
            offset: Pagination offset token
            opt_fields: Comma-separated fields to expand
        """
        ws = _workspace(workspace_gid)
        payload, nxt = await _req(
            "GET", "/webhooks",
            params={"workspace": ws, "resource": resource_gid, "limit": limit,
                    "offset": offset, "opt_fields": opt_fields},
        )
        return _list(payload, nxt)

    @mcp.tool()
    async def asana_delete_webhook(webhook_gid: str) -> str:
        """Delete a webhook.
        Args:
            webhook_gid: Webhook GID
        """
        await _req("DELETE", f"/webhooks/{webhook_gid}")
        return _success(200, deleted=webhook_gid)
```

---

## 4. tests/test_asana_tool.py (complete)

Uses `respx` to mock httpx, asserting both the endpoint hit AND the request body envelope (`{"data": {...}}`) — matching the repo's L2 contract-test discipline. Every one of the 67 tools is exercised, plus error-code coverage (400/402/404/429), default-workspace fallback, `_clean` None-drop, multipart upload, list_tasks scope rules, and all three custom-field value types (enum/multi_enum/number).

```python
"""Tests for Asana integration — 67 tools across 12 tiers."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.asana_tool import register_tools

BASE = "https://app.asana.com/api/1.0"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


def _body(route) -> dict:
    return json.loads(route.calls.last.request.content)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.asana_tool.ASANA_ACCESS_TOKEN", "pat_test"), \
         patch("mcp_toolbox.tools.asana_tool.ASANA_DEFAULT_WORKSPACE_ID", "111"), \
         patch("mcp_toolbox.tools.asana_tool._client", None):
        register_tools(mcp)
        yield mcp


def _data(obj):
    return httpx.Response(200, json={"data": obj})


def _data_list(items, next_page=None):
    body = {"data": items}
    if next_page is not None:
        body["next_page"] = next_page
    return httpx.Response(200, json=body)


# ---------------- Auth / error handling ----------------

@pytest.mark.asyncio
async def test_missing_token():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.asana_tool.ASANA_ACCESS_TOKEN", None), \
         patch("mcp_toolbox.tools.asana_tool._client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="ASANA_ACCESS_TOKEN"):
            await mcp.call_tool("asana_list_workspaces", {})


@pytest.mark.asyncio
async def test_missing_default_workspace():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.asana_tool.ASANA_ACCESS_TOKEN", "pat"), \
         patch("mcp_toolbox.tools.asana_tool.ASANA_DEFAULT_WORKSPACE_ID", None), \
         patch("mcp_toolbox.tools.asana_tool._client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="workspace"):
            await mcp.call_tool("asana_list_tags", {})


@pytest.mark.asyncio
@respx.mock
async def test_error_429(server):
    respx.get(f"{BASE}/workspaces").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "5"}))
    with pytest.raises(Exception, match="rate limit"):
        await server.call_tool("asana_list_workspaces", {})


@pytest.mark.asyncio
@respx.mock
async def test_error_envelope(server):
    respx.get(f"{BASE}/tasks/bad").mock(return_value=httpx.Response(
        400, json={"errors": [{"message": "Not a valid task"}]}))
    with pytest.raises(Exception, match="Not a valid task"):
        await server.call_tool("asana_get_task", {"task_gid": "bad"})


@pytest.mark.asyncio
@respx.mock
async def test_error_402_paid_feature(server):
    # Search and some custom fields require a paid plan → 402.
    respx.get(f"{BASE}/workspaces/111/tasks/search").mock(
        return_value=httpx.Response(
            402, json={"errors": [{"message": "upgrade required"}]}))
    with pytest.raises(Exception, match="upgrade required"):
        await server.call_tool("asana_search_tasks", {"text": "x"})


@pytest.mark.asyncio
@respx.mock
async def test_error_404(server):
    respx.get(f"{BASE}/projects/missing").mock(
        return_value=httpx.Response(
            404, json={"errors": [{"message": "project: Not Found"}]}))
    with pytest.raises(Exception, match="Not Found"):
        await server.call_tool("asana_get_project", {"project_gid": "missing"})


# ---------------- Tier 1: Workspaces, Users & Jobs ----------------

@pytest.mark.asyncio
@respx.mock
async def test_list_workspaces(server):
    route = respx.get(f"{BASE}/workspaces").mock(
        return_value=_data_list([{"gid": "1"}], {"offset": "ofs"}))
    out = _r(await server.call_tool("asana_list_workspaces", {"limit": 50}))
    assert route.calls.last.request.url.params["limit"] == "50"
    assert out["count"] == 1
    assert out["next_offset"] == "ofs"


@pytest.mark.asyncio
@respx.mock
async def test_get_workspace_default(server):
    respx.get(f"{BASE}/workspaces/111").mock(return_value=_data({"gid": "111"}))
    out = _r(await server.call_tool("asana_get_workspace", {}))
    assert out["data"]["gid"] == "111"


@pytest.mark.asyncio
@respx.mock
async def test_get_me(server):
    respx.get(f"{BASE}/users/me").mock(return_value=_data({"gid": "u1"}))
    out = _r(await server.call_tool("asana_get_me", {}))
    assert out["data"]["gid"] == "u1"


@pytest.mark.asyncio
@respx.mock
async def test_list_users(server):
    respx.get(f"{BASE}/workspaces/111/users").mock(
        return_value=_data_list([{"gid": "u1"}]))
    out = _r(await server.call_tool("asana_list_users", {}))
    assert out["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_user(server):
    respx.get(f"{BASE}/users/u9").mock(return_value=_data({"gid": "u9"}))
    out = _r(await server.call_tool("asana_get_user", {"user_gid": "u9"}))
    assert out["data"]["gid"] == "u9"


@pytest.mark.asyncio
@respx.mock
async def test_get_job(server):
    respx.get(f"{BASE}/jobs/j1").mock(
        return_value=_data({"gid": "j1", "status": "succeeded"}))
    out = _r(await server.call_tool("asana_get_job", {"job_gid": "j1"}))
    assert out["data"]["status"] == "succeeded"


# ---------------- Tier 2: Teams ----------------

@pytest.mark.asyncio
@respx.mock
async def test_list_teams(server):
    respx.get(f"{BASE}/workspaces/111/teams").mock(
        return_value=_data_list([{"gid": "t1"}]))
    out = _r(await server.call_tool("asana_list_teams", {}))
    assert out["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_team(server):
    respx.get(f"{BASE}/teams/t1").mock(return_value=_data({"gid": "t1"}))
    out = _r(await server.call_tool("asana_get_team", {"team_gid": "t1"}))
    assert out["data"]["gid"] == "t1"


@pytest.mark.asyncio
@respx.mock
async def test_add_user_to_team(server):
    route = respx.post(f"{BASE}/teams/t1/addUser").mock(return_value=_data({}))
    await server.call_tool("asana_add_user_to_team",
                           {"team_gid": "t1", "user": "me"})
    assert _body(route) == {"data": {"user": "me"}}


@pytest.mark.asyncio
@respx.mock
async def test_remove_user_from_team(server):
    route = respx.post(f"{BASE}/teams/t1/removeUser").mock(return_value=_data({}))
    await server.call_tool("asana_remove_user_from_team",
                           {"team_gid": "t1", "user": "u2"})
    assert _body(route) == {"data": {"user": "u2"}}


# ---------------- Tier 3: Projects ----------------

@pytest.mark.asyncio
@respx.mock
async def test_create_project(server):
    route = respx.post(f"{BASE}/projects").mock(return_value=_data({"gid": "p1"}))
    await server.call_tool("asana_create_project",
                           {"name": "Proj", "team_gid": "t1", "notes": "n"})
    body = _body(route)["data"]
    assert body["name"] == "Proj"
    assert body["workspace"] == "111"
    assert body["team"] == "t1"


@pytest.mark.asyncio
@respx.mock
async def test_get_project(server):
    respx.get(f"{BASE}/projects/p1").mock(return_value=_data({"gid": "p1"}))
    out = _r(await server.call_tool("asana_get_project", {"project_gid": "p1"}))
    assert out["data"]["gid"] == "p1"


@pytest.mark.asyncio
@respx.mock
async def test_update_project(server):
    route = respx.put(f"{BASE}/projects/p1").mock(return_value=_data({"gid": "p1"}))
    await server.call_tool("asana_update_project",
                           {"project_gid": "p1", "archived": True})
    assert _body(route) == {"data": {"archived": True}}


@pytest.mark.asyncio
async def test_update_project_requires_field(server):
    with pytest.raises(Exception, match="at least one"):
        await server.call_tool("asana_update_project", {"project_gid": "p1"})


@pytest.mark.asyncio
@respx.mock
async def test_delete_project(server):
    respx.delete(f"{BASE}/projects/p1").mock(return_value=httpx.Response(200, json={"data": {}}))
    out = _r(await server.call_tool("asana_delete_project", {"project_gid": "p1"}))
    assert out["deleted"] == "p1"


@pytest.mark.asyncio
@respx.mock
async def test_list_projects_team(server):
    route = respx.get(f"{BASE}/projects").mock(return_value=_data_list([]))
    await server.call_tool("asana_list_projects", {"team_gid": "t1"})
    assert route.calls.last.request.url.params["team"] == "t1"


@pytest.mark.asyncio
@respx.mock
async def test_list_projects_default_workspace(server):
    route = respx.get(f"{BASE}/projects").mock(return_value=_data_list([]))
    await server.call_tool("asana_list_projects", {})
    assert route.calls.last.request.url.params["workspace"] == "111"


@pytest.mark.asyncio
@respx.mock
async def test_duplicate_project(server):
    route = respx.post(f"{BASE}/projects/p1/duplicate").mock(
        return_value=_data({"gid": "j1", "resource_type": "job"}))
    out = _r(await server.call_tool("asana_duplicate_project",
                                    {"project_gid": "p1", "name": "Copy"}))
    assert _body(route)["data"]["name"] == "Copy"
    assert out["data"]["resource_type"] == "job"


@pytest.mark.asyncio
@respx.mock
async def test_project_task_counts(server):
    route = respx.get(f"{BASE}/projects/p1/task_counts").mock(
        return_value=_data({"num_tasks": 3}))
    await server.call_tool("asana_get_project_task_counts", {"project_gid": "p1"})
    assert "num_tasks" in route.calls.last.request.url.params["opt_fields"]


# ---------------- Tier 4: Sections ----------------

@pytest.mark.asyncio
@respx.mock
async def test_create_section(server):
    route = respx.post(f"{BASE}/projects/p1/sections").mock(
        return_value=_data({"gid": "s1"}))
    await server.call_tool("asana_create_section",
                           {"project_gid": "p1", "name": "To Do"})
    assert _body(route)["data"]["name"] == "To Do"


@pytest.mark.asyncio
@respx.mock
async def test_get_section(server):
    respx.get(f"{BASE}/sections/s1").mock(return_value=_data({"gid": "s1"}))
    out = _r(await server.call_tool("asana_get_section", {"section_gid": "s1"}))
    assert out["data"]["gid"] == "s1"


@pytest.mark.asyncio
@respx.mock
async def test_update_section(server):
    route = respx.put(f"{BASE}/sections/s1").mock(return_value=_data({"gid": "s1"}))
    await server.call_tool("asana_update_section",
                           {"section_gid": "s1", "name": "Doing"})
    assert _body(route) == {"data": {"name": "Doing"}}


@pytest.mark.asyncio
@respx.mock
async def test_delete_section(server):
    respx.delete(f"{BASE}/sections/s1").mock(return_value=httpx.Response(204))
    out = _r(await server.call_tool("asana_delete_section", {"section_gid": "s1"}))
    assert out["deleted"] == "s1"


@pytest.mark.asyncio
@respx.mock
async def test_list_sections(server):
    respx.get(f"{BASE}/projects/p1/sections").mock(
        return_value=_data_list([{"gid": "s1"}]))
    out = _r(await server.call_tool("asana_list_sections", {"project_gid": "p1"}))
    assert out["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_add_task_to_section(server):
    route = respx.post(f"{BASE}/sections/s1/addTask").mock(return_value=_data({}))
    await server.call_tool("asana_add_task_to_section",
                           {"section_gid": "s1", "task_gid": "k1"})
    assert _body(route) == {"data": {"task": "k1"}}


# ---------------- Tier 5: Tasks — Core ----------------

@pytest.mark.asyncio
@respx.mock
async def test_create_task_workspace_default(server):
    route = respx.post(f"{BASE}/tasks").mock(return_value=_data({"gid": "k1"}))
    await server.call_tool("asana_create_task", {"name": "Do thing"})
    body = _body(route)["data"]
    assert body["name"] == "Do thing"
    assert body["workspace"] == "111"


@pytest.mark.asyncio
@respx.mock
async def test_create_task_with_projects_omits_workspace(server):
    route = respx.post(f"{BASE}/tasks").mock(return_value=_data({"gid": "k1"}))
    await server.call_tool("asana_create_task",
                           {"name": "X", "projects": ["p1"]})
    body = _body(route)["data"]
    assert body["projects"] == ["p1"]
    assert "workspace" not in body


@pytest.mark.asyncio
@respx.mock
async def test_get_task(server):
    respx.get(f"{BASE}/tasks/k1").mock(return_value=_data({"gid": "k1"}))
    out = _r(await server.call_tool("asana_get_task", {"task_gid": "k1"}))
    assert out["data"]["gid"] == "k1"


@pytest.mark.asyncio
@respx.mock
async def test_update_task(server):
    route = respx.put(f"{BASE}/tasks/k1").mock(return_value=_data({"gid": "k1"}))
    await server.call_tool("asana_update_task",
                           {"task_gid": "k1", "completed": True})
    assert _body(route) == {"data": {"completed": True}}


@pytest.mark.asyncio
@respx.mock
async def test_delete_task(server):
    respx.delete(f"{BASE}/tasks/k1").mock(return_value=httpx.Response(204))
    out = _r(await server.call_tool("asana_delete_task", {"task_gid": "k1"}))
    assert out["deleted"] == "k1"


@pytest.mark.asyncio
async def test_list_tasks_requires_scope(server):
    with pytest.raises(Exception, match="exactly one"):
        await server.call_tool("asana_list_tasks", {})


@pytest.mark.asyncio
@respx.mock
async def test_list_tasks_assignee_adds_workspace(server):
    route = respx.get(f"{BASE}/tasks").mock(return_value=_data_list([]))
    await server.call_tool("asana_list_tasks", {"assignee": "me"})
    params = route.calls.last.request.url.params
    assert params["assignee"] == "me"
    assert params["workspace"] == "111"


@pytest.mark.asyncio
async def test_list_tasks_rejects_multiple_scopes(server):
    # Asana's GET /tasks rejects combined scopes (400); we fail fast instead.
    with pytest.raises(Exception, match="only one task scope"):
        await server.call_tool("asana_list_tasks",
                               {"assignee": "me", "project_gid": "p1"})


@pytest.mark.asyncio
@respx.mock
async def test_search_tasks(server):
    route = respx.get(f"{BASE}/workspaces/111/tasks/search").mock(
        return_value=_data_list([{"gid": "k1"}]))
    out = _r(await server.call_tool("asana_search_tasks",
                                    {"text": "bug", "assignee_any": "u1,u2"}))
    params = route.calls.last.request.url.params
    assert params["text"] == "bug"
    assert params["assignee.any"] == "u1,u2"
    assert "next_offset" not in out


@pytest.mark.asyncio
@respx.mock
async def test_duplicate_task(server):
    route = respx.post(f"{BASE}/tasks/k1/duplicate").mock(
        return_value=_data({"gid": "j1", "resource_type": "job"}))
    await server.call_tool("asana_duplicate_task",
                           {"task_gid": "k1", "name": "Copy"})
    assert _body(route)["data"]["name"] == "Copy"


@pytest.mark.asyncio
@respx.mock
async def test_add_task_to_project(server):
    route = respx.post(f"{BASE}/tasks/k1/addProject").mock(return_value=_data({}))
    await server.call_tool("asana_add_task_to_project",
                           {"task_gid": "k1", "project_gid": "p1",
                            "section": "s1"})
    body = _body(route)["data"]
    assert body == {"project": "p1", "section": "s1"}


@pytest.mark.asyncio
@respx.mock
async def test_remove_task_from_project(server):
    route = respx.post(f"{BASE}/tasks/k1/removeProject").mock(return_value=_data({}))
    await server.call_tool("asana_remove_task_from_project",
                           {"task_gid": "k1", "project_gid": "p1"})
    assert _body(route) == {"data": {"project": "p1"}}


@pytest.mark.asyncio
@respx.mock
async def test_add_task_followers(server):
    route = respx.post(f"{BASE}/tasks/k1/addFollowers").mock(return_value=_data({}))
    await server.call_tool("asana_add_task_followers",
                           {"task_gid": "k1", "followers": ["u1", "u2"]})
    assert _body(route) == {"data": {"followers": ["u1", "u2"]}}


@pytest.mark.asyncio
@respx.mock
async def test_remove_task_followers(server):
    route = respx.post(f"{BASE}/tasks/k1/removeFollowers").mock(return_value=_data({}))
    await server.call_tool("asana_remove_task_followers",
                           {"task_gid": "k1", "followers": ["u1"]})
    assert _body(route) == {"data": {"followers": ["u1"]}}


@pytest.mark.asyncio
@respx.mock
async def test_add_task_dependencies(server):
    route = respx.post(f"{BASE}/tasks/k1/addDependencies").mock(return_value=_data({}))
    await server.call_tool("asana_add_task_dependencies",
                           {"task_gid": "k1", "dependencies": ["k2"]})
    assert _body(route) == {"data": {"dependencies": ["k2"]}}


@pytest.mark.asyncio
@respx.mock
async def test_add_task_dependents(server):
    route = respx.post(f"{BASE}/tasks/k1/addDependents").mock(return_value=_data({}))
    await server.call_tool("asana_add_task_dependents",
                           {"task_gid": "k1", "dependents": ["k3"]})
    assert _body(route) == {"data": {"dependents": ["k3"]}}


# ---------------- Tier 6: Subtasks ----------------

@pytest.mark.asyncio
@respx.mock
async def test_create_subtask(server):
    route = respx.post(f"{BASE}/tasks/k1/subtasks").mock(
        return_value=_data({"gid": "k2"}))
    await server.call_tool("asana_create_subtask",
                           {"parent_task_gid": "k1", "name": "Sub"})
    assert _body(route)["data"]["name"] == "Sub"


@pytest.mark.asyncio
@respx.mock
async def test_list_subtasks(server):
    respx.get(f"{BASE}/tasks/k1/subtasks").mock(
        return_value=_data_list([{"gid": "k2"}]))
    out = _r(await server.call_tool("asana_list_subtasks", {"task_gid": "k1"}))
    assert out["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_set_task_parent(server):
    route = respx.post(f"{BASE}/tasks/k2/setParent").mock(return_value=_data({}))
    await server.call_tool("asana_set_task_parent",
                           {"task_gid": "k2", "parent": "k1"})
    assert _body(route) == {"data": {"parent": "k1"}}


@pytest.mark.asyncio
@respx.mock
async def test_set_task_parent_detach(server):
    route = respx.post(f"{BASE}/tasks/k2/setParent").mock(return_value=_data({}))
    await server.call_tool("asana_set_task_parent",
                           {"task_gid": "k2", "parent": None})
    assert _body(route) == {"data": {"parent": None}}


# ---------------- Tier 7: Stories ----------------

@pytest.mark.asyncio
@respx.mock
async def test_create_story(server):
    route = respx.post(f"{BASE}/tasks/k1/stories").mock(
        return_value=_data({"gid": "st1"}))
    await server.call_tool("asana_create_story",
                           {"task_gid": "k1", "text": "Hello"})
    assert _body(route) == {"data": {"text": "Hello"}}


@pytest.mark.asyncio
async def test_create_story_requires_text(server):
    with pytest.raises(Exception, match="text"):
        await server.call_tool("asana_create_story", {"task_gid": "k1"})


@pytest.mark.asyncio
@respx.mock
async def test_get_story(server):
    respx.get(f"{BASE}/stories/st1").mock(return_value=_data({"gid": "st1"}))
    out = _r(await server.call_tool("asana_get_story", {"story_gid": "st1"}))
    assert out["data"]["gid"] == "st1"


@pytest.mark.asyncio
@respx.mock
async def test_list_stories(server):
    respx.get(f"{BASE}/tasks/k1/stories").mock(
        return_value=_data_list([{"gid": "st1"}]))
    out = _r(await server.call_tool("asana_list_stories", {"task_gid": "k1"}))
    assert out["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_update_story(server):
    route = respx.put(f"{BASE}/stories/st1").mock(return_value=_data({"gid": "st1"}))
    await server.call_tool("asana_update_story",
                           {"story_gid": "st1", "text": "Edited"})
    assert _body(route) == {"data": {"text": "Edited"}}


@pytest.mark.asyncio
@respx.mock
async def test_delete_story(server):
    respx.delete(f"{BASE}/stories/st1").mock(return_value=httpx.Response(204))
    out = _r(await server.call_tool("asana_delete_story", {"story_gid": "st1"}))
    assert out["deleted"] == "st1"


# ---------------- Tier 8: Tags ----------------

@pytest.mark.asyncio
@respx.mock
async def test_create_tag(server):
    route = respx.post(f"{BASE}/tags").mock(return_value=_data({"gid": "tg1"}))
    await server.call_tool("asana_create_tag", {"name": "urgent"})
    body = _body(route)["data"]
    assert body["name"] == "urgent"
    assert body["workspace"] == "111"


@pytest.mark.asyncio
@respx.mock
async def test_get_tag(server):
    respx.get(f"{BASE}/tags/tg1").mock(return_value=_data({"gid": "tg1"}))
    out = _r(await server.call_tool("asana_get_tag", {"tag_gid": "tg1"}))
    assert out["data"]["gid"] == "tg1"


@pytest.mark.asyncio
@respx.mock
async def test_update_tag(server):
    route = respx.put(f"{BASE}/tags/tg1").mock(return_value=_data({"gid": "tg1"}))
    await server.call_tool("asana_update_tag",
                           {"tag_gid": "tg1", "color": "red"})
    assert _body(route) == {"data": {"color": "red"}}


@pytest.mark.asyncio
@respx.mock
async def test_delete_tag(server):
    respx.delete(f"{BASE}/tags/tg1").mock(return_value=httpx.Response(204))
    out = _r(await server.call_tool("asana_delete_tag", {"tag_gid": "tg1"}))
    assert out["deleted"] == "tg1"


@pytest.mark.asyncio
@respx.mock
async def test_list_tags(server):
    route = respx.get(f"{BASE}/tags").mock(return_value=_data_list([{"gid": "tg1"}]))
    await server.call_tool("asana_list_tags", {})
    assert route.calls.last.request.url.params["workspace"] == "111"


@pytest.mark.asyncio
@respx.mock
async def test_add_tag_to_task(server):
    route = respx.post(f"{BASE}/tasks/k1/addTag").mock(return_value=_data({}))
    await server.call_tool("asana_add_tag_to_task",
                           {"task_gid": "k1", "tag_gid": "tg1"})
    assert _body(route) == {"data": {"tag": "tg1"}}


@pytest.mark.asyncio
@respx.mock
async def test_remove_tag_from_task(server):
    route = respx.post(f"{BASE}/tasks/k1/removeTag").mock(return_value=_data({}))
    await server.call_tool("asana_remove_tag_from_task",
                           {"task_gid": "k1", "tag_gid": "tg1"})
    assert _body(route) == {"data": {"tag": "tg1"}}


# ---------------- Tier 9: Attachments ----------------

@pytest.mark.asyncio
@respx.mock
async def test_list_attachments(server):
    route = respx.get(f"{BASE}/attachments").mock(
        return_value=_data_list([{"gid": "a1"}]))
    await server.call_tool("asana_list_attachments", {"task_gid": "k1"})
    assert route.calls.last.request.url.params["parent"] == "k1"


@pytest.mark.asyncio
@respx.mock
async def test_get_attachment(server):
    respx.get(f"{BASE}/attachments/a1").mock(return_value=_data({"gid": "a1"}))
    out = _r(await server.call_tool("asana_get_attachment", {"attachment_gid": "a1"}))
    assert out["data"]["gid"] == "a1"


@pytest.mark.asyncio
@respx.mock
async def test_upload_attachment(server, tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("hi")
    route = respx.post(f"{BASE}/attachments").mock(return_value=_data({"gid": "a1"}))
    out = _r(await server.call_tool("asana_upload_attachment",
                                    {"task_gid": "k1", "file_path": str(f)}))
    req = route.calls.last.request
    assert b"k1" in req.content  # parent form field present
    assert out["data"]["gid"] == "a1"


@pytest.mark.asyncio
async def test_upload_attachment_missing_file(server):
    with pytest.raises(Exception, match="File not found"):
        await server.call_tool("asana_upload_attachment",
                               {"task_gid": "k1", "file_path": "/no/such"})


@pytest.mark.asyncio
@respx.mock
async def test_delete_attachment(server):
    respx.delete(f"{BASE}/attachments/a1").mock(return_value=httpx.Response(204))
    out = _r(await server.call_tool("asana_delete_attachment",
                                    {"attachment_gid": "a1"}))
    assert out["deleted"] == "a1"


# ---------------- Tier 10: Custom Fields ----------------

@pytest.mark.asyncio
@respx.mock
async def test_list_custom_fields(server):
    respx.get(f"{BASE}/workspaces/111/custom_fields").mock(
        return_value=_data_list([{"gid": "cf1"}]))
    out = _r(await server.call_tool("asana_list_custom_fields", {}))
    assert out["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_custom_field(server):
    respx.get(f"{BASE}/custom_fields/cf1").mock(return_value=_data({"gid": "cf1"}))
    out = _r(await server.call_tool("asana_get_custom_field",
                                    {"custom_field_gid": "cf1"}))
    assert out["data"]["gid"] == "cf1"


@pytest.mark.asyncio
@respx.mock
async def test_create_custom_field(server):
    route = respx.post(f"{BASE}/custom_fields").mock(return_value=_data({"gid": "cf1"}))
    await server.call_tool("asana_create_custom_field",
                           {"name": "Priority", "field_type": "enum",
                            "enum_options": ["Low", "High"]})
    body = _body(route)["data"]
    assert body["resource_subtype"] == "enum"
    assert body["enum_options"] == [{"name": "Low"}, {"name": "High"}]
    assert "type" not in body


@pytest.mark.asyncio
@respx.mock
async def test_set_task_custom_field(server):
    route = respx.put(f"{BASE}/tasks/k1").mock(return_value=_data({"gid": "k1"}))
    await server.call_tool("asana_set_task_custom_field",
                           {"task_gid": "k1", "custom_field_gid": "cf1",
                            "value": "opt9"})
    assert _body(route) == {"data": {"custom_fields": {"cf1": "opt9"}}}


@pytest.mark.asyncio
@respx.mock
async def test_set_task_custom_field_multi_enum(server):
    route = respx.put(f"{BASE}/tasks/k1").mock(return_value=_data({"gid": "k1"}))
    await server.call_tool("asana_set_task_custom_field",
                           {"task_gid": "k1", "custom_field_gid": "cf1",
                            "value": ["o1", "o2"]})
    assert _body(route) == {"data": {"custom_fields": {"cf1": ["o1", "o2"]}}}


@pytest.mark.asyncio
@respx.mock
async def test_set_task_custom_field_number(server):
    route = respx.put(f"{BASE}/tasks/k1").mock(return_value=_data({"gid": "k1"}))
    await server.call_tool("asana_set_task_custom_field",
                           {"task_gid": "k1", "custom_field_gid": "cf1",
                            "value": 42})
    assert _body(route) == {"data": {"custom_fields": {"cf1": 42}}}


# ---------------- Tier 11: Status Updates ----------------

@pytest.mark.asyncio
@respx.mock
async def test_create_status_update(server):
    route = respx.post(f"{BASE}/status_updates").mock(return_value=_data({"gid": "su1"}))
    await server.call_tool("asana_create_status_update",
                           {"parent_gid": "p1", "status_type": "on_track",
                            "text": "Going well"})
    body = _body(route)["data"]
    assert body["parent"] == "p1"
    assert body["status_type"] == "on_track"


@pytest.mark.asyncio
async def test_create_status_update_requires_text(server):
    with pytest.raises(Exception, match="text"):
        await server.call_tool("asana_create_status_update",
                               {"parent_gid": "p1", "status_type": "on_track"})


@pytest.mark.asyncio
@respx.mock
async def test_get_status_update(server):
    respx.get(f"{BASE}/status_updates/su1").mock(return_value=_data({"gid": "su1"}))
    out = _r(await server.call_tool("asana_get_status_update",
                                    {"status_update_gid": "su1"}))
    assert out["data"]["gid"] == "su1"


@pytest.mark.asyncio
@respx.mock
async def test_list_status_updates(server):
    route = respx.get(f"{BASE}/status_updates").mock(return_value=_data_list([]))
    await server.call_tool("asana_list_status_updates", {"parent_gid": "p1"})
    assert route.calls.last.request.url.params["parent"] == "p1"


@pytest.mark.asyncio
@respx.mock
async def test_delete_status_update(server):
    respx.delete(f"{BASE}/status_updates/su1").mock(return_value=httpx.Response(204))
    out = _r(await server.call_tool("asana_delete_status_update",
                                    {"status_update_gid": "su1"}))
    assert out["deleted"] == "su1"


# ---------------- Tier 12: Webhooks ----------------

@pytest.mark.asyncio
@respx.mock
async def test_create_webhook(server):
    route = respx.post(f"{BASE}/webhooks").mock(return_value=_data({"gid": "wh1"}))
    await server.call_tool("asana_create_webhook",
                           {"resource_gid": "k1",
                            "target_url": "https://x.test/hook"})
    body = _body(route)["data"]
    assert body["resource"] == "k1"
    assert body["target"] == "https://x.test/hook"


@pytest.mark.asyncio
@respx.mock
async def test_get_webhook(server):
    respx.get(f"{BASE}/webhooks/wh1").mock(return_value=_data({"gid": "wh1"}))
    out = _r(await server.call_tool("asana_get_webhook", {"webhook_gid": "wh1"}))
    assert out["data"]["gid"] == "wh1"


@pytest.mark.asyncio
@respx.mock
async def test_list_webhooks(server):
    route = respx.get(f"{BASE}/webhooks").mock(return_value=_data_list([]))
    await server.call_tool("asana_list_webhooks", {})
    assert route.calls.last.request.url.params["workspace"] == "111"


@pytest.mark.asyncio
@respx.mock
async def test_delete_webhook(server):
    respx.delete(f"{BASE}/webhooks/wh1").mock(return_value=httpx.Response(204))
    out = _r(await server.call_tool("asana_delete_webhook", {"webhook_gid": "wh1"}))
    assert out["deleted"] == "wh1"
```

---

## 5. CLAUDE.md changes

- Add to the source-layout block:
  `├── asana_tool.py          # 67 Asana tools (workspaces, projects, tasks, sections, stories, tags, custom fields, webhooks)`
- Add an "### Asana (asana_tool.py) — 67 tools" subsection under Integrations mirroring the tier breakdown, config (`ASANA_ACCESS_TOKEN`, `ASANA_DEFAULT_WORKSPACE_ID`), auth (PAT Bearer), and the `{"data": {...}}` envelope note.

---

## 6. Verification steps (implementation)

```bash
uv run pytest tests/test_asana_tool.py -q     # new tests pass
uv run pytest -q                              # full regression
uv run ruff check src/ tests/                 # lint
uv run pyright src/mcp_toolbox/tools/asana_tool.py  # type check
```

## Risk notes / decisions
- **`opt_fields` booleans:** httpx serializes `True`/`False` query params to `"true"`/`"false"`, matching Asana's expectation.
- **`set_task_parent(parent=None)`** intentionally sends `{"parent": null}` (not cleaned) to detach — covered by a dedicated test.
- **`set_task_custom_field`** does not clean the value, so passing `None` clears the field (Asana semantics).
- **Multipart upload** is the only non-JSON-envelope request; `_req` routes `files`+`form` to httpx `files=`/`data=`.
- **pyright:** all tools are fully typed; this module is NOT added to the pyright exclude list (unlike msal/sendgrid modules).
