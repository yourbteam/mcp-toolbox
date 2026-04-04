"""Tests for Google Tasks tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.gtasks_tool import register_tools

BASE = "https://tasks.googleapis.com/tasks/v1"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


def _ok(result) -> None:
    assert _r(result)["status"] == "success"


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_creds = type("C", (), {
        "valid": True, "token": "tok", "refresh": lambda self, r: None,
    })()
    with patch(
        "mcp_toolbox.tools.gtasks_tool.GOOGLE_SERVICE_ACCOUNT_JSON",
        "/fake/key.json",
    ), patch(
        "mcp_toolbox.tools.gtasks_tool.GTASKS_DELEGATED_USER",
        "user@test.com",
    ), patch(
        "mcp_toolbox.tools.gtasks_tool._credentials", mock_creds,
    ), patch(
        "mcp_toolbox.tools.gtasks_tool._client", None,
    ):
        register_tools(mcp)
        yield mcp


# --- Auth/Error ---

@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with patch(
        "mcp_toolbox.tools.gtasks_tool.GOOGLE_SERVICE_ACCOUNT_JSON", None,
    ), patch(
        "mcp_toolbox.tools.gtasks_tool.GTASKS_DELEGATED_USER", None,
    ), patch(
        "mcp_toolbox.tools.gtasks_tool._credentials", None,
    ), patch(
        "mcp_toolbox.tools.gtasks_tool._client", None,
    ):
        register_tools(mcp)
        with pytest.raises(Exception, match="GOOGLE_SERVICE_ACCOUNT_JSON"):
            await mcp.call_tool("gtasks_list_tasklists", {})


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit(server):
    respx.get(f"{BASE}/users/@me/lists").mock(
        return_value=httpx.Response(429),
    )
    with pytest.raises(Exception, match="rate limit"):
        await server.call_tool("gtasks_list_tasklists", {})


# --- Task Lists ---

@pytest.mark.asyncio
@respx.mock
async def test_list_tasklists(server):
    respx.get(f"{BASE}/users/@me/lists").mock(
        return_value=httpx.Response(200, json={
            "items": [{"id": "tl1", "title": "My Tasks"}],
        }),
    )
    r = _r(await server.call_tool("gtasks_list_tasklists", {}))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_tasklist(server):
    respx.get(f"{BASE}/users/@me/lists/tl1").mock(
        return_value=httpx.Response(200, json={"id": "tl1"}),
    )
    _ok(await server.call_tool(
        "gtasks_get_tasklist", {"tasklist_id": "tl1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_insert_tasklist(server):
    route = respx.post(f"{BASE}/users/@me/lists").mock(
        return_value=httpx.Response(200, json={"id": "tl2", "title": "New"}),
    )
    _ok(await server.call_tool(
        "gtasks_insert_tasklist", {"title": "New"},
    ))
    body = json.loads(route.calls[0].request.content)
    assert body["title"] == "New"


@pytest.mark.asyncio
@respx.mock
async def test_update_tasklist(server):
    route = respx.put(f"{BASE}/users/@me/lists/tl1").mock(
        return_value=httpx.Response(200, json={"id": "tl1"}),
    )
    _ok(await server.call_tool(
        "gtasks_update_tasklist", {"tasklist_id": "tl1", "title": "Updated"},
    ))
    body = json.loads(route.calls[0].request.content)
    assert body["title"] == "Updated"


@pytest.mark.asyncio
@respx.mock
async def test_patch_tasklist(server):
    route = respx.patch(f"{BASE}/users/@me/lists/tl1").mock(
        return_value=httpx.Response(200, json={"id": "tl1"}),
    )
    _ok(await server.call_tool(
        "gtasks_patch_tasklist", {"tasklist_id": "tl1", "title": "Patched"},
    ))
    body = json.loads(route.calls[0].request.content)
    assert body["title"] == "Patched"


@pytest.mark.asyncio
async def test_patch_tasklist_no_fields(server):
    with pytest.raises(Exception, match="At least one field"):
        await server.call_tool(
            "gtasks_patch_tasklist", {"tasklist_id": "tl1"},
        )


@pytest.mark.asyncio
@respx.mock
async def test_delete_tasklist(server):
    respx.delete(f"{BASE}/users/@me/lists/tl1").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gtasks_delete_tasklist", {"tasklist_id": "tl1"},
    ))


# --- Tasks ---

@pytest.mark.asyncio
@respx.mock
async def test_list_tasks(server):
    respx.get(f"{BASE}/lists/@default/tasks").mock(
        return_value=httpx.Response(200, json={
            "items": [{"id": "t1", "title": "Buy milk"}],
        }),
    )
    r = _r(await server.call_tool("gtasks_list_tasks", {}))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_task(server):
    respx.get(f"{BASE}/lists/@default/tasks/t1").mock(
        return_value=httpx.Response(200, json={"id": "t1"}),
    )
    _ok(await server.call_tool("gtasks_get_task", {"task_id": "t1"}))


@pytest.mark.asyncio
@respx.mock
async def test_insert_task(server):
    route = respx.post(f"{BASE}/lists/@default/tasks").mock(
        return_value=httpx.Response(200, json={"id": "t2"}),
    )
    _ok(await server.call_tool(
        "gtasks_insert_task", {"title": "New task"},
    ))
    body = json.loads(route.calls[0].request.content)
    assert body["title"] == "New task"


@pytest.mark.asyncio
@respx.mock
async def test_insert_task_with_parent_and_notes(server):
    route = respx.post(f"{BASE}/lists/@default/tasks").mock(
        return_value=httpx.Response(200, json={"id": "t3"}),
    )
    _ok(await server.call_tool("gtasks_insert_task", {
        "title": "Sub task", "notes": "Details here",
        "parent": "t1", "previous": "t2",
    }))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["title"] == "Sub task"
    assert body["notes"] == "Details here"
    assert req.url.params["parent"] == "t1"
    assert req.url.params["previous"] == "t2"


@pytest.mark.asyncio
@respx.mock
async def test_update_task(server):
    route = respx.put(f"{BASE}/lists/@default/tasks/t1").mock(
        return_value=httpx.Response(200, json={"id": "t1"}),
    )
    _ok(await server.call_tool("gtasks_update_task", {
        "task_id": "t1", "title": "Updated",
    }))
    body = json.loads(route.calls[0].request.content)
    assert body["id"] == "t1"
    assert body["title"] == "Updated"


@pytest.mark.asyncio
@respx.mock
async def test_patch_task(server):
    route = respx.patch(f"{BASE}/lists/@default/tasks/t1").mock(
        return_value=httpx.Response(200, json={"id": "t1"}),
    )
    _ok(await server.call_tool("gtasks_patch_task", {
        "task_id": "t1", "status": "completed",
    }))
    body = json.loads(route.calls[0].request.content)
    assert body["status"] == "completed"
    assert "title" not in body  # only provided fields


@pytest.mark.asyncio
async def test_patch_task_no_fields(server):
    with pytest.raises(Exception, match="At least one field"):
        await server.call_tool("gtasks_patch_task", {"task_id": "t1"})


@pytest.mark.asyncio
@respx.mock
async def test_delete_task(server):
    respx.delete(f"{BASE}/lists/@default/tasks/t1").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool("gtasks_delete_task", {"task_id": "t1"}))


# --- Ordering & Bulk ---

@pytest.mark.asyncio
@respx.mock
async def test_move_task(server):
    route = respx.post(f"{BASE}/lists/@default/tasks/t1/move").mock(
        return_value=httpx.Response(200, json={"id": "t1"}),
    )
    _ok(await server.call_tool("gtasks_move_task", {
        "task_id": "t1", "previous": "t0",
    }))
    req = route.calls[0].request
    assert req.url.params["previous"] == "t0"


@pytest.mark.asyncio
@respx.mock
async def test_clear_tasks(server):
    respx.post(f"{BASE}/lists/@default/clear").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool("gtasks_clear_tasks", {}))
