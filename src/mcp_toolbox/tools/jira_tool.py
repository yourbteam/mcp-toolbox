"""Jira Cloud integration — issues, projects, boards, sprints, worklogs."""

import base64
import json
import logging
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import JIRA_API_TOKEN, JIRA_BASE_URL, JIRA_EMAIL

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if not JIRA_BASE_URL or not JIRA_EMAIL or not JIRA_API_TOKEN:
        raise ToolError(
            "Jira credentials not configured. Set JIRA_BASE_URL, "
            "JIRA_EMAIL, and JIRA_API_TOKEN."
        )
    if _client is None:
        creds = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
        _client = httpx.AsyncClient(
            base_url=JIRA_BASE_URL.rstrip("/"),
            headers={"Authorization": f"Basic {creds}"},
            timeout=30.0,
        )
    return _client


def _success(sc: int, **kw) -> str:
    return json.dumps({"status": "success", "status_code": sc, **kw})


def _adf(text: str) -> dict:
    """Convert plain text to minimal ADF."""
    return {
        "type": "doc", "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


async def _req(method: str, path: str, **kwargs) -> dict | list:
    """Platform API request (/rest/api/3/)."""
    client = _get_client()
    try:
        response = await client.request(method, f"/rest/api/3{path}", **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"Jira request failed: {e}") from e
    if response.status_code == 429:
        ra = response.headers.get("Retry-After", "unknown")
        raise ToolError(f"Jira rate limit exceeded. Retry after {ra}s.")
    if response.status_code >= 400:
        try:
            err = response.json()
            msgs = err.get("errorMessages", [])
            errs = err.get("errors", {})
            msg = "; ".join(msgs) if msgs else json.dumps(errs) if errs else response.text
        except Exception:
            msg = response.text
        raise ToolError(f"Jira error ({response.status_code}): {msg}")
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


async def _agile(method: str, path: str, **kwargs) -> dict | list:
    """Agile API request (/rest/agile/1.0/)."""
    client = _get_client()
    try:
        response = await client.request(method, f"/rest/agile/1.0{path}", **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"Jira Agile request failed: {e}") from e
    if response.status_code == 429:
        ra = response.headers.get("Retry-After", "unknown")
        raise ToolError(f"Jira rate limit exceeded. Retry after {ra}s.")
    if response.status_code >= 400:
        try:
            msg = response.json().get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(f"Jira Agile error ({response.status_code}): {msg}")
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def register_tools(mcp: FastMCP) -> None:
    if not JIRA_BASE_URL:
        logger.warning("JIRA_BASE_URL not set — Jira tools will fail.")

    # === TIER 1: ISSUE MANAGEMENT ===

    @mcp.tool()
    async def jira_create_issue(
        project_key: str, summary: str, issue_type: str,
        description: str | None = None, assignee_account_id: str | None = None,
        priority: str | None = None, labels: list[str] | None = None,
        components: list[str] | None = None, parent_key: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Create a Jira issue.
        Args:
            project_key: Project key (e.g., PROJ)
            summary: Issue summary
            issue_type: Issue type (Task, Bug, Story, Epic)
            description: Description (plain text)
            assignee_account_id: Assignee account ID
            priority: Priority name (High, Medium, Low)
            labels: Labels
            components: Component names
            parent_key: Parent issue key (for subtasks)
            extra_fields: Additional fields
        """
        fields: dict = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        if description:
            fields["description"] = _adf(description)
        if assignee_account_id:
            fields["assignee"] = {"accountId": assignee_account_id}
        if priority:
            fields["priority"] = {"name": priority}
        if labels:
            fields["labels"] = labels
        if components:
            fields["components"] = [{"name": c} for c in components]
        if parent_key:
            fields["parent"] = {"key": parent_key}
        if extra_fields:
            fields.update(extra_fields)
        data = await _req("POST", "/issue", json={"fields": fields})
        return _success(201, data=data)

    @mcp.tool()
    async def jira_get_issue(
        issue_key: str, fields: str | None = None, expand: str | None = None,
    ) -> str:
        """Get a Jira issue.
        Args:
            issue_key: Issue key (e.g., PROJ-123)
            fields: Comma-separated fields
            expand: Comma-separated expansions
        """
        params = {}
        if fields:
            params["fields"] = fields
        if expand:
            params["expand"] = expand
        data = await _req("GET", f"/issue/{issue_key}", params=params)
        return _success(200, data=data)

    @mcp.tool()
    async def jira_update_issue(
        issue_key: str, summary: str | None = None,
        description: str | None = None, assignee_account_id: str | None = None,
        priority: str | None = None, labels: list[str] | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Update a Jira issue.
        Args:
            issue_key: Issue key
            summary: New summary
            description: New description
            assignee_account_id: New assignee
            priority: New priority
            labels: New labels
            extra_fields: Additional fields
        """
        f: dict = {}
        if summary:
            f["summary"] = summary
        if description:
            f["description"] = _adf(description)
        if assignee_account_id:
            f["assignee"] = {"accountId": assignee_account_id}
        if priority:
            f["priority"] = {"name": priority}
        if labels is not None:
            f["labels"] = labels
        if extra_fields:
            f.update(extra_fields)
        if not f:
            raise ToolError("At least one field to update must be provided.")
        await _req("PUT", f"/issue/{issue_key}", json={"fields": f})
        return _success(204, message="Issue updated")

    @mcp.tool()
    async def jira_delete_issue(issue_key: str) -> str:
        """Delete a Jira issue.
        Args:
            issue_key: Issue key
        """
        await _req("DELETE", f"/issue/{issue_key}")
        return _success(204, deleted=issue_key)

    @mcp.tool()
    async def jira_search_issues(
        jql: str, fields: list[str] | None = None,
        max_results: int = 50, next_page_token: str | None = None,
    ) -> str:
        """Search Jira issues using JQL.
        Args:
            jql: JQL query string
            fields: Fields to return
            max_results: Max results (default 50)
            next_page_token: Pagination token
        """
        body: dict = {"jql": jql, "maxResults": max_results}
        if fields:
            body["fields"] = fields
        if next_page_token:
            body["nextPageToken"] = next_page_token
        data = await _req("POST", "/search/jql", json=body)
        issues = data.get("issues", []) if isinstance(data, dict) else data
        npt = data.get("nextPageToken") if isinstance(data, dict) else None
        return _success(200, data=issues, count=len(issues), next_page_token=npt)

    @mcp.tool()
    async def jira_transition_issue(issue_key: str, transition_id: str) -> str:
        """Transition a Jira issue to a new status.
        Args:
            issue_key: Issue key
            transition_id: Transition ID (from jira_list_transitions)
        """
        await _req("POST", f"/issue/{issue_key}/transitions",
                    json={"transition": {"id": transition_id}})
        return _success(204, message="Issue transitioned")

    @mcp.tool()
    async def jira_list_transitions(issue_key: str) -> str:
        """List available transitions for an issue.
        Args:
            issue_key: Issue key
        """
        data = await _req("GET", f"/issue/{issue_key}/transitions")
        transitions = data.get("transitions", []) if isinstance(data, dict) else data
        return _success(200, data=transitions, count=len(transitions))

    @mcp.tool()
    async def jira_assign_issue(issue_key: str, account_id: str) -> str:
        """Assign a Jira issue.
        Args:
            issue_key: Issue key
            account_id: Assignee account ID
        """
        await _req("PUT", f"/issue/{issue_key}/assignee",
                    json={"accountId": account_id})
        return _success(204, message="Issue assigned")

    @mcp.tool()
    async def jira_add_comment(issue_key: str, body: str) -> str:
        """Add a comment to a Jira issue.
        Args:
            issue_key: Issue key
            body: Comment text (converted to ADF)
        """
        data = await _req("POST", f"/issue/{issue_key}/comment",
                          json={"body": _adf(body)})
        return _success(201, data=data)

    @mcp.tool()
    async def jira_list_comments(
        issue_key: str, start_at: int = 0, max_results: int = 50,
    ) -> str:
        """List comments on a Jira issue.
        Args:
            issue_key: Issue key
            start_at: Start index
            max_results: Max results
        """
        data = await _req("GET", f"/issue/{issue_key}/comment",
                          params={"startAt": str(start_at), "maxResults": str(max_results)})
        comments = data.get("comments", []) if isinstance(data, dict) else data
        return _success(200, data=comments, count=len(comments))

    @mcp.tool()
    async def jira_update_comment(
        issue_key: str, comment_id: str, body: str,
    ) -> str:
        """Update a comment on a Jira issue.
        Args:
            issue_key: Issue key
            comment_id: Comment ID
            body: New comment text (converted to ADF)
        """
        data = await _req("PUT", f"/issue/{issue_key}/comment/{comment_id}",
                          json={"body": _adf(body)})
        return _success(200, data=data)

    @mcp.tool()
    async def jira_delete_comment(issue_key: str, comment_id: str) -> str:
        """Delete a comment from a Jira issue.
        Args:
            issue_key: Issue key
            comment_id: Comment ID
        """
        await _req("DELETE", f"/issue/{issue_key}/comment/{comment_id}")
        return _success(204, message="Comment deleted")

    @mcp.tool()
    async def jira_add_attachment(issue_key: str, file_path: str) -> str:
        """Add an attachment to a Jira issue.
        Args:
            issue_key: Issue key
            file_path: Local file path
        """
        fp = Path(file_path)
        if not fp.is_file():
            raise ToolError(f"File not found: {file_path}")
        client = _get_client()
        try:
            with open(fp, "rb") as f:
                response = await client.post(
                    f"/rest/api/3/issue/{issue_key}/attachments",
                    files={"file": (fp.name, f)},
                    headers={"X-Atlassian-Token": "no-check"},
                )
        except httpx.HTTPError as e:
            raise ToolError(f"Attachment upload failed: {e}") from e
        if response.status_code >= 400:
            raise ToolError(f"Attachment error ({response.status_code}): {response.text}")
        return _success(200, data=response.json())

    @mcp.tool()
    async def jira_list_attachments(issue_key: str) -> str:
        """List attachments on a Jira issue.
        Args:
            issue_key: Issue key
        """
        data = await _req("GET", f"/issue/{issue_key}", params={"fields": "attachment"})
        atts = data.get("fields", {}).get("attachment", []) if isinstance(data, dict) else []
        return _success(200, data=atts, count=len(atts))

    @mcp.tool()
    async def jira_delete_attachment(attachment_id: str) -> str:
        """Delete an attachment.
        Args:
            attachment_id: Attachment ID
        """
        await _req("DELETE", f"/attachment/{attachment_id}")
        return _success(204, message="Attachment deleted")

    # === TIER 2: PROJECTS ===

    @mcp.tool()
    async def jira_list_projects(
        start_at: int = 0, max_results: int = 50,
    ) -> str:
        """List Jira projects.
        Args:
            start_at: Start index
            max_results: Max results
        """
        data = await _req("GET", "/project/search",
                          params={"startAt": str(start_at), "maxResults": str(max_results)})
        projects = data.get("values", []) if isinstance(data, dict) else data
        return _success(200, data=projects, count=len(projects))

    @mcp.tool()
    async def jira_get_project(project_key: str) -> str:
        """Get a Jira project.
        Args:
            project_key: Project key
        """
        data = await _req("GET", f"/project/{project_key}")
        return _success(200, data=data)

    # === TIER 3: BOARDS (Agile) ===

    @mcp.tool()
    async def jira_list_boards(
        start_at: int = 0, max_results: int = 50, name: str | None = None,
    ) -> str:
        """List Jira boards.
        Args:
            start_at: Start index
            max_results: Max results
            name: Filter by board name
        """
        params: dict = {"startAt": str(start_at), "maxResults": str(max_results)}
        if name:
            params["name"] = name
        data = await _agile("GET", "/board", params=params)
        boards = data.get("values", []) if isinstance(data, dict) else data
        return _success(200, data=boards, count=len(boards))

    @mcp.tool()
    async def jira_get_board(board_id: int) -> str:
        """Get a Jira board.
        Args:
            board_id: Board ID
        """
        data = await _agile("GET", f"/board/{board_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def jira_get_board_issues(
        board_id: int, start_at: int = 0, max_results: int = 50,
        jql: str | None = None,
    ) -> str:
        """Get issues on a board.
        Args:
            board_id: Board ID
            start_at: Start index
            max_results: Max results
            jql: Additional JQL filter
        """
        params: dict = {"startAt": str(start_at), "maxResults": str(max_results)}
        if jql:
            params["jql"] = jql
        data = await _agile("GET", f"/board/{board_id}/issue", params=params)
        issues = data.get("issues", []) if isinstance(data, dict) else data
        return _success(200, data=issues, count=len(issues))

    # === TIER 4: SPRINTS (Agile) ===

    @mcp.tool()
    async def jira_list_sprints(
        board_id: int, start_at: int = 0, max_results: int = 50,
        state: str | None = None,
    ) -> str:
        """List sprints for a board.
        Args:
            board_id: Board ID
            start_at: Start index
            max_results: Max results
            state: Filter: active, closed, future
        """
        params: dict = {"startAt": str(start_at), "maxResults": str(max_results)}
        if state:
            params["state"] = state
        data = await _agile("GET", f"/board/{board_id}/sprint", params=params)
        sprints = data.get("values", []) if isinstance(data, dict) else data
        return _success(200, data=sprints, count=len(sprints))

    @mcp.tool()
    async def jira_get_sprint(sprint_id: int) -> str:
        """Get a sprint.
        Args:
            sprint_id: Sprint ID
        """
        data = await _agile("GET", f"/sprint/{sprint_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def jira_get_sprint_issues(
        sprint_id: int, start_at: int = 0, max_results: int = 50,
    ) -> str:
        """Get issues in a sprint.
        Args:
            sprint_id: Sprint ID
            start_at: Start index
            max_results: Max results
        """
        params = {"startAt": str(start_at), "maxResults": str(max_results)}
        data = await _agile("GET", f"/sprint/{sprint_id}/issue", params=params)
        issues = data.get("issues", []) if isinstance(data, dict) else data
        return _success(200, data=issues, count=len(issues))

    @mcp.tool()
    async def jira_move_to_sprint(sprint_id: int, issue_keys: list[str]) -> str:
        """Move issues to a sprint.
        Args:
            sprint_id: Sprint ID
            issue_keys: Issue keys to move
        """
        await _agile("POST", f"/sprint/{sprint_id}/issue",
                      json={"issues": issue_keys})
        return _success(204, message="Issues moved to sprint")

    # === TIER 5: USERS ===

    @mcp.tool()
    async def jira_search_users(
        query: str, start_at: int = 0, max_results: int = 50,
    ) -> str:
        """Search Jira users.
        Args:
            query: Search query (name or email)
            start_at: Start index
            max_results: Max results
        """
        data = await _req("GET", "/user/search",
                          params={"query": query, "startAt": str(start_at),
                                  "maxResults": str(max_results)})
        users = data if isinstance(data, list) else data.get("values", [])
        return _success(200, data=users, count=len(users))

    @mcp.tool()
    async def jira_get_user(account_id: str) -> str:
        """Get a Jira user.
        Args:
            account_id: User account ID
        """
        data = await _req("GET", "/user", params={"accountId": account_id})
        return _success(200, data=data)

    # === TIER 6: METADATA ===

    @mcp.tool()
    async def jira_list_priorities() -> str:
        """List Jira issue priorities."""
        data = await _req("GET", "/priority/search")
        values = data.get("values", []) if isinstance(data, dict) else data
        return _success(200, data=values, count=len(values))

    @mcp.tool()
    async def jira_list_statuses(project_id: str | None = None) -> str:
        """List Jira statuses.
        Args:
            project_id: Filter by project ID (numeric)
        """
        params = {}
        if project_id:
            params["projectId"] = project_id
        data = await _req("GET", "/statuses/search", params=params)
        values = data.get("values", []) if isinstance(data, dict) else data
        return _success(200, data=values, count=len(values))

    # === TIER 7: WORKLOGS ===

    @mcp.tool()
    async def jira_add_worklog(
        issue_key: str, time_spent: str,
        started: str | None = None, comment: str | None = None,
    ) -> str:
        """Add a worklog to a Jira issue.
        Args:
            issue_key: Issue key
            time_spent: Time spent (e.g., 2h 30m)
            started: Start time (ISO datetime)
            comment: Work description
        """
        body: dict = {"timeSpent": time_spent}
        if started:
            body["started"] = started
        if comment:
            body["comment"] = _adf(comment)
        data = await _req("POST", f"/issue/{issue_key}/worklog", json=body)
        return _success(201, data=data)

    @mcp.tool()
    async def jira_list_worklogs(
        issue_key: str, start_at: int = 0, max_results: int = 50,
    ) -> str:
        """List worklogs on a Jira issue.
        Args:
            issue_key: Issue key
            start_at: Start index
            max_results: Max results
        """
        data = await _req("GET", f"/issue/{issue_key}/worklog",
                          params={"startAt": str(start_at), "maxResults": str(max_results)})
        worklogs = data.get("worklogs", []) if isinstance(data, dict) else data
        return _success(200, data=worklogs, count=len(worklogs))

    @mcp.tool()
    async def jira_update_worklog(
        issue_key: str, worklog_id: str,
        time_spent: str | None = None, started: str | None = None,
        comment: str | None = None,
    ) -> str:
        """Update a worklog.
        Args:
            issue_key: Issue key
            worklog_id: Worklog ID
            time_spent: New time spent
            started: New start time
            comment: New comment
        """
        body: dict = {}
        if time_spent:
            body["timeSpent"] = time_spent
        if started:
            body["started"] = started
        if comment:
            body["comment"] = _adf(comment)
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _req("PUT", f"/issue/{issue_key}/worklog/{worklog_id}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def jira_delete_worklog(issue_key: str, worklog_id: str) -> str:
        """Delete a worklog.
        Args:
            issue_key: Issue key
            worklog_id: Worklog ID
        """
        await _req("DELETE", f"/issue/{issue_key}/worklog/{worklog_id}")
        return _success(204, message="Worklog deleted")

    # === TIER 8: WATCHERS ===

    @mcp.tool()
    async def jira_get_watchers(issue_key: str) -> str:
        """Get watchers on a Jira issue.
        Args:
            issue_key: Issue key
        """
        data = await _req("GET", f"/issue/{issue_key}/watchers")
        watchers = data.get("watchers", []) if isinstance(data, dict) else data
        return _success(200, data=watchers, count=len(watchers))

    @mcp.tool()
    async def jira_add_watcher(issue_key: str, account_id: str) -> str:
        """Add a watcher to a Jira issue.
        Args:
            issue_key: Issue key
            account_id: User account ID
        """
        await _req("POST", f"/issue/{issue_key}/watchers",
                    content=json.dumps(account_id),
                    headers={"Content-Type": "application/json"})
        return _success(204, message="Watcher added")

    @mcp.tool()
    async def jira_remove_watcher(issue_key: str, account_id: str) -> str:
        """Remove a watcher from a Jira issue.
        Args:
            issue_key: Issue key
            account_id: User account ID
        """
        await _req("DELETE", f"/issue/{issue_key}/watchers",
                    params={"accountId": account_id})
        return _success(204, message="Watcher removed")

    # === TIER 9: ISSUE LINKS ===

    @mcp.tool()
    async def jira_create_issue_link(
        type_name: str, inward_issue_key: str, outward_issue_key: str,
    ) -> str:
        """Link two Jira issues.
        Args:
            type_name: Link type (e.g., Blocks, Duplicates)
            inward_issue_key: Inward issue key
            outward_issue_key: Outward issue key
        """
        body = {
            "type": {"name": type_name},
            "inwardIssue": {"key": inward_issue_key},
            "outwardIssue": {"key": outward_issue_key},
        }
        await _req("POST", "/issueLink", json=body)
        return _success(201, message="Issue link created")

    @mcp.tool()
    async def jira_delete_issue_link(link_id: str) -> str:
        """Delete an issue link.
        Args:
            link_id: Link ID
        """
        await _req("DELETE", f"/issueLink/{link_id}")
        return _success(204, message="Issue link deleted")

    @mcp.tool()
    async def jira_list_issue_link_types() -> str:
        """List available issue link types."""
        data = await _req("GET", "/issueLinkType")
        types = data.get("issueLinkTypes", []) if isinstance(data, dict) else data
        return _success(200, data=types, count=len(types))

    # === TIER 10: COMPONENTS ===

    @mcp.tool()
    async def jira_list_components(project_key: str) -> str:
        """List components in a Jira project.
        Args:
            project_key: Project key
        """
        data = await _req("GET", f"/project/{project_key}/component")
        comps = data if isinstance(data, list) else data.get("values", [])
        return _success(200, data=comps, count=len(comps))

    @mcp.tool()
    async def jira_create_component(
        project_key: str, name: str,
        description: str | None = None,
        lead_account_id: str | None = None,
    ) -> str:
        """Create a project component.
        Args:
            project_key: Project key
            name: Component name
            description: Description
            lead_account_id: Component lead
        """
        body: dict = {"project": project_key, "name": name}
        if description:
            body["description"] = description
        if lead_account_id:
            body["leadAccountId"] = lead_account_id
        data = await _req("POST", "/component", json=body)
        return _success(201, data=data)

    # === TIER 11: VERSIONS ===

    @mcp.tool()
    async def jira_list_versions(project_key: str) -> str:
        """List versions in a Jira project.
        Args:
            project_key: Project key
        """
        data = await _req("GET", f"/project/{project_key}/versions")
        versions = data if isinstance(data, list) else data.get("values", [])
        return _success(200, data=versions, count=len(versions))

    @mcp.tool()
    async def jira_create_version(
        project_id: str, name: str,
        description: str | None = None,
        start_date: str | None = None,
        release_date: str | None = None,
        released: bool | None = None,
    ) -> str:
        """Create a project version.
        Args:
            project_id: Numeric project ID
            name: Version name
            description: Description
            start_date: Start date (YYYY-MM-DD)
            release_date: Release date (YYYY-MM-DD)
            released: Whether released
        """
        body: dict = {"projectId": project_id, "name": name}
        if description:
            body["description"] = description
        if start_date:
            body["startDate"] = start_date
        if release_date:
            body["releaseDate"] = release_date
        if released is not None:
            body["released"] = released
        data = await _req("POST", "/version", json=body)
        return _success(201, data=data)

    # === TIER 12: LABELS ===

    @mcp.tool()
    async def jira_list_labels(
        start_at: int = 0, max_results: int = 50,
    ) -> str:
        """List Jira labels.
        Args:
            start_at: Start index
            max_results: Max results
        """
        data = await _req("GET", "/label",
                          params={"startAt": str(start_at), "maxResults": str(max_results)})
        labels = data.get("values", []) if isinstance(data, dict) else data
        return _success(200, data=labels, count=len(labels))

    # === TIER 13: BULK ===

    @mcp.tool()
    async def jira_bulk_create_issues(issues: list[dict]) -> str:
        """Bulk create Jira issues (max 50).
        Args:
            issues: List of issue create payloads (each with fields dict)
        """
        data = await _req("POST", "/issue/bulk",
                          json={"issueUpdates": issues})
        created = data.get("issues", []) if isinstance(data, dict) else data
        errors = data.get("errors", []) if isinstance(data, dict) else []
        return _success(201, data=created, count=len(created), errors=errors)
