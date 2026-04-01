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


# --- Tier 1: Core Task Management ---


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


# --- Tier 2: Task Details ---


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


# --- Tier 3: Time Tracking ---


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


# --- Tier 4: Organizational ---


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


# --- API Error Handling ---


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


# --- Group A: Space CRUD ---


@pytest.mark.asyncio
@respx.mock
async def test_get_space(server):
    respx.get(f"{CLICKUP_BASE}/space/s1").mock(
        return_value=httpx.Response(200, json={"id": "s1", "name": "Eng"})
    )
    result = await server.call_tool("clickup_get_space", {"space_id": "s1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_space(server):
    respx.put(f"{CLICKUP_BASE}/space/s1").mock(
        return_value=httpx.Response(200, json={"id": "s1", "name": "New Name"})
    )
    result = await server.call_tool("clickup_update_space", {"space_id": "s1", "name": "New Name"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_space(server):
    respx.delete(f"{CLICKUP_BASE}/space/s1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("clickup_delete_space", {"space_id": "s1"})
    assert _get_result_data(result)["status"] == "success"


# --- Group B: Folder CRUD ---


@pytest.mark.asyncio
@respx.mock
async def test_get_folders(server):
    respx.get(f"{CLICKUP_BASE}/space/s1/folder").mock(
        return_value=httpx.Response(200, json={"folders": [{"id": "f1"}]})
    )
    result = await server.call_tool("clickup_get_folders", {"space_id": "s1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_folder(server):
    respx.get(f"{CLICKUP_BASE}/folder/f1").mock(
        return_value=httpx.Response(200, json={"id": "f1", "name": "Sprint"})
    )
    result = await server.call_tool("clickup_get_folder", {"folder_id": "f1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_folder(server):
    respx.put(f"{CLICKUP_BASE}/folder/f1").mock(
        return_value=httpx.Response(200, json={"id": "f1", "name": "Renamed"})
    )
    result = await server.call_tool("clickup_update_folder", {"folder_id": "f1", "name": "Renamed"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_folder(server):
    respx.delete(f"{CLICKUP_BASE}/folder/f1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("clickup_delete_folder", {"folder_id": "f1"})
    assert _get_result_data(result)["status"] == "success"


# --- Group C: List CRUD ---


@pytest.mark.asyncio
@respx.mock
async def test_get_list(server):
    respx.get(f"{CLICKUP_BASE}/list/l1").mock(
        return_value=httpx.Response(200, json={"id": "l1", "name": "Backlog"})
    )
    result = await server.call_tool("clickup_get_list", {"list_id": "l1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_list(server):
    respx.put(f"{CLICKUP_BASE}/list/l1").mock(
        return_value=httpx.Response(200, json={"id": "l1", "name": "Updated"})
    )
    result = await server.call_tool("clickup_update_list", {"list_id": "l1", "name": "Updated"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_list(server):
    respx.delete(f"{CLICKUP_BASE}/list/l1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("clickup_delete_list", {"list_id": "l1"})
    assert _get_result_data(result)["status"] == "success"


# --- Group D: Comment Management ---


@pytest.mark.asyncio
@respx.mock
async def test_update_comment(server):
    respx.put(f"{CLICKUP_BASE}/comment/c1").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await server.call_tool("clickup_update_comment", {
        "comment_id": "c1", "comment_text": "Updated text",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_comment(server):
    respx.delete(f"{CLICKUP_BASE}/comment/c1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("clickup_delete_comment", {"comment_id": "c1"})
    assert _get_result_data(result)["status"] == "success"


# --- Group E: Checklist Management ---


@pytest.mark.asyncio
@respx.mock
async def test_update_checklist(server):
    respx.put(f"{CLICKUP_BASE}/checklist/cl_1").mock(
        return_value=httpx.Response(200, json={"checklist": {"id": "cl_1"}})
    )
    result = await server.call_tool("clickup_update_checklist", {
        "checklist_id": "cl_1", "name": "Renamed",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_checklist(server):
    respx.delete(f"{CLICKUP_BASE}/checklist/cl_1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("clickup_delete_checklist", {"checklist_id": "cl_1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_checklist_item(server):
    respx.put(f"{CLICKUP_BASE}/checklist/cl_1/checklist_item/ci_1").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await server.call_tool("clickup_update_checklist_item", {
        "checklist_id": "cl_1", "checklist_item_id": "ci_1", "resolved": True,
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_checklist_item(server):
    respx.delete(f"{CLICKUP_BASE}/checklist/cl_1/checklist_item/ci_1").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("clickup_delete_checklist_item", {
        "checklist_id": "cl_1", "checklist_item_id": "ci_1",
    })
    assert _get_result_data(result)["status"] == "success"


# --- Group F: Time Tracking Extras ---


@pytest.mark.asyncio
@respx.mock
async def test_get_task_time(server):
    respx.get(f"{CLICKUP_BASE}/task/task_abc/time").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "ti_1"}]})
    )
    result = await server.call_tool("clickup_get_task_time", {"task_id": "task_abc"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_task_time(server):
    respx.delete(f"{CLICKUP_BASE}/task/task_abc/time/ti_1").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("clickup_delete_task_time", {
        "task_id": "task_abc", "interval_id": "ti_1",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_time_entry(server):
    respx.put(f"{CLICKUP_BASE}/team/team_123/time_entries/te_1").mock(
        return_value=httpx.Response(200, json={"data": {"id": "te_1"}})
    )
    result = await server.call_tool("clickup_update_time_entry", {
        "timer_id": "te_1", "description": "Updated",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_time_entry(server):
    respx.delete(f"{CLICKUP_BASE}/team/team_123/time_entries/te_1").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("clickup_delete_time_entry", {"timer_id": "te_1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_running_timer(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/time_entries/running").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    result = await server.call_tool("clickup_get_running_timer", {})
    assert _get_result_data(result)["status"] == "success"


# --- Group G: Tag Management ---


@pytest.mark.asyncio
@respx.mock
async def test_get_space_tags(server):
    respx.get(f"{CLICKUP_BASE}/space/s1/tag").mock(
        return_value=httpx.Response(200, json={"tags": [{"name": "urgent"}]})
    )
    result = await server.call_tool("clickup_get_space_tags", {"space_id": "s1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_space_tag(server):
    respx.post(f"{CLICKUP_BASE}/space/s1/tag").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await server.call_tool("clickup_create_space_tag", {
        "space_id": "s1", "name": "bug",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_space_tag(server):
    respx.put(f"{CLICKUP_BASE}/space/s1/tag/bug").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await server.call_tool("clickup_update_space_tag", {
        "space_id": "s1", "tag_name": "bug", "new_name": "defect",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_space_tag(server):
    respx.delete(f"{CLICKUP_BASE}/space/s1/tag/bug").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("clickup_delete_space_tag", {
        "space_id": "s1", "tag_name": "bug",
    })
    assert _get_result_data(result)["status"] == "success"


# --- Group H: Custom Field Removal ---


@pytest.mark.asyncio
@respx.mock
async def test_remove_custom_field(server):
    respx.delete(f"{CLICKUP_BASE}/task/task_abc/field/cf_1").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("clickup_remove_custom_field", {
        "task_id": "task_abc", "field_id": "cf_1",
    })
    assert _get_result_data(result)["status"] == "success"


# --- Group I: Goals ---


@pytest.mark.asyncio
@respx.mock
async def test_get_goals(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/goal").mock(
        return_value=httpx.Response(200, json={"goals": [{"id": "g1"}]})
    )
    result = await server.call_tool("clickup_get_goals", {})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_goal(server):
    respx.post(f"{CLICKUP_BASE}/team/team_123/goal").mock(
        return_value=httpx.Response(200, json={"goal": {"id": "g_new"}})
    )
    result = await server.call_tool("clickup_create_goal", {"name": "Q1 Target"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_goal(server):
    respx.get(f"{CLICKUP_BASE}/goal/g1").mock(
        return_value=httpx.Response(200, json={"goal": {"id": "g1"}})
    )
    result = await server.call_tool("clickup_get_goal", {"goal_id": "g1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_goal(server):
    respx.put(f"{CLICKUP_BASE}/goal/g1").mock(
        return_value=httpx.Response(200, json={"goal": {"id": "g1"}})
    )
    result = await server.call_tool("clickup_update_goal", {"goal_id": "g1", "name": "Updated"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_goal(server):
    respx.delete(f"{CLICKUP_BASE}/goal/g1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("clickup_delete_goal", {"goal_id": "g1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_key_result(server):
    respx.post(f"{CLICKUP_BASE}/goal/g1/key_result").mock(
        return_value=httpx.Response(200, json={"key_result": {"id": "kr_1"}})
    )
    result = await server.call_tool("clickup_create_key_result", {
        "goal_id": "g1", "name": "Revenue", "type": "currency",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_key_result(server):
    respx.put(f"{CLICKUP_BASE}/key_result/kr_1").mock(
        return_value=httpx.Response(200, json={"key_result": {"id": "kr_1"}})
    )
    result = await server.call_tool("clickup_update_key_result", {
        "key_result_id": "kr_1", "steps_current": 50,
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_key_result(server):
    respx.delete(f"{CLICKUP_BASE}/key_result/kr_1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("clickup_delete_key_result", {"key_result_id": "kr_1"})
    assert _get_result_data(result)["status"] == "success"


# --- Group J: Time Entry Details ---


@pytest.mark.asyncio
@respx.mock
async def test_get_time_entry(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/time_entries/te_1").mock(
        return_value=httpx.Response(200, json={"data": {"id": "te_1"}})
    )
    result = await server.call_tool("clickup_get_time_entry", {"timer_id": "te_1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_time_entry_history(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/time_entries/te_1/history").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    result = await server.call_tool("clickup_get_time_entry_history", {"timer_id": "te_1"})
    assert _get_result_data(result)["status"] == "success"


# --- Group K: Time Entry Tags ---


@pytest.mark.asyncio
@respx.mock
async def test_get_time_entry_tags(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/time_entries/tags").mock(
        return_value=httpx.Response(200, json={"data": [{"name": "billable"}]})
    )
    result = await server.call_tool("clickup_get_time_entry_tags", {})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_add_time_entry_tags(server):
    respx.post(f"{CLICKUP_BASE}/team/team_123/time_entries/tags").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await server.call_tool("clickup_add_time_entry_tags", {
        "time_entry_ids": ["te_1"], "tags": [{"name": "billable"}],
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_remove_time_entry_tags(server):
    respx.delete(f"{CLICKUP_BASE}/team/team_123/time_entries/tags").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await server.call_tool("clickup_remove_time_entry_tags", {
        "time_entry_ids": ["te_1"], "tags": [{"name": "billable"}],
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_rename_time_entry_tag(server):
    respx.put(f"{CLICKUP_BASE}/team/team_123/time_entries/tags").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await server.call_tool("clickup_rename_time_entry_tag", {
        "name": "billable", "new_name": "invoiced",
    })
    assert _get_result_data(result)["status"] == "success"


# --- Group L: Views ---


@pytest.mark.asyncio
@respx.mock
async def test_get_workspace_views(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/view").mock(
        return_value=httpx.Response(200, json={"views": [{"id": "v1"}]})
    )
    result = await server.call_tool("clickup_get_workspace_views", {})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_workspace_view(server):
    respx.post(f"{CLICKUP_BASE}/team/team_123/view").mock(
        return_value=httpx.Response(200, json={"view": {"id": "v_new"}})
    )
    result = await server.call_tool("clickup_create_workspace_view", {
        "name": "Board", "type": "board",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_space_views(server):
    respx.get(f"{CLICKUP_BASE}/space/s1/view").mock(
        return_value=httpx.Response(200, json={"views": []})
    )
    result = await server.call_tool("clickup_get_space_views", {"space_id": "s1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_space_view(server):
    respx.post(f"{CLICKUP_BASE}/space/s1/view").mock(
        return_value=httpx.Response(200, json={"view": {"id": "v2"}})
    )
    result = await server.call_tool("clickup_create_space_view", {
        "space_id": "s1", "name": "Calendar", "type": "calendar",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_folder_views(server):
    respx.get(f"{CLICKUP_BASE}/folder/f1/view").mock(
        return_value=httpx.Response(200, json={"views": []})
    )
    result = await server.call_tool("clickup_get_folder_views", {"folder_id": "f1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_folder_view(server):
    respx.post(f"{CLICKUP_BASE}/folder/f1/view").mock(
        return_value=httpx.Response(200, json={"view": {"id": "v3"}})
    )
    result = await server.call_tool("clickup_create_folder_view", {
        "folder_id": "f1", "name": "Gantt", "type": "gantt",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_list_views(server):
    respx.get(f"{CLICKUP_BASE}/list/l1/view").mock(
        return_value=httpx.Response(200, json={"views": []})
    )
    result = await server.call_tool("clickup_get_list_views", {"list_id": "l1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_list_view(server):
    respx.post(f"{CLICKUP_BASE}/list/l1/view").mock(
        return_value=httpx.Response(200, json={"view": {"id": "v4"}})
    )
    result = await server.call_tool("clickup_create_list_view", {
        "list_id": "l1", "name": "Table", "type": "table",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_view(server):
    respx.get(f"{CLICKUP_BASE}/view/v1").mock(
        return_value=httpx.Response(200, json={"view": {"id": "v1"}})
    )
    result = await server.call_tool("clickup_get_view", {"view_id": "v1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_view(server):
    respx.put(f"{CLICKUP_BASE}/view/v1").mock(
        return_value=httpx.Response(200, json={"view": {"id": "v1"}})
    )
    result = await server.call_tool("clickup_update_view", {"view_id": "v1", "name": "Renamed"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_view(server):
    respx.delete(f"{CLICKUP_BASE}/view/v1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("clickup_delete_view", {"view_id": "v1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_view_tasks(server):
    respx.get(f"{CLICKUP_BASE}/view/v1/task").mock(
        return_value=httpx.Response(200, json={"tasks": [{"id": "t1"}]})
    )
    result = await server.call_tool("clickup_get_view_tasks", {"view_id": "v1"})
    assert _get_result_data(result)["status"] == "success"


# --- Group M: Webhooks ---


@pytest.mark.asyncio
@respx.mock
async def test_get_webhooks(server):
    respx.get(f"{CLICKUP_BASE}/team/team_123/webhook").mock(
        return_value=httpx.Response(200, json={"webhooks": [{"id": "wh_1"}]})
    )
    result = await server.call_tool("clickup_get_webhooks", {})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_webhook(server):
    respx.post(f"{CLICKUP_BASE}/team/team_123/webhook").mock(
        return_value=httpx.Response(200, json={"id": "wh_new", "webhook": {"id": "wh_new"}})
    )
    result = await server.call_tool("clickup_create_webhook", {
        "endpoint": "https://example.com/hook", "events": ["taskCreated"],
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_webhook(server):
    respx.put(f"{CLICKUP_BASE}/webhook/wh_1").mock(
        return_value=httpx.Response(200, json={"id": "wh_1"})
    )
    result = await server.call_tool("clickup_update_webhook", {
        "webhook_id": "wh_1", "status": "inactive",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_webhook(server):
    respx.delete(f"{CLICKUP_BASE}/webhook/wh_1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("clickup_delete_webhook", {"webhook_id": "wh_1"})
    assert _get_result_data(result)["status"] == "success"
