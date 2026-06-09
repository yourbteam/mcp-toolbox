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
    respx.delete(f"{BASE}/projects/p1").mock(
        return_value=httpx.Response(200, json={"data": {}}))
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
