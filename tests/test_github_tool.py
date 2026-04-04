"""Tests for GitHub tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.github_tool import register_tools

BASE = "https://api.github.com"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


def _ok(result) -> None:
    assert _r(result)["status"] == "success"


@pytest.fixture
def server():
    mcp = FastMCP("test")
    with (
        patch(
            "mcp_toolbox.tools.github_tool.GITHUB_TOKEN",
            "ghp_test",
        ),
        patch(
            "mcp_toolbox.tools.github_tool."
            "GITHUB_DEFAULT_OWNER",
            "owner",
        ),
        patch(
            "mcp_toolbox.tools.github_tool."
            "GITHUB_DEFAULT_REPO",
            "repo",
        ),
        patch(
            "mcp_toolbox.tools.github_tool._client",
            None,
        ),
    ):
        register_tools(mcp)
        yield mcp


# --- Auth / Error ---


@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with (
        patch(
            "mcp_toolbox.tools.github_tool.GITHUB_TOKEN",
            None,
        ),
        patch(
            "mcp_toolbox.tools.github_tool."
            "GITHUB_DEFAULT_OWNER",
            "owner",
        ),
        patch(
            "mcp_toolbox.tools.github_tool."
            "GITHUB_DEFAULT_REPO",
            "repo",
        ),
        patch(
            "mcp_toolbox.tools.github_tool._client",
            None,
        ),
    ):
        register_tools(mcp)
        with pytest.raises(
            Exception, match="GITHUB_TOKEN"
        ):
            await mcp.call_tool(
                "github_list_repos", {}
            )


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit(server):
    respx.get(f"{BASE}/user/repos").mock(
        return_value=httpx.Response(
            403,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "1700000000",
            },
        ),
    )
    with pytest.raises(
        Exception, match="rate limit exceeded"
    ):
        await server.call_tool(
            "github_list_repos", {}
        )


@pytest.mark.asyncio
@respx.mock
async def test_secondary_rate_limit(server):
    respx.get(f"{BASE}/user/repos").mock(
        return_value=httpx.Response(
            429, headers={"Retry-After": "60"},
        ),
    )
    with pytest.raises(
        Exception, match="secondary rate limit"
    ):
        await server.call_tool(
            "github_list_repos", {}
        )


# --- Repositories (7) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_repos(server):
    respx.get(f"{BASE}/user/repos").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1, "name": "repo"}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_repos", {},
    ))
    assert r["status"] == "success"
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_repos_for_user(server):
    respx.get(f"{BASE}/users/octocat/repos").mock(
        return_value=httpx.Response(200, json=[]),
    )
    _ok(await server.call_tool(
        "github_list_repos", {"owner": "octocat"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_repo(server):
    respx.get(f"{BASE}/repos/owner/repo").mock(
        return_value=httpx.Response(
            200, json={"id": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_get_repo", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_create_repo(server):
    route = respx.post(f"{BASE}/user/repos").mock(
        return_value=httpx.Response(
            201, json={"id": 1, "name": "new"},
        ),
    )
    _ok(await server.call_tool(
        "github_create_repo", {"name": "new"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["name"] == "new"


@pytest.mark.asyncio
@respx.mock
async def test_create_repo_in_org(server):
    route = respx.post(f"{BASE}/orgs/myorg/repos").mock(
        return_value=httpx.Response(
            201, json={"id": 2},
        ),
    )
    _ok(await server.call_tool(
        "github_create_repo",
        {"name": "r", "org": "myorg"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["name"] == "r"


@pytest.mark.asyncio
@respx.mock
async def test_update_repo(server):
    route = respx.patch(f"{BASE}/repos/owner/repo").mock(
        return_value=httpx.Response(
            200, json={"id": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_update_repo",
        {"description": "updated"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["description"] == "updated"


@pytest.mark.asyncio
@respx.mock
async def test_delete_repo(server):
    respx.delete(f"{BASE}/repos/owner/repo").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_delete_repo", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_repo_topics(server):
    respx.get(
        f"{BASE}/repos/owner/repo/topics"
    ).mock(
        return_value=httpx.Response(
            200, json={"names": ["python"]},
        ),
    )
    _ok(await server.call_tool(
        "github_list_repo_topics", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_repo_languages(server):
    respx.get(
        f"{BASE}/repos/owner/repo/languages"
    ).mock(
        return_value=httpx.Response(
            200, json={"Python": 1000},
        ),
    )
    _ok(await server.call_tool(
        "github_list_repo_languages", {},
    ))


# --- Issues (13) ---


@pytest.mark.asyncio
@respx.mock
async def test_create_issue(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo/issues"
    ).mock(
        return_value=httpx.Response(
            201, json={"id": 1, "number": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_create_issue",
        {
            "title": "Bug",
            "body": "It broke",
            "labels": ["bug", "urgent"],
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["title"] == "Bug"
    assert body["body"] == "It broke"
    assert body["labels"] == ["bug", "urgent"]


@pytest.mark.asyncio
@respx.mock
async def test_get_issue(server):
    respx.get(
        f"{BASE}/repos/owner/repo/issues/1"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": 1, "number": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_get_issue", {"issue_number": 1},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_issue(server):
    route = respx.patch(
        f"{BASE}/repos/owner/repo/issues/1"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_update_issue",
        {"issue_number": 1, "state": "closed"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["state"] == "closed"


@pytest.mark.asyncio
@respx.mock
async def test_list_issues(server):
    respx.get(
        f"{BASE}/repos/owner/repo/issues"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_issues", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_add_issue_labels(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo/issues/1/labels"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"name": "bug"}],
        ),
    )
    _ok(await server.call_tool(
        "github_add_issue_labels",
        {"issue_number": 1, "labels": ["bug"]},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["labels"] == ["bug"]


@pytest.mark.asyncio
@respx.mock
async def test_remove_issue_label(server):
    respx.delete(
        f"{BASE}/repos/owner/repo"
        "/issues/1/labels/bug"
    ).mock(
        return_value=httpx.Response(
            200, json=[],
        ),
    )
    _ok(await server.call_tool(
        "github_remove_issue_label",
        {"issue_number": 1, "label": "bug"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_add_issue_assignees(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo"
        "/issues/1/assignees"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_add_issue_assignees",
        {"issue_number": 1, "assignees": ["user1"]},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["assignees"] == ["user1"]


@pytest.mark.asyncio
@respx.mock
async def test_list_issue_comments(server):
    respx.get(
        f"{BASE}/repos/owner/repo"
        "/issues/1/comments"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"id": 10}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_issue_comments",
        {"issue_number": 1},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_create_issue_comment(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo"
        "/issues/1/comments"
    ).mock(
        return_value=httpx.Response(
            201, json={"id": 10},
        ),
    )
    _ok(await server.call_tool(
        "github_create_issue_comment",
        {"issue_number": 1, "body": "Hello"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["body"] == "Hello"


@pytest.mark.asyncio
@respx.mock
async def test_update_issue_comment(server):
    route = respx.patch(
        f"{BASE}/repos/owner/repo"
        "/issues/comments/10"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": 10},
        ),
    )
    _ok(await server.call_tool(
        "github_update_issue_comment",
        {"comment_id": 10, "body": "Updated"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["body"] == "Updated"


@pytest.mark.asyncio
@respx.mock
async def test_delete_issue_comment(server):
    respx.delete(
        f"{BASE}/repos/owner/repo"
        "/issues/comments/10"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_delete_issue_comment",
        {"comment_id": 10},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_lock_issue(server):
    route = respx.put(
        f"{BASE}/repos/owner/repo/issues/1/lock"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_lock_issue", {"issue_number": 1},
    ))
    assert route.calls


@pytest.mark.asyncio
@respx.mock
async def test_unlock_issue(server):
    respx.delete(
        f"{BASE}/repos/owner/repo/issues/1/lock"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_unlock_issue", {"issue_number": 1},
    ))


# --- Pull Requests (9) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_pulls(server):
    respx.get(
        f"{BASE}/repos/owner/repo/pulls"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_pulls", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_pull(server):
    respx.get(
        f"{BASE}/repos/owner/repo/pulls/1"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": 1, "number": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_get_pull", {"pull_number": 1},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_create_pull(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo/pulls"
    ).mock(
        return_value=httpx.Response(
            201, json={"id": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_create_pull",
        {
            "title": "Fix",
            "head": "feature",
            "base": "main",
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["title"] == "Fix"
    assert body["head"] == "feature"
    assert body["base"] == "main"


@pytest.mark.asyncio
@respx.mock
async def test_update_pull(server):
    route = respx.patch(
        f"{BASE}/repos/owner/repo/pulls/1"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_update_pull",
        {"pull_number": 1, "title": "Updated"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["title"] == "Updated"


@pytest.mark.asyncio
@respx.mock
async def test_merge_pull(server):
    route = respx.put(
        f"{BASE}/repos/owner/repo/pulls/1/merge"
    ).mock(
        return_value=httpx.Response(
            200, json={"merged": True},
        ),
    )
    _ok(await server.call_tool(
        "github_merge_pull", {"pull_number": 1},
    ))
    assert route.calls


@pytest.mark.asyncio
@respx.mock
async def test_list_pull_reviews(server):
    respx.get(
        f"{BASE}/repos/owner/repo/pulls/1/reviews"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_pull_reviews",
        {"pull_number": 1},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_create_pull_review(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo/pulls/1/reviews"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_create_pull_review",
        {"pull_number": 1, "event": "APPROVE"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["event"] == "APPROVE"


@pytest.mark.asyncio
@respx.mock
async def test_list_pull_review_comments(server):
    respx.get(
        f"{BASE}/repos/owner/repo"
        "/pulls/1/comments"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_pull_review_comments",
        {"pull_number": 1},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_pull_files(server):
    respx.get(
        f"{BASE}/repos/owner/repo/pulls/1/files"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"filename": "a.py"}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_pull_files",
        {"pull_number": 1},
    ))
    assert r["count"] == 1


# --- Branches (5) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_branches(server):
    respx.get(
        f"{BASE}/repos/owner/repo/branches"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"name": "main"}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_branches", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_branch(server):
    respx.get(
        f"{BASE}/repos/owner/repo/branches/main"
    ).mock(
        return_value=httpx.Response(
            200, json={"name": "main"},
        ),
    )
    _ok(await server.call_tool(
        "github_get_branch", {"branch": "main"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_create_branch(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo/git/refs"
    ).mock(
        return_value=httpx.Response(
            201, json={"ref": "refs/heads/feat"},
        ),
    )
    _ok(await server.call_tool(
        "github_create_branch",
        {"branch": "feat", "sha": "abc123"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["ref"] == "refs/heads/feat"
    assert body["sha"] == "abc123"


@pytest.mark.asyncio
@respx.mock
async def test_delete_branch(server):
    respx.delete(
        f"{BASE}/repos/owner/repo"
        "/git/refs/heads/feat"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_delete_branch",
        {"branch": "feat"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_branch_protection(server):
    respx.get(
        f"{BASE}/repos/owner/repo"
        "/branches/main/protection"
    ).mock(
        return_value=httpx.Response(
            200, json={"required_pull_request_reviews": {}},
        ),
    )
    _ok(await server.call_tool(
        "github_get_branch_protection",
        {"branch": "main"},
    ))


# --- Commits (3) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_commits(server):
    respx.get(
        f"{BASE}/repos/owner/repo/commits"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"sha": "abc"}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_commits", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_commit(server):
    respx.get(
        f"{BASE}/repos/owner/repo/commits/abc123"
    ).mock(
        return_value=httpx.Response(
            200, json={"sha": "abc123"},
        ),
    )
    _ok(await server.call_tool(
        "github_get_commit", {"sha": "abc123"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_compare_commits(server):
    respx.get(
        f"{BASE}/repos/owner/repo"
        "/compare/main...feat"
    ).mock(
        return_value=httpx.Response(
            200, json={"ahead_by": 3},
        ),
    )
    _ok(await server.call_tool(
        "github_compare_commits",
        {"base": "main", "head": "feat"},
    ))


# --- Releases (6) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_releases(server):
    respx.get(
        f"{BASE}/repos/owner/repo/releases"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_releases", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_release(server):
    respx.get(
        f"{BASE}/repos/owner/repo/releases/1"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_get_release", {"release_id": 1},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_create_release(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo/releases"
    ).mock(
        return_value=httpx.Response(
            201, json={"id": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_create_release",
        {"tag_name": "v1.0.0"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["tag_name"] == "v1.0.0"


@pytest.mark.asyncio
@respx.mock
async def test_update_release(server):
    route = respx.patch(
        f"{BASE}/repos/owner/repo/releases/1"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_update_release",
        {"release_id": 1, "name": "v1.0.1"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["name"] == "v1.0.1"


@pytest.mark.asyncio
@respx.mock
async def test_delete_release(server):
    respx.delete(
        f"{BASE}/repos/owner/repo/releases/1"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_delete_release", {"release_id": 1},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_release_assets(server):
    respx.get(
        f"{BASE}/repos/owner/repo"
        "/releases/1/assets"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"id": 10}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_release_assets",
        {"release_id": 1},
    ))
    assert r["count"] == 1


# --- Actions / Workflows (6) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_workflows(server):
    respx.get(
        f"{BASE}/repos/owner/repo"
        "/actions/workflows"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "total_count": 1,
                "workflows": [{"id": 1}],
            },
        ),
    )
    _ok(await server.call_tool(
        "github_list_workflows", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_workflow_runs(server):
    respx.get(
        f"{BASE}/repos/owner/repo/actions/runs"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "total_count": 1,
                "workflow_runs": [{"id": 100}],
            },
        ),
    )
    _ok(await server.call_tool(
        "github_list_workflow_runs", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_workflow_runs_by_id(server):
    respx.get(
        f"{BASE}/repos/owner/repo"
        "/actions/workflows/ci.yml/runs"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "total_count": 0,
                "workflow_runs": [],
            },
        ),
    )
    _ok(await server.call_tool(
        "github_list_workflow_runs",
        {"workflow_id": "ci.yml"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_workflow_run(server):
    respx.get(
        f"{BASE}/repos/owner/repo"
        "/actions/runs/100"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": 100},
        ),
    )
    _ok(await server.call_tool(
        "github_get_workflow_run", {"run_id": 100},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_trigger_workflow(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo"
        "/actions/workflows/ci.yml/dispatches"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_trigger_workflow",
        {"workflow_id": "ci.yml", "ref": "main"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["ref"] == "main"


@pytest.mark.asyncio
@respx.mock
async def test_cancel_workflow_run(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo"
        "/actions/runs/100/cancel"
    ).mock(
        return_value=httpx.Response(
            202, json={},
        ),
    )
    _ok(await server.call_tool(
        "github_cancel_workflow_run",
        {"run_id": 100},
    ))
    assert route.calls


@pytest.mark.asyncio
@respx.mock
async def test_download_workflow_run_logs(server):
    respx.get(
        f"{BASE}/repos/owner/repo"
        "/actions/runs/100/logs"
    ).mock(
        return_value=httpx.Response(
            302,
            headers={
                "Location": "https://example.com/logs.zip"
            },
        ),
    )
    r = _r(await server.call_tool(
        "github_download_workflow_run_logs",
        {"run_id": 100},
    ))
    assert r["redirect_url"] == (
        "https://example.com/logs.zip"
    )


# --- Labels (4) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_labels(server):
    respx.get(
        f"{BASE}/repos/owner/repo/labels"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"name": "bug"}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_labels", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_create_label(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo/labels"
    ).mock(
        return_value=httpx.Response(
            201, json={"name": "bug", "color": "ff0000"},
        ),
    )
    _ok(await server.call_tool(
        "github_create_label",
        {"name": "bug", "color": "ff0000"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["name"] == "bug"
    assert body["color"] == "ff0000"


@pytest.mark.asyncio
@respx.mock
async def test_update_label(server):
    route = respx.patch(
        f"{BASE}/repos/owner/repo/labels/bug"
    ).mock(
        return_value=httpx.Response(
            200, json={"name": "bugfix"},
        ),
    )
    _ok(await server.call_tool(
        "github_update_label",
        {"label_name": "bug", "new_name": "bugfix"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["new_name"] == "bugfix"


@pytest.mark.asyncio
@respx.mock
async def test_delete_label(server):
    respx.delete(
        f"{BASE}/repos/owner/repo/labels/bug"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_delete_label",
        {"label_name": "bug"},
    ))


# --- Milestones (4) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_milestones(server):
    respx.get(
        f"{BASE}/repos/owner/repo/milestones"
    ).mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_milestones", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_create_milestone(server):
    route = respx.post(
        f"{BASE}/repos/owner/repo/milestones"
    ).mock(
        return_value=httpx.Response(
            201, json={"id": 1, "title": "v1"},
        ),
    )
    _ok(await server.call_tool(
        "github_create_milestone",
        {"title": "v1"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["title"] == "v1"


@pytest.mark.asyncio
@respx.mock
async def test_update_milestone(server):
    route = respx.patch(
        f"{BASE}/repos/owner/repo/milestones/1"
    ).mock(
        return_value=httpx.Response(
            200, json={"id": 1},
        ),
    )
    _ok(await server.call_tool(
        "github_update_milestone",
        {"milestone_number": 1, "title": "v2"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["title"] == "v2"


@pytest.mark.asyncio
@respx.mock
async def test_delete_milestone(server):
    respx.delete(
        f"{BASE}/repos/owner/repo/milestones/1"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_delete_milestone",
        {"milestone_number": 1},
    ))


# --- Organizations (2) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_orgs(server):
    respx.get(f"{BASE}/user/orgs").mock(
        return_value=httpx.Response(
            200, json=[{"login": "myorg"}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_orgs", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_org(server):
    respx.get(f"{BASE}/orgs/myorg").mock(
        return_value=httpx.Response(
            200, json={"login": "myorg"},
        ),
    )
    _ok(await server.call_tool(
        "github_get_org", {"org": "myorg"},
    ))


# --- Users (2) ---


@pytest.mark.asyncio
@respx.mock
async def test_get_authenticated_user(server):
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(
            200, json={"login": "me"},
        ),
    )
    _ok(await server.call_tool(
        "github_get_authenticated_user", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_user(server):
    respx.get(f"{BASE}/users/octocat").mock(
        return_value=httpx.Response(
            200, json={"login": "octocat"},
        ),
    )
    _ok(await server.call_tool(
        "github_get_user", {"username": "octocat"},
    ))


# --- Search (4) ---


@pytest.mark.asyncio
@respx.mock
async def test_search_repos(server):
    respx.get(f"{BASE}/search/repositories").mock(
        return_value=httpx.Response(
            200,
            json={"total_count": 1, "items": []},
        ),
    )
    _ok(await server.call_tool(
        "github_search_repos", {"q": "python"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_search_issues(server):
    respx.get(f"{BASE}/search/issues").mock(
        return_value=httpx.Response(
            200,
            json={"total_count": 0, "items": []},
        ),
    )
    _ok(await server.call_tool(
        "github_search_issues", {"q": "bug"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_search_code(server):
    respx.get(f"{BASE}/search/code").mock(
        return_value=httpx.Response(
            200,
            json={"total_count": 0, "items": []},
        ),
    )
    _ok(await server.call_tool(
        "github_search_code", {"q": "def main"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_search_users(server):
    respx.get(f"{BASE}/search/users").mock(
        return_value=httpx.Response(
            200,
            json={"total_count": 0, "items": []},
        ),
    )
    _ok(await server.call_tool(
        "github_search_users", {"q": "octocat"},
    ))


# --- Gists (5) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_gists(server):
    respx.get(f"{BASE}/gists").mock(
        return_value=httpx.Response(
            200, json=[{"id": "abc"}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_gists", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_gists_for_user(server):
    respx.get(f"{BASE}/users/octocat/gists").mock(
        return_value=httpx.Response(200, json=[]),
    )
    _ok(await server.call_tool(
        "github_list_gists",
        {"username": "octocat"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_create_gist(server):
    route = respx.post(f"{BASE}/gists").mock(
        return_value=httpx.Response(
            201, json={"id": "abc"},
        ),
    )
    _ok(await server.call_tool(
        "github_create_gist",
        {"files": {"a.txt": {"content": "hi"}}},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "files" in body
    assert body["files"]["a.txt"]["content"] == "hi"


@pytest.mark.asyncio
@respx.mock
async def test_get_gist(server):
    respx.get(f"{BASE}/gists/abc").mock(
        return_value=httpx.Response(
            200, json={"id": "abc"},
        ),
    )
    _ok(await server.call_tool(
        "github_get_gist", {"gist_id": "abc"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_gist(server):
    route = respx.patch(f"{BASE}/gists/abc").mock(
        return_value=httpx.Response(
            200, json={"id": "abc"},
        ),
    )
    _ok(await server.call_tool(
        "github_update_gist",
        {"gist_id": "abc", "description": "new"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["description"] == "new"


@pytest.mark.asyncio
@respx.mock
async def test_delete_gist(server):
    respx.delete(f"{BASE}/gists/abc").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_delete_gist", {"gist_id": "abc"},
    ))


# --- Stars (3) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_starred_repos(server):
    respx.get(f"{BASE}/user/starred").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_starred_repos", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_starred_repos_for_user(server):
    respx.get(
        f"{BASE}/users/octocat/starred"
    ).mock(
        return_value=httpx.Response(200, json=[]),
    )
    _ok(await server.call_tool(
        "github_list_starred_repos",
        {"username": "octocat"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_star_repo(server):
    route = respx.put(
        f"{BASE}/user/starred/octocat/hello"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_star_repo",
        {"owner": "octocat", "repo": "hello"},
    ))
    assert route.calls


@pytest.mark.asyncio
@respx.mock
async def test_unstar_repo(server):
    respx.delete(
        f"{BASE}/user/starred/octocat/hello"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "github_unstar_repo",
        {"owner": "octocat", "repo": "hello"},
    ))


# --- Notifications (2) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_notifications(server):
    respx.get(f"{BASE}/notifications").mock(
        return_value=httpx.Response(
            200, json=[{"id": "1"}],
        ),
    )
    r = _r(await server.call_tool(
        "github_list_notifications", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_mark_notifications_read(server):
    route = respx.put(f"{BASE}/notifications").mock(
        return_value=httpx.Response(
            202, json={},
        ),
    )
    _ok(await server.call_tool(
        "github_mark_notifications_read", {},
    ))
    assert route.calls
