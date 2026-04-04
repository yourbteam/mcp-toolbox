"""GitHub integration — repos, issues, PRs, branches, actions, search."""

import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import (
    GITHUB_DEFAULT_OWNER,
    GITHUB_DEFAULT_REPO,
    GITHUB_TOKEN,
)

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if not GITHUB_TOKEN:
        raise ToolError(
            "GITHUB_TOKEN is not configured. "
            "Set it in your environment or .env file."
        )
    if _client is None:
        _client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
    return _client


def _success(sc: int, **kw) -> str:  # noqa: ANN003
    return json.dumps(
        {"status": "success", "status_code": sc, **kw}
    )


def _list_result(
    data: list | dict, page: int, per_page: int
) -> str:
    items = data if isinstance(data, list) else []
    return _success(
        200, data=items, count=len(items),
        page=page, per_page=per_page,
    )


def _resolve_owner(owner: str | None = None) -> str:
    resolved = owner or GITHUB_DEFAULT_OWNER
    if not resolved:
        raise ToolError(
            "No owner provided. Either pass owner or "
            "set GITHUB_DEFAULT_OWNER in your environment."
        )
    return resolved


def _resolve_repo(repo: str | None = None) -> str:
    resolved = repo or GITHUB_DEFAULT_REPO
    if not resolved:
        raise ToolError(
            "No repo provided. Either pass repo or "
            "set GITHUB_DEFAULT_REPO in your environment."
        )
    return resolved


async def _req(
    method: str, path: str, **kwargs
) -> dict | list:
    client = _get_client()
    try:
        response = await client.request(
            method, path, **kwargs
        )
    except httpx.HTTPError as e:
        raise ToolError(
            f"GitHub API request failed: {e}"
        ) from e
    if response.status_code == 403:
        remaining = response.headers.get(
            "X-RateLimit-Remaining"
        )
        if remaining == "0":
            reset = response.headers.get(
                "X-RateLimit-Reset", "unknown"
            )
            raise ToolError(
                "GitHub rate limit exceeded. "
                f"Resets at Unix epoch: {reset}. "
                "Try again after the reset time."
            )
    if response.status_code == 429:
        retry_after = response.headers.get(
            "Retry-After", "unknown"
        )
        raise ToolError(
            "GitHub secondary rate limit hit. "
            f"Retry after: {retry_after}s."
        )
    if response.status_code >= 400:
        try:
            error_body = response.json()
            error_msg = error_body.get(
                "message", response.text
            )
        except Exception:
            error_msg = response.text
        raise ToolError(
            f"GitHub API error ({response.status_code})"
            f": {error_msg}"
        )
    if response.status_code == 204:
        return {}
    if response.status_code == 302:
        return {
            "redirect_url": response.headers.get(
                "Location", ""
            )
        }
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def register_tools(mcp: FastMCP) -> None:  # noqa: C901
    if not GITHUB_TOKEN:
        logger.warning(
            "GITHUB_TOKEN not set — GitHub tools "
            "will fail at invocation."
        )

    # ── Tier 1: Repositories (7) ─────────────────

    @mcp.tool()
    async def github_list_repos(
        owner: str | None = None,
        type: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List repos for authenticated user or a user/org.
        Args:
            owner: User or org (omit for your repos)
            type: all, owner, public, private, member
            sort: created, updated, pushed, full_name
            direction: asc or desc
            per_page: Results per page (max 100)
            page: Page number
        """
        params: dict = {
            "per_page": per_page, "page": page
        }
        if type is not None:
            params["type"] = type
        if sort is not None:
            params["sort"] = sort
        if direction is not None:
            params["direction"] = direction
        if owner is not None:
            path = f"/users/{owner}/repos"
        else:
            path = "/user/repos"
        data = await _req("GET", path, params=params)
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_get_repo(
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Get details for a specific repository.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req("GET", f"/repos/{o}/{r}")
        return _success(200, data=data)

    @mcp.tool()
    async def github_create_repo(
        name: str,
        description: str | None = None,
        private: bool | None = None,
        auto_init: bool | None = None,
        gitignore_template: str | None = None,
        license_template: str | None = None,
        org: str | None = None,
        has_issues: bool | None = None,
        has_projects: bool | None = None,
        has_wiki: bool | None = None,
    ) -> str:
        """Create a new repository.
        Args:
            name: Repository name
            description: Short description
            private: Whether repo is private
            auto_init: Initialize with README
            gitignore_template: e.g. Python, Node
            license_template: e.g. mit, apache-2.0
            org: Org name (creates org repo)
            has_issues: Enable issues
            has_projects: Enable projects
            has_wiki: Enable wiki
        """
        body: dict = {"name": name}
        if description is not None:
            body["description"] = description
        if private is not None:
            body["private"] = private
        if auto_init is not None:
            body["auto_init"] = auto_init
        if gitignore_template is not None:
            body["gitignore_template"] = (
                gitignore_template
            )
        if license_template is not None:
            body["license_template"] = license_template
        if has_issues is not None:
            body["has_issues"] = has_issues
        if has_projects is not None:
            body["has_projects"] = has_projects
        if has_wiki is not None:
            body["has_wiki"] = has_wiki
        if org is not None:
            path = f"/orgs/{org}/repos"
        else:
            path = "/user/repos"
        data = await _req("POST", path, json=body)
        return _success(201, data=data)

    @mcp.tool()
    async def github_update_repo(
        owner: str | None = None,
        repo: str | None = None,
        name: str | None = None,
        description: str | None = None,
        private: bool | None = None,
        default_branch: str | None = None,
        has_issues: bool | None = None,
        has_projects: bool | None = None,
        has_wiki: bool | None = None,
        archived: bool | None = None,
    ) -> str:
        """Update repository settings.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            name: New repository name
            description: New description
            private: Change visibility
            default_branch: Change default branch
            has_issues: Enable/disable issues
            has_projects: Enable/disable projects
            has_wiki: Enable/disable wiki
            archived: Archive or unarchive repo
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        body: dict = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if private is not None:
            body["private"] = private
        if default_branch is not None:
            body["default_branch"] = default_branch
        if has_issues is not None:
            body["has_issues"] = has_issues
        if has_projects is not None:
            body["has_projects"] = has_projects
        if has_wiki is not None:
            body["has_wiki"] = has_wiki
        if archived is not None:
            body["archived"] = archived
        data = await _req(
            "PATCH", f"/repos/{o}/{r}", json=body
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_delete_repo(
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Delete a repository. Requires admin access.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        await _req("DELETE", f"/repos/{o}/{r}")
        return _success(204, message="Repository deleted.")

    @mcp.tool()
    async def github_list_repo_topics(
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """List topics (tags) for a repository.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET", f"/repos/{o}/{r}/topics"
        )
        names = (
            data.get("names", [])
            if isinstance(data, dict) else data
        )
        return _success(200, data=names)

    @mcp.tool()
    async def github_list_repo_languages(
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """List languages used in a repo with byte counts.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET", f"/repos/{o}/{r}/languages"
        )
        return _success(200, data=data)

    # ── Tier 2: Issues (13) ──────────────────────

    @mcp.tool()
    async def github_create_issue(
        title: str,
        owner: str | None = None,
        repo: str | None = None,
        body: str | None = None,
        assignees: list[str] | None = None,
        labels: list[str] | None = None,
        milestone: int | None = None,
    ) -> str:
        """Create a new issue in a repository.
        Args:
            title: Issue title
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            body: Issue body (Markdown)
            assignees: Usernames to assign
            labels: Label names to apply
            milestone: Milestone number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {"title": title}
        if body is not None:
            payload["body"] = body
        if assignees is not None:
            payload["assignees"] = assignees
        if labels is not None:
            payload["labels"] = labels
        if milestone is not None:
            payload["milestone"] = milestone
        data = await _req(
            "POST", f"/repos/{o}/{r}/issues",
            json=payload,
        )
        return _success(201, data=data)

    @mcp.tool()
    async def github_get_issue(
        issue_number: int,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Get a single issue by number.
        Args:
            issue_number: Issue number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET", f"/repos/{o}/{r}/issues/{issue_number}"
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_update_issue(
        issue_number: int,
        owner: str | None = None,
        repo: str | None = None,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        state_reason: str | None = None,
        assignees: list[str] | None = None,
        labels: list[str] | None = None,
        milestone: int | None = None,
    ) -> str:
        """Update an existing issue.
        Args:
            issue_number: Issue number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            title: New title
            body: New body
            state: open or closed
            state_reason: completed, not_planned, reopened
            assignees: Replace assignees list
            labels: Replace labels list
            milestone: Milestone number (null to remove)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        if state_reason is not None:
            payload["state_reason"] = state_reason
        if assignees is not None:
            payload["assignees"] = assignees
        if labels is not None:
            payload["labels"] = labels
        if milestone is not None:
            payload["milestone"] = milestone
        data = await _req(
            "PATCH",
            f"/repos/{o}/{r}/issues/{issue_number}",
            json=payload,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_list_issues(
        owner: str | None = None,
        repo: str | None = None,
        state: str | None = None,
        assignee: str | None = None,
        labels: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        since: str | None = None,
        milestone: str | None = None,
        creator: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List issues for a repository with filters.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            state: open, closed, or all
            assignee: Filter by assignee; none or *
            labels: Comma-separated label names
            sort: created, updated, comments
            direction: asc or desc
            since: ISO 8601 timestamp
            milestone: Number, none, or *
            creator: Filter by creator username
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        params: dict = {
            "per_page": per_page, "page": page
        }
        if state is not None:
            params["state"] = state
        if assignee is not None:
            params["assignee"] = assignee
        if labels is not None:
            params["labels"] = labels
        if sort is not None:
            params["sort"] = sort
        if direction is not None:
            params["direction"] = direction
        if since is not None:
            params["since"] = since
        if milestone is not None:
            params["milestone"] = milestone
        if creator is not None:
            params["creator"] = creator
        data = await _req(
            "GET", f"/repos/{o}/{r}/issues",
            params=params,
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_add_issue_labels(
        issue_number: int,
        labels: list[str],
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Add labels to an issue (keeps existing).
        Args:
            issue_number: Issue number
            labels: Label names to add
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "POST",
            f"/repos/{o}/{r}/issues"
            f"/{issue_number}/labels",
            json={"labels": labels},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_remove_issue_label(
        issue_number: int,
        label: str,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Remove a single label from an issue.
        Args:
            issue_number: Issue number
            label: Label name to remove
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "DELETE",
            f"/repos/{o}/{r}/issues"
            f"/{issue_number}/labels/{label}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_add_issue_assignees(
        issue_number: int,
        assignees: list[str],
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Add assignees to an issue.
        Args:
            issue_number: Issue number
            assignees: Usernames to add
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "POST",
            f"/repos/{o}/{r}/issues"
            f"/{issue_number}/assignees",
            json={"assignees": assignees},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_list_issue_comments(
        issue_number: int,
        owner: str | None = None,
        repo: str | None = None,
        since: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List comments on an issue.
        Args:
            issue_number: Issue number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            since: ISO 8601 timestamp
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        params: dict = {
            "per_page": per_page, "page": page
        }
        if since is not None:
            params["since"] = since
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/issues"
            f"/{issue_number}/comments",
            params=params,
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_create_issue_comment(
        issue_number: int,
        body: str,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Create a comment on an issue.
        Args:
            issue_number: Issue number
            body: Comment body (Markdown)
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "POST",
            f"/repos/{o}/{r}/issues"
            f"/{issue_number}/comments",
            json={"body": body},
        )
        return _success(201, data=data)

    @mcp.tool()
    async def github_update_issue_comment(
        comment_id: int,
        body: str,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Update an existing issue comment.
        Args:
            comment_id: Comment ID
            body: New comment body (Markdown)
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "PATCH",
            f"/repos/{o}/{r}/issues"
            f"/comments/{comment_id}",
            json={"body": body},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_delete_issue_comment(
        comment_id: int,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Delete an issue comment.
        Args:
            comment_id: Comment ID
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        await _req(
            "DELETE",
            f"/repos/{o}/{r}/issues"
            f"/comments/{comment_id}",
        )
        return _success(204, message="Comment deleted.")

    @mcp.tool()
    async def github_lock_issue(
        issue_number: int,
        owner: str | None = None,
        repo: str | None = None,
        lock_reason: str | None = None,
    ) -> str:
        """Lock an issue conversation.
        Args:
            issue_number: Issue number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            lock_reason: off-topic, too heated,
                resolved, spam
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        body: dict = {}
        if lock_reason is not None:
            body["lock_reason"] = lock_reason
        await _req(
            "PUT",
            f"/repos/{o}/{r}/issues"
            f"/{issue_number}/lock",
            json=body,
        )
        return _success(204, message="Issue locked.")

    @mcp.tool()
    async def github_unlock_issue(
        issue_number: int,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Unlock an issue.
        Args:
            issue_number: Issue number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        await _req(
            "DELETE",
            f"/repos/{o}/{r}/issues"
            f"/{issue_number}/lock",
        )
        return _success(204, message="Issue unlocked.")

    # ── Tier 3: Pull Requests (9) ────────────────

    @mcp.tool()
    async def github_list_pulls(
        owner: str | None = None,
        repo: str | None = None,
        state: str | None = None,
        head: str | None = None,
        base: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List pull requests for a repository.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            state: open, closed, or all
            head: Filter by head (user:branch)
            base: Filter by base branch
            sort: created, updated, popularity,
                long-running
            direction: asc or desc
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        params: dict = {
            "per_page": per_page, "page": page
        }
        if state is not None:
            params["state"] = state
        if head is not None:
            params["head"] = head
        if base is not None:
            params["base"] = base
        if sort is not None:
            params["sort"] = sort
        if direction is not None:
            params["direction"] = direction
        data = await _req(
            "GET", f"/repos/{o}/{r}/pulls",
            params=params,
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_get_pull(
        pull_number: int,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Get a single pull request by number.
        Args:
            pull_number: Pull request number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/pulls/{pull_number}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_create_pull(
        title: str,
        head: str,
        base: str,
        owner: str | None = None,
        repo: str | None = None,
        body: str | None = None,
        draft: bool | None = None,
        maintainer_can_modify: bool | None = None,
    ) -> str:
        """Create a new pull request.
        Args:
            title: PR title
            head: Branch with changes (or user:branch)
            base: Branch to merge into
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            body: PR description (Markdown)
            draft: Create as draft PR
            maintainer_can_modify: Allow maintainer edits
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {
            "title": title, "head": head, "base": base
        }
        if body is not None:
            payload["body"] = body
        if draft is not None:
            payload["draft"] = draft
        if maintainer_can_modify is not None:
            payload["maintainer_can_modify"] = (
                maintainer_can_modify
            )
        data = await _req(
            "POST", f"/repos/{o}/{r}/pulls",
            json=payload,
        )
        return _success(201, data=data)

    @mcp.tool()
    async def github_update_pull(
        pull_number: int,
        owner: str | None = None,
        repo: str | None = None,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        base: str | None = None,
    ) -> str:
        """Update a pull request.
        Args:
            pull_number: Pull request number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            title: New title
            body: New body
            state: open or closed
            base: New base branch
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        if base is not None:
            payload["base"] = base
        data = await _req(
            "PATCH",
            f"/repos/{o}/{r}/pulls/{pull_number}",
            json=payload,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_merge_pull(
        pull_number: int,
        owner: str | None = None,
        repo: str | None = None,
        commit_title: str | None = None,
        commit_message: str | None = None,
        merge_method: str | None = None,
        sha: str | None = None,
    ) -> str:
        """Merge a pull request.
        Args:
            pull_number: Pull request number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            commit_title: Merge commit title
            commit_message: Merge commit detail
            merge_method: merge, squash, or rebase
            sha: HEAD SHA to verify
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {}
        if commit_title is not None:
            payload["commit_title"] = commit_title
        if commit_message is not None:
            payload["commit_message"] = commit_message
        if merge_method is not None:
            payload["merge_method"] = merge_method
        if sha is not None:
            payload["sha"] = sha
        data = await _req(
            "PUT",
            f"/repos/{o}/{r}/pulls"
            f"/{pull_number}/merge",
            json=payload,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_list_pull_reviews(
        pull_number: int,
        owner: str | None = None,
        repo: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List reviews on a pull request.
        Args:
            pull_number: Pull request number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/pulls"
            f"/{pull_number}/reviews",
            params={
                "per_page": per_page, "page": page
            },
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_create_pull_review(
        pull_number: int,
        event: str,
        owner: str | None = None,
        repo: str | None = None,
        body: str | None = None,
        comments: list[dict] | None = None,
    ) -> str:
        """Create a review on a pull request.
        Args:
            pull_number: Pull request number
            event: APPROVE, REQUEST_CHANGES, COMMENT
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            body: Review body text
            comments: Line-level comments list
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {"event": event}
        if body is not None:
            payload["body"] = body
        if comments is not None:
            payload["comments"] = comments
        data = await _req(
            "POST",
            f"/repos/{o}/{r}/pulls"
            f"/{pull_number}/reviews",
            json=payload,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_list_pull_review_comments(
        pull_number: int,
        owner: str | None = None,
        repo: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        since: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List inline review comments on a PR.
        Args:
            pull_number: Pull request number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            sort: created or updated
            direction: asc or desc
            since: ISO 8601 timestamp
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        params: dict = {
            "per_page": per_page, "page": page
        }
        if sort is not None:
            params["sort"] = sort
        if direction is not None:
            params["direction"] = direction
        if since is not None:
            params["since"] = since
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/pulls"
            f"/{pull_number}/comments",
            params=params,
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_list_pull_files(
        pull_number: int,
        owner: str | None = None,
        repo: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List files changed in a pull request.
        Args:
            pull_number: Pull request number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/pulls"
            f"/{pull_number}/files",
            params={
                "per_page": per_page, "page": page
            },
        )
        return _list_result(data, page, per_page)

    # ── Tier 4: Branches (5) ────────────────────

    @mcp.tool()
    async def github_list_branches(
        owner: str | None = None,
        repo: str | None = None,
        protected: bool | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List branches in a repository.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            protected: Filter to protected branches
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        params: dict = {
            "per_page": per_page, "page": page
        }
        if protected is not None:
            params["protected"] = str(protected).lower()
        data = await _req(
            "GET", f"/repos/{o}/{r}/branches",
            params=params,
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_get_branch(
        branch: str,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Get details for a specific branch.
        Args:
            branch: Branch name
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/branches/{branch}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_create_branch(
        branch: str,
        sha: str,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Create a new branch from a given SHA.
        Args:
            branch: New branch name
            sha: Commit SHA to branch from
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "POST", f"/repos/{o}/{r}/git/refs",
            json={
                "ref": f"refs/heads/{branch}",
                "sha": sha,
            },
        )
        return _success(201, data=data)

    @mcp.tool()
    async def github_delete_branch(
        branch: str,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Delete a branch.
        Args:
            branch: Branch name to delete
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        await _req(
            "DELETE",
            f"/repos/{o}/{r}/git/refs/heads/{branch}",
        )
        return _success(204, message="Branch deleted.")

    @mcp.tool()
    async def github_get_branch_protection(
        branch: str,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Get branch protection rules.
        Args:
            branch: Branch name
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/branches"
            f"/{branch}/protection",
        )
        return _success(200, data=data)

    # ── Tier 5: Commits (3) ─────────────────────

    @mcp.tool()
    async def github_list_commits(
        owner: str | None = None,
        repo: str | None = None,
        sha: str | None = None,
        path: str | None = None,
        author: str | None = None,
        committer: str | None = None,
        since: str | None = None,
        until: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List commits for a repository.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            sha: Branch or commit SHA to start from
            path: Only commits with this file path
            author: Filter by author
            committer: Filter by committer
            since: ISO 8601 after timestamp
            until: ISO 8601 before timestamp
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        params: dict = {
            "per_page": per_page, "page": page
        }
        if sha is not None:
            params["sha"] = sha
        if path is not None:
            params["path"] = path
        if author is not None:
            params["author"] = author
        if committer is not None:
            params["committer"] = committer
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        data = await _req(
            "GET", f"/repos/{o}/{r}/commits",
            params=params,
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_get_commit(
        sha: str,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Get a single commit by SHA.
        Args:
            sha: Commit SHA
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET", f"/repos/{o}/{r}/commits/{sha}"
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_compare_commits(
        base: str,
        head: str,
        owner: str | None = None,
        repo: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """Compare two commits, branches, or tags.
        Args:
            base: Base commit/branch/tag
            head: Head commit/branch/tag
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/compare/{base}...{head}",
            params={
                "per_page": per_page, "page": page
            },
        )
        return _success(200, data=data)

    # ── Tier 6: Releases (6) ────────────────────

    @mcp.tool()
    async def github_list_releases(
        owner: str | None = None,
        repo: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List releases for a repository.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET", f"/repos/{o}/{r}/releases",
            params={
                "per_page": per_page, "page": page
            },
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_get_release(
        release_id: int,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Get a single release by ID.
        Args:
            release_id: Release ID
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/releases/{release_id}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_create_release(
        tag_name: str,
        owner: str | None = None,
        repo: str | None = None,
        name: str | None = None,
        body: str | None = None,
        target_commitish: str | None = None,
        draft: bool | None = None,
        prerelease: bool | None = None,
        generate_release_notes: bool | None = None,
    ) -> str:
        """Create a new release.
        Args:
            tag_name: Tag name (e.g. v1.0.0)
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            name: Release title
            body: Release notes (Markdown)
            target_commitish: Branch or SHA for tag
            draft: Create as draft
            prerelease: Mark as pre-release
            generate_release_notes: Auto-generate notes
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {"tag_name": tag_name}
        if name is not None:
            payload["name"] = name
        if body is not None:
            payload["body"] = body
        if target_commitish is not None:
            payload["target_commitish"] = (
                target_commitish
            )
        if draft is not None:
            payload["draft"] = draft
        if prerelease is not None:
            payload["prerelease"] = prerelease
        if generate_release_notes is not None:
            payload["generate_release_notes"] = (
                generate_release_notes
            )
        data = await _req(
            "POST", f"/repos/{o}/{r}/releases",
            json=payload,
        )
        return _success(201, data=data)

    @mcp.tool()
    async def github_update_release(
        release_id: int,
        owner: str | None = None,
        repo: str | None = None,
        tag_name: str | None = None,
        name: str | None = None,
        body: str | None = None,
        target_commitish: str | None = None,
        draft: bool | None = None,
        prerelease: bool | None = None,
    ) -> str:
        """Update an existing release.
        Args:
            release_id: Release ID
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            tag_name: New tag name
            name: New release title
            body: New release notes
            target_commitish: New target branch/SHA
            draft: Update draft status
            prerelease: Update pre-release status
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {}
        if tag_name is not None:
            payload["tag_name"] = tag_name
        if name is not None:
            payload["name"] = name
        if body is not None:
            payload["body"] = body
        if target_commitish is not None:
            payload["target_commitish"] = (
                target_commitish
            )
        if draft is not None:
            payload["draft"] = draft
        if prerelease is not None:
            payload["prerelease"] = prerelease
        data = await _req(
            "PATCH",
            f"/repos/{o}/{r}/releases/{release_id}",
            json=payload,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_delete_release(
        release_id: int,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Delete a release.
        Args:
            release_id: Release ID
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        await _req(
            "DELETE",
            f"/repos/{o}/{r}/releases/{release_id}",
        )
        return _success(204, message="Release deleted.")

    @mcp.tool()
    async def github_list_release_assets(
        release_id: int,
        owner: str | None = None,
        repo: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List assets for a release.
        Args:
            release_id: Release ID
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/releases"
            f"/{release_id}/assets",
            params={
                "per_page": per_page, "page": page
            },
        )
        return _list_result(data, page, per_page)

    # ── Tier 7: Actions / Workflows (6) ─────────

    @mcp.tool()
    async def github_list_workflows(
        owner: str | None = None,
        repo: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List workflows in a repository.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/actions/workflows",
            params={
                "per_page": per_page, "page": page
            },
        )
        workflows = (
            data.get("workflows", [])
            if isinstance(data, dict) else data
        )
        return _success(
            200, data=workflows,
            total_count=data.get("total_count", 0)
            if isinstance(data, dict) else len(workflows),
        )

    @mcp.tool()
    async def github_list_workflow_runs(
        owner: str | None = None,
        repo: str | None = None,
        workflow_id: str | None = None,
        branch: str | None = None,
        event: str | None = None,
        status: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List workflow runs, optionally by workflow.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            workflow_id: Workflow ID or filename
            branch: Filter by branch
            event: Filter by event type
            status: Filter by status
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        params: dict = {
            "per_page": per_page, "page": page
        }
        if branch is not None:
            params["branch"] = branch
        if event is not None:
            params["event"] = event
        if status is not None:
            params["status"] = status
        if workflow_id is not None:
            path = (
                f"/repos/{o}/{r}/actions/workflows"
                f"/{workflow_id}/runs"
            )
        else:
            path = f"/repos/{o}/{r}/actions/runs"
        data = await _req(
            "GET", path, params=params
        )
        runs = (
            data.get("workflow_runs", [])
            if isinstance(data, dict) else data
        )
        return _success(
            200, data=runs,
            total_count=data.get("total_count", 0)
            if isinstance(data, dict) else len(runs),
        )

    @mcp.tool()
    async def github_get_workflow_run(
        run_id: int,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Get a single workflow run by ID.
        Args:
            run_id: Workflow run ID
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET",
            f"/repos/{o}/{r}/actions/runs/{run_id}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_trigger_workflow(
        workflow_id: str,
        ref: str,
        owner: str | None = None,
        repo: str | None = None,
        inputs: dict | None = None,
    ) -> str:
        """Trigger a workflow_dispatch event.
        Args:
            workflow_id: Workflow ID or filename
            ref: Branch or tag to run on
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            inputs: Workflow input key-value pairs
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {"ref": ref}
        if inputs is not None:
            payload["inputs"] = inputs
        await _req(
            "POST",
            f"/repos/{o}/{r}/actions/workflows"
            f"/{workflow_id}/dispatches",
            json=payload,
        )
        return _success(
            204, message="Workflow dispatch triggered."
        )

    @mcp.tool()
    async def github_cancel_workflow_run(
        run_id: int,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Cancel a workflow run.
        Args:
            run_id: Workflow run ID
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        await _req(
            "POST",
            f"/repos/{o}/{r}/actions/runs"
            f"/{run_id}/cancel",
        )
        return _success(
            202, message="Workflow run cancelled."
        )

    @mcp.tool()
    async def github_download_workflow_run_logs(
        run_id: int,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Get download URL for workflow run logs.
        Args:
            run_id: Workflow run ID
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        client = _get_client()
        try:
            response = await client.request(
                "GET",
                f"/repos/{o}/{r}/actions/runs"
                f"/{run_id}/logs",
                follow_redirects=False,
            )
        except httpx.HTTPError as e:
            raise ToolError(
                f"GitHub API request failed: {e}"
            ) from e
        if response.status_code == 302:
            url = response.headers.get("Location", "")
            return _success(
                302, redirect_url=url,
                message="Use redirect_url to download.",
            )
        if response.status_code >= 400:
            raise ToolError(
                "GitHub API error "
                f"({response.status_code}): "
                f"{response.text}"
            )
        return _success(
            200, message="Logs response received."
        )

    # ── Tier 8: Labels (4) ──────────────────────

    @mcp.tool()
    async def github_list_labels(
        owner: str | None = None,
        repo: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List labels for a repository.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        data = await _req(
            "GET", f"/repos/{o}/{r}/labels",
            params={
                "per_page": per_page, "page": page
            },
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_create_label(
        name: str,
        color: str,
        owner: str | None = None,
        repo: str | None = None,
        description: str | None = None,
    ) -> str:
        """Create a new label in a repository.
        Args:
            name: Label name
            color: Hex color without # (e.g. ff0000)
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            description: Label description
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {"name": name, "color": color}
        if description is not None:
            payload["description"] = description
        data = await _req(
            "POST", f"/repos/{o}/{r}/labels",
            json=payload,
        )
        return _success(201, data=data)

    @mcp.tool()
    async def github_update_label(
        label_name: str,
        owner: str | None = None,
        repo: str | None = None,
        new_name: str | None = None,
        color: str | None = None,
        description: str | None = None,
    ) -> str:
        """Update an existing label.
        Args:
            label_name: Current label name
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            new_name: New label name
            color: New hex color without #
            description: New description
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {}
        if new_name is not None:
            payload["new_name"] = new_name
        if color is not None:
            payload["color"] = color
        if description is not None:
            payload["description"] = description
        data = await _req(
            "PATCH",
            f"/repos/{o}/{r}/labels/{label_name}",
            json=payload,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_delete_label(
        label_name: str,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Delete a label from a repository.
        Args:
            label_name: Label name to delete
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        await _req(
            "DELETE",
            f"/repos/{o}/{r}/labels/{label_name}",
        )
        return _success(204, message="Label deleted.")

    # ── Tier 9: Milestones (4) ──────────────────

    @mcp.tool()
    async def github_list_milestones(
        owner: str | None = None,
        repo: str | None = None,
        state: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List milestones for a repository.
        Args:
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            state: open, closed, or all
            sort: due_on or completeness
            direction: asc or desc
            per_page: Results per page (max 100)
            page: Page number
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        params: dict = {
            "per_page": per_page, "page": page
        }
        if state is not None:
            params["state"] = state
        if sort is not None:
            params["sort"] = sort
        if direction is not None:
            params["direction"] = direction
        data = await _req(
            "GET", f"/repos/{o}/{r}/milestones",
            params=params,
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_create_milestone(
        title: str,
        owner: str | None = None,
        repo: str | None = None,
        description: str | None = None,
        due_on: str | None = None,
        state: str | None = None,
    ) -> str:
        """Create a new milestone.
        Args:
            title: Milestone title
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            description: Milestone description
            due_on: ISO 8601 due date
            state: open or closed
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {"title": title}
        if description is not None:
            payload["description"] = description
        if due_on is not None:
            payload["due_on"] = due_on
        if state is not None:
            payload["state"] = state
        data = await _req(
            "POST", f"/repos/{o}/{r}/milestones",
            json=payload,
        )
        return _success(201, data=data)

    @mcp.tool()
    async def github_update_milestone(
        milestone_number: int,
        owner: str | None = None,
        repo: str | None = None,
        title: str | None = None,
        description: str | None = None,
        due_on: str | None = None,
        state: str | None = None,
    ) -> str:
        """Update an existing milestone.
        Args:
            milestone_number: Milestone number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
            title: New title
            description: New description
            due_on: New ISO 8601 due date
            state: open or closed
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if due_on is not None:
            payload["due_on"] = due_on
        if state is not None:
            payload["state"] = state
        data = await _req(
            "PATCH",
            f"/repos/{o}/{r}/milestones"
            f"/{milestone_number}",
            json=payload,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_delete_milestone(
        milestone_number: int,
        owner: str | None = None,
        repo: str | None = None,
    ) -> str:
        """Delete a milestone.
        Args:
            milestone_number: Milestone number
            owner: Repository owner (uses default)
            repo: Repository name (uses default)
        """
        o, r = _resolve_owner(owner), _resolve_repo(repo)
        await _req(
            "DELETE",
            f"/repos/{o}/{r}/milestones"
            f"/{milestone_number}",
        )
        return _success(
            204, message="Milestone deleted."
        )

    # ── Tier 10: Organizations (2) ──────────────

    @mcp.tool()
    async def github_list_orgs(
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List orgs for the authenticated user.
        Args:
            per_page: Results per page (max 100)
            page: Page number
        """
        data = await _req(
            "GET", "/user/orgs",
            params={
                "per_page": per_page, "page": page
            },
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_get_org(org: str) -> str:
        """Get details for a specific organization.
        Args:
            org: Organization login name
        """
        data = await _req("GET", f"/orgs/{org}")
        return _success(200, data=data)

    # ── Tier 11: Users (2) ──────────────────────

    @mcp.tool()
    async def github_get_authenticated_user() -> str:
        """Get the authenticated user's profile."""
        data = await _req("GET", "/user")
        return _success(200, data=data)

    @mcp.tool()
    async def github_get_user(username: str) -> str:
        """Get a user's public profile by username.
        Args:
            username: GitHub username
        """
        data = await _req(
            "GET", f"/users/{username}"
        )
        return _success(200, data=data)

    # ── Tier 12: Search (4) ─────────────────────

    @mcp.tool()
    async def github_search_repos(
        q: str,
        sort: str | None = None,
        order: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """Search for repositories.
        Args:
            q: Search query with qualifiers
            sort: stars, forks, help-wanted-issues,
                updated
            order: asc or desc
            per_page: Results per page (max 100)
            page: Page number
        """
        params: dict = {
            "q": q, "per_page": per_page, "page": page
        }
        if sort is not None:
            params["sort"] = sort
        if order is not None:
            params["order"] = order
        data = await _req(
            "GET", "/search/repositories",
            params=params,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_search_issues(
        q: str,
        sort: str | None = None,
        order: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """Search issues and PRs across repositories.
        Args:
            q: Search query with qualifiers
            sort: comments, reactions, created, updated
            order: asc or desc
            per_page: Results per page (max 100)
            page: Page number
        """
        params: dict = {
            "q": q, "per_page": per_page, "page": page
        }
        if sort is not None:
            params["sort"] = sort
        if order is not None:
            params["order"] = order
        data = await _req(
            "GET", "/search/issues", params=params
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_search_code(
        q: str,
        sort: str | None = None,
        order: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """Search for code across repositories.
        Args:
            q: Search query with qualifiers
            sort: indexed
            order: asc or desc
            per_page: Results per page (max 100)
            page: Page number
        """
        params: dict = {
            "q": q, "per_page": per_page, "page": page
        }
        if sort is not None:
            params["sort"] = sort
        if order is not None:
            params["order"] = order
        data = await _req(
            "GET", "/search/code", params=params
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_search_users(
        q: str,
        sort: str | None = None,
        order: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """Search for users.
        Args:
            q: Search query with qualifiers
            sort: followers, repositories, joined
            order: asc or desc
            per_page: Results per page (max 100)
            page: Page number
        """
        params: dict = {
            "q": q, "per_page": per_page, "page": page
        }
        if sort is not None:
            params["sort"] = sort
        if order is not None:
            params["order"] = order
        data = await _req(
            "GET", "/search/users", params=params
        )
        return _success(200, data=data)

    # ── Tier 13: Gists (5) ─────────────────────

    @mcp.tool()
    async def github_list_gists(
        username: str | None = None,
        since: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List gists for authenticated or specified user.
        Args:
            username: GitHub username (omit for yours)
            since: ISO 8601 timestamp
            per_page: Results per page (max 100)
            page: Page number
        """
        params: dict = {
            "per_page": per_page, "page": page
        }
        if since is not None:
            params["since"] = since
        if username is not None:
            path = f"/users/{username}/gists"
        else:
            path = "/gists"
        data = await _req(
            "GET", path, params=params
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_create_gist(
        files: dict,
        description: str | None = None,
        public: bool | None = None,
    ) -> str:
        """Create a new gist.
        Args:
            files: {"filename": {"content": "..."}}
            description: Gist description
            public: Whether gist is public
        """
        payload: dict = {"files": files}
        if description is not None:
            payload["description"] = description
        if public is not None:
            payload["public"] = public
        data = await _req(
            "POST", "/gists", json=payload
        )
        return _success(201, data=data)

    @mcp.tool()
    async def github_get_gist(gist_id: str) -> str:
        """Get a single gist by ID.
        Args:
            gist_id: Gist ID
        """
        data = await _req(
            "GET", f"/gists/{gist_id}"
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_update_gist(
        gist_id: str,
        files: dict | None = None,
        description: str | None = None,
    ) -> str:
        """Update an existing gist.
        Args:
            gist_id: Gist ID
            files: Files to update/add/delete
            description: New description
        """
        payload: dict = {}
        if files is not None:
            payload["files"] = files
        if description is not None:
            payload["description"] = description
        data = await _req(
            "PATCH", f"/gists/{gist_id}",
            json=payload,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def github_delete_gist(
        gist_id: str,
    ) -> str:
        """Delete a gist.
        Args:
            gist_id: Gist ID
        """
        await _req("DELETE", f"/gists/{gist_id}")
        return _success(204, message="Gist deleted.")

    # ── Tier 14: Stars (3) ─────────────────────

    @mcp.tool()
    async def github_list_starred_repos(
        username: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List starred repositories.
        Args:
            username: GitHub username (omit for yours)
            sort: created or updated
            direction: asc or desc
            per_page: Results per page (max 100)
            page: Page number
        """
        params: dict = {
            "per_page": per_page, "page": page
        }
        if sort is not None:
            params["sort"] = sort
        if direction is not None:
            params["direction"] = direction
        if username is not None:
            path = f"/users/{username}/starred"
        else:
            path = "/user/starred"
        data = await _req(
            "GET", path, params=params
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_star_repo(
        owner: str,
        repo: str,
    ) -> str:
        """Star a repository.
        Args:
            owner: Repository owner
            repo: Repository name
        """
        await _req(
            "PUT", f"/user/starred/{owner}/{repo}"
        )
        return _success(204, message="Repository starred.")

    @mcp.tool()
    async def github_unstar_repo(
        owner: str,
        repo: str,
    ) -> str:
        """Unstar a repository.
        Args:
            owner: Repository owner
            repo: Repository name
        """
        await _req(
            "DELETE", f"/user/starred/{owner}/{repo}"
        )
        return _success(
            204, message="Repository unstarred."
        )

    # ── Tier 15: Notifications (2) ──────────────

    @mcp.tool()
    async def github_list_notifications(
        all: bool | None = None,
        participating: bool | None = None,
        since: str | None = None,
        before: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> str:
        """List notifications for authenticated user.
        Args:
            all: Include read notifications
            participating: Only direct participation
            since: ISO 8601 after timestamp
            before: ISO 8601 before timestamp
            per_page: Results per page (max 100)
            page: Page number
        """
        params: dict = {
            "per_page": per_page, "page": page
        }
        if all is not None:
            params["all"] = str(all).lower()
        if participating is not None:
            params["participating"] = (
                str(participating).lower()
            )
        if since is not None:
            params["since"] = since
        if before is not None:
            params["before"] = before
        data = await _req(
            "GET", "/notifications", params=params
        )
        return _list_result(data, page, per_page)

    @mcp.tool()
    async def github_mark_notifications_read(
        last_read_at: str | None = None,
    ) -> str:
        """Mark notifications as read.
        Args:
            last_read_at: ISO 8601 timestamp (default now)
        """
        payload: dict = {}
        if last_read_at is not None:
            payload["last_read_at"] = last_read_at
        await _req(
            "PUT", "/notifications", json=payload
        )
        return _success(
            202, message="Notifications marked as read."
        )
