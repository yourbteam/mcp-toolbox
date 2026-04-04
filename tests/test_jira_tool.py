"""Tests for Jira Cloud tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.jira_tool import register_tools

JB = "https://test.atlassian.net"
API = f"{JB}/rest/api/3"
AGILE = f"{JB}/rest/agile/1.0"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.jira_tool.JIRA_BASE_URL", JB), \
         patch("mcp_toolbox.tools.jira_tool.JIRA_EMAIL", "t@e.com"), \
         patch("mcp_toolbox.tools.jira_tool.JIRA_API_TOKEN", "tok"), \
         patch("mcp_toolbox.tools.jira_tool._client", None):
        register_tools(mcp)
        yield mcp


# --- Auth/Error ---

@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.jira_tool.JIRA_BASE_URL", None), \
         patch("mcp_toolbox.tools.jira_tool.JIRA_EMAIL", None), \
         patch("mcp_toolbox.tools.jira_tool.JIRA_API_TOKEN", None), \
         patch("mcp_toolbox.tools.jira_tool._client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="Jira credentials"):
            await mcp.call_tool("jira_list_projects", {})

@pytest.mark.asyncio
@respx.mock
async def test_api_error_429(server):
    respx.get(f"{API}/project/search").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "5"}),
    )
    with pytest.raises(Exception, match="rate limit"):
        await server.call_tool("jira_list_projects", {})

# --- Issues ---

@pytest.mark.asyncio
@respx.mock
async def test_create_issue(server):
    route = respx.post(f"{API}/issue").mock(
        return_value=httpx.Response(201, json={"id": "1", "key": "P-1"}),
    )
    assert _r(await server.call_tool("jira_create_issue", {
        "project_key": "P", "summary": "Bug", "issue_type": "Bug",
    }))["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert "fields" in body
    assert body["fields"]["project"] == {"key": "P"}
    assert body["fields"]["summary"] == "Bug"
    assert body["fields"]["issuetype"] == {"name": "Bug"}

@pytest.mark.asyncio
@respx.mock
async def test_get_issue(server):
    respx.get(f"{API}/issue/P-1").mock(
        return_value=httpx.Response(200, json={"key": "P-1"}),
    )
    assert _r(await server.call_tool("jira_get_issue", {"issue_key": "P-1"}))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_update_issue(server):
    route = respx.put(f"{API}/issue/P-1").mock(
        return_value=httpx.Response(204),
    )
    result = await server.call_tool("jira_update_issue", {"issue_key": "P-1", "summary": "Fixed"})
    assert _r(result)["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body == {"fields": {"summary": "Fixed"}}

@pytest.mark.asyncio
@respx.mock
async def test_delete_issue(server):
    respx.delete(f"{API}/issue/P-1").mock(
        return_value=httpx.Response(204),
    )
    result = await server.call_tool("jira_delete_issue", {"issue_key": "P-1"})
    assert _r(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_search_issues(server):
    route = respx.post(f"{API}/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": [{"key": "P-1"}]}),
    )
    assert _r(await server.call_tool("jira_search_issues", {"jql": "project=P"}))["count"] == 1
    body = json.loads(route.calls[0].request.content)
    assert body["jql"] == "project=P"
    assert body["maxResults"] == 50

@pytest.mark.asyncio
@respx.mock
async def test_transition_issue(server):
    route = respx.post(f"{API}/issue/P-1/transitions").mock(
        return_value=httpx.Response(204),
    )
    result = await server.call_tool("jira_transition_issue", {
        "issue_key": "P-1", "transition_id": "5",
    })
    assert _r(result)["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body == {"transition": {"id": "5"}}

@pytest.mark.asyncio
@respx.mock
async def test_list_transitions(server):
    respx.get(f"{API}/issue/P-1/transitions").mock(
        return_value=httpx.Response(200, json={"transitions": [{"id": "5"}]}),
    )
    assert _r(await server.call_tool("jira_list_transitions", {"issue_key": "P-1"}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_assign_issue(server):
    route = respx.put(f"{API}/issue/P-1/assignee").mock(
        return_value=httpx.Response(204),
    )
    result = await server.call_tool("jira_assign_issue", {"issue_key": "P-1", "account_id": "abc"})
    assert _r(result)["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body == {"accountId": "abc"}

@pytest.mark.asyncio
@respx.mock
async def test_add_comment(server):
    route = respx.post(f"{API}/issue/P-1/comment").mock(
        return_value=httpx.Response(201, json={"id": "c1"}),
    )
    result = await server.call_tool("jira_add_comment", {"issue_key": "P-1", "body": "Note"})
    assert _r(result)["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body["body"]["type"] == "doc"
    assert body["body"]["version"] == 1
    assert body["body"]["content"][0]["content"][0]["text"] == "Note"

@pytest.mark.asyncio
@respx.mock
async def test_list_comments(server):
    respx.get(f"{API}/issue/P-1/comment").mock(
        return_value=httpx.Response(200, json={"comments": [{"id": "c1"}]}),
    )
    assert _r(await server.call_tool("jira_list_comments", {"issue_key": "P-1"}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_update_comment(server):
    route = respx.put(f"{API}/issue/P-1/comment/c1").mock(
        return_value=httpx.Response(200, json={"id": "c1"}),
    )
    result = await server.call_tool("jira_update_comment", {
        "issue_key": "P-1", "comment_id": "c1", "body": "Edited",
    })
    assert _r(result)["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body["body"]["type"] == "doc"
    assert body["body"]["content"][0]["content"][0]["text"] == "Edited"

@pytest.mark.asyncio
@respx.mock
async def test_delete_comment(server):
    respx.delete(f"{API}/issue/P-1/comment/c1").mock(
        return_value=httpx.Response(204),
    )
    result = await server.call_tool("jira_delete_comment", {"issue_key": "P-1", "comment_id": "c1"})
    assert _r(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_add_attachment(server, tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hi")
    route = respx.post(f"{API}/issue/P-1/attachments").mock(
        return_value=httpx.Response(200, json=[{"id": "a1"}]),
    )
    result = await server.call_tool("jira_add_attachment", {
        "issue_key": "P-1", "file_path": str(f),
    })
    assert _r(result)["status"] == "success"
    req = route.calls[0].request
    assert "multipart" in req.headers.get("content-type", "")

@pytest.mark.asyncio
@respx.mock
async def test_list_attachments(server):
    respx.get(f"{API}/issue/P-1").mock(
        return_value=httpx.Response(200, json={"fields": {"attachment": [{"id": "a1"}]}}),
    )
    assert _r(await server.call_tool("jira_list_attachments", {"issue_key": "P-1"}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_delete_attachment(server):
    respx.delete(f"{API}/attachment/a1").mock(
        return_value=httpx.Response(204),
    )
    result = await server.call_tool("jira_delete_attachment", {"attachment_id": "a1"})
    assert _r(result)["status"] == "success"

# --- Projects ---

@pytest.mark.asyncio
@respx.mock
async def test_list_projects(server):
    respx.get(f"{API}/project/search").mock(
        return_value=httpx.Response(200, json={"values": [{"key": "P"}]}),
    )
    assert _r(await server.call_tool("jira_list_projects", {}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_get_project(server):
    respx.get(f"{API}/project/P").mock(
        return_value=httpx.Response(200, json={"key": "P"}),
    )
    result = await server.call_tool("jira_get_project", {"project_key": "P"})
    assert _r(result)["status"] == "success"

# --- Boards ---

@pytest.mark.asyncio
@respx.mock
async def test_list_boards(server):
    respx.get(f"{AGILE}/board").mock(
        return_value=httpx.Response(200, json={"values": [{"id": 1}]}),
    )
    assert _r(await server.call_tool("jira_list_boards", {}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_get_board(server):
    respx.get(f"{AGILE}/board/1").mock(
        return_value=httpx.Response(200, json={"id": 1}),
    )
    assert _r(await server.call_tool("jira_get_board", {"board_id": 1}))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_get_board_issues(server):
    respx.get(f"{AGILE}/board/1/issue").mock(
        return_value=httpx.Response(200, json={"issues": []}),
    )
    assert _r(await server.call_tool("jira_get_board_issues", {"board_id": 1}))["count"] == 0

# --- Sprints ---

@pytest.mark.asyncio
@respx.mock
async def test_list_sprints(server):
    respx.get(f"{AGILE}/board/1/sprint").mock(
        return_value=httpx.Response(200, json={"values": [{"id": 1}]}),
    )
    assert _r(await server.call_tool("jira_list_sprints", {"board_id": 1}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_get_sprint(server):
    respx.get(f"{AGILE}/sprint/1").mock(
        return_value=httpx.Response(200, json={"id": 1}),
    )
    assert _r(await server.call_tool("jira_get_sprint", {"sprint_id": 1}))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_get_sprint_issues(server):
    respx.get(f"{AGILE}/sprint/1/issue").mock(
        return_value=httpx.Response(200, json={"issues": []}),
    )
    assert _r(await server.call_tool("jira_get_sprint_issues", {"sprint_id": 1}))["count"] == 0

@pytest.mark.asyncio
@respx.mock
async def test_move_to_sprint(server):
    route = respx.post(f"{AGILE}/sprint/1/issue").mock(
        return_value=httpx.Response(204),
    )
    result = await server.call_tool("jira_move_to_sprint", {"sprint_id": 1, "issue_keys": ["P-1"]})
    assert _r(result)["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body == {"issues": ["P-1"]}

# --- Users ---

@pytest.mark.asyncio
@respx.mock
async def test_search_users(server):
    respx.get(f"{API}/user/search").mock(
        return_value=httpx.Response(200, json=[{"accountId": "u1"}]),
    )
    assert _r(await server.call_tool("jira_search_users", {"query": "john"}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_get_user(server):
    respx.get(f"{API}/user").mock(
        return_value=httpx.Response(200, json={"accountId": "u1"}),
    )
    assert _r(await server.call_tool("jira_get_user", {"account_id": "u1"}))["status"] == "success"

# --- Metadata ---

@pytest.mark.asyncio
@respx.mock
async def test_list_priorities(server):
    respx.get(f"{API}/priority/search").mock(
        return_value=httpx.Response(200, json={"values": [{"id": "1"}]}),
    )
    assert _r(await server.call_tool("jira_list_priorities", {}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_list_statuses(server):
    respx.get(f"{API}/statuses/search").mock(
        return_value=httpx.Response(200, json={"values": [{"id": "1"}]}),
    )
    assert _r(await server.call_tool("jira_list_statuses", {}))["count"] == 1

# --- Worklogs ---

@pytest.mark.asyncio
@respx.mock
async def test_add_worklog(server):
    route = respx.post(f"{API}/issue/P-1/worklog").mock(
        return_value=httpx.Response(201, json={"id": "w1"}),
    )
    result = await server.call_tool("jira_add_worklog", {"issue_key": "P-1", "time_spent": "2h"})
    assert _r(result)["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body["timeSpent"] == "2h"

@pytest.mark.asyncio
@respx.mock
async def test_list_worklogs(server):
    respx.get(f"{API}/issue/P-1/worklog").mock(
        return_value=httpx.Response(200, json={"worklogs": []}),
    )
    assert _r(await server.call_tool("jira_list_worklogs", {"issue_key": "P-1"}))["count"] == 0

@pytest.mark.asyncio
@respx.mock
async def test_update_worklog(server):
    route = respx.put(f"{API}/issue/P-1/worklog/w1").mock(
        return_value=httpx.Response(200, json={"id": "w1"}),
    )
    result = await server.call_tool("jira_update_worklog", {
        "issue_key": "P-1", "worklog_id": "w1", "time_spent": "3h",
    })
    assert _r(result)["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body == {"timeSpent": "3h"}

@pytest.mark.asyncio
@respx.mock
async def test_delete_worklog(server):
    respx.delete(f"{API}/issue/P-1/worklog/w1").mock(
        return_value=httpx.Response(204),
    )
    result = await server.call_tool("jira_delete_worklog", {"issue_key": "P-1", "worklog_id": "w1"})
    assert _r(result)["status"] == "success"

# --- Watchers ---

@pytest.mark.asyncio
@respx.mock
async def test_get_watchers(server):
    respx.get(f"{API}/issue/P-1/watchers").mock(
        return_value=httpx.Response(200, json={"watchers": [{"accountId": "u1"}]}),
    )
    assert _r(await server.call_tool("jira_get_watchers", {"issue_key": "P-1"}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_add_watcher(server):
    route = respx.post(f"{API}/issue/P-1/watchers").mock(
        return_value=httpx.Response(204),
    )
    result = await server.call_tool("jira_add_watcher", {"issue_key": "P-1", "account_id": "u1"})
    assert _r(result)["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body == "u1"

@pytest.mark.asyncio
@respx.mock
async def test_remove_watcher(server):
    respx.delete(f"{API}/issue/P-1/watchers").mock(
        return_value=httpx.Response(204),
    )
    result = await server.call_tool("jira_remove_watcher", {"issue_key": "P-1", "account_id": "u1"})
    assert _r(result)["status"] == "success"

# --- Issue Links ---

@pytest.mark.asyncio
@respx.mock
async def test_create_issue_link(server):
    route = respx.post(f"{API}/issueLink").mock(
        return_value=httpx.Response(201, json={}),
    )
    assert _r(await server.call_tool("jira_create_issue_link", {
        "type_name": "Blocks", "inward_issue_key": "P-1", "outward_issue_key": "P-2",
    }))["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body["type"] == {"name": "Blocks"}
    assert body["inwardIssue"] == {"key": "P-1"}
    assert body["outwardIssue"] == {"key": "P-2"}

@pytest.mark.asyncio
@respx.mock
async def test_delete_issue_link(server):
    respx.delete(f"{API}/issueLink/123").mock(
        return_value=httpx.Response(204),
    )
    result = await server.call_tool("jira_delete_issue_link", {"link_id": "123"})
    assert _r(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_issue_link_types(server):
    respx.get(f"{API}/issueLinkType").mock(
        return_value=httpx.Response(200, json={"issueLinkTypes": [{"name": "Blocks"}]}),
    )
    assert _r(await server.call_tool("jira_list_issue_link_types", {}))["count"] == 1

# --- Components ---

@pytest.mark.asyncio
@respx.mock
async def test_list_components(server):
    respx.get(f"{API}/project/P/component").mock(
        return_value=httpx.Response(200, json=[{"id": "1"}]),
    )
    assert _r(await server.call_tool("jira_list_components", {"project_key": "P"}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_create_component(server):
    route = respx.post(f"{API}/component").mock(
        return_value=httpx.Response(201, json={"id": "1"}),
    )
    result = await server.call_tool("jira_create_component", {
        "project_key": "P", "name": "Backend",
    })
    assert _r(result)["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body == {"project": "P", "name": "Backend"}

# --- Versions ---

@pytest.mark.asyncio
@respx.mock
async def test_list_versions(server):
    respx.get(f"{API}/project/P/versions").mock(
        return_value=httpx.Response(200, json=[{"id": "1"}]),
    )
    assert _r(await server.call_tool("jira_list_versions", {"project_key": "P"}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_create_version(server):
    route = respx.post(f"{API}/version").mock(
        return_value=httpx.Response(201, json={"id": "1"}),
    )
    result = await server.call_tool("jira_create_version", {"project_id": "10001", "name": "v1.0"})
    assert _r(result)["status"] == "success"
    body = json.loads(route.calls[0].request.content)
    assert body == {"projectId": 10001, "name": "v1.0"}

# --- Labels ---

@pytest.mark.asyncio
@respx.mock
async def test_list_labels(server):
    respx.get(f"{API}/label").mock(
        return_value=httpx.Response(200, json={"values": ["bug", "feature"]}),
    )
    assert _r(await server.call_tool("jira_list_labels", {}))["count"] == 2

# --- Bulk ---

@pytest.mark.asyncio
@respx.mock
async def test_bulk_create_issues(server):
    route = respx.post(f"{API}/issue/bulk").mock(
        return_value=httpx.Response(201, json={"issues": [{"id": "1"}], "errors": []}),
    )
    assert _r(await server.call_tool("jira_bulk_create_issues", {
        "issues": [{"fields": {
            "project": {"key": "P"}, "summary": "Test",
            "issuetype": {"name": "Task"},
        }}],
    }))["count"] == 1
    body = json.loads(route.calls[0].request.content)
    assert "issueUpdates" in body
    assert body["issueUpdates"][0]["fields"]["project"] == {"key": "P"}
    assert body["issueUpdates"][0]["fields"]["summary"] == "Test"
