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
