"""Tests for Microsoft Teams tool integration."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.teams_tool import register_tools

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _get_result_data(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_msal = MagicMock()
    mock_msal.acquire_token_for_client.return_value = {"access_token": "test-token"}
    with patch("mcp_toolbox.tools.teams_tool.TEAMS_TENANT_ID", "tenant_t"), \
         patch("mcp_toolbox.tools.teams_tool.TEAMS_CLIENT_ID", "client_t"), \
         patch("mcp_toolbox.tools.teams_tool.TEAMS_CLIENT_SECRET", "secret_t"), \
         patch("mcp_toolbox.tools.teams_tool.O365_USER_ID", "user@example.com"), \
         patch("mcp_toolbox.tools.teams_tool._msal_app", mock_msal), \
         patch("mcp_toolbox.tools.teams_tool._http_client", None):
        register_tools(mcp)
        yield mcp


# --- Auth & Error Tests ---


@pytest.mark.asyncio
async def test_missing_credentials():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.teams_tool.TEAMS_TENANT_ID", None), \
         patch("mcp_toolbox.tools.teams_tool.TEAMS_CLIENT_ID", None), \
         patch("mcp_toolbox.tools.teams_tool.TEAMS_CLIENT_SECRET", None), \
         patch("mcp_toolbox.tools.teams_tool.O365_USER_ID", "u@e.com"), \
         patch("mcp_toolbox.tools.teams_tool._msal_app", None), \
         patch("mcp_toolbox.tools.teams_tool._http_client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="Teams credentials not configured"):
            await mcp.call_tool("teams_list_teams", {})


@pytest.mark.asyncio
@respx.mock
async def test_api_error_401(server):
    respx.get(f"{GRAPH_BASE}/teams").mock(
        return_value=httpx.Response(401, json={
            "error": {"code": "Unauthorized", "message": "Invalid token"}
        })
    )
    with pytest.raises(Exception, match="Teams Graph API error.*401"):
        await server.call_tool("teams_list_teams", {})


@pytest.mark.asyncio
@respx.mock
async def test_api_error_429(server):
    respx.get(f"{GRAPH_BASE}/teams").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "10"})
    )
    with pytest.raises(Exception, match="rate limit.*10 seconds"):
        await server.call_tool("teams_list_teams", {})


# --- Teams Management ---


@pytest.mark.asyncio
@respx.mock
async def test_list_teams(server):
    respx.get(f"{GRAPH_BASE}/teams").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "t1"}]})
    )
    result = await server.call_tool("teams_list_teams", {})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_team(server):
    respx.get(f"{GRAPH_BASE}/teams/t1").mock(
        return_value=httpx.Response(200, json={"id": "t1", "displayName": "Eng"})
    )
    result = await server.call_tool("teams_get_team", {"team_id": "t1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_team(server):
    route = respx.post(f"{GRAPH_BASE}/teams").mock(return_value=httpx.Response(202))
    result = await server.call_tool("teams_create_team", {
        "display_name": "New Team", "owner_id": "user_1",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["displayName"] == "New Team"
    assert body["visibility"] == "private"
    assert body["template@odata.bind"] == (
        "https://graph.microsoft.com/v1.0/teamsTemplates('standard')"
    )
    assert len(body["members"]) == 1
    assert body["members"][0]["roles"] == ["owner"]
    assert "users('user_1')" in body["members"][0]["user@odata.bind"]


@pytest.mark.asyncio
@respx.mock
async def test_update_team(server):
    route = respx.patch(f"{GRAPH_BASE}/teams/t1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("teams_update_team", {
        "team_id": "t1", "display_name": "Renamed",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["displayName"] == "Renamed"


@pytest.mark.asyncio
@respx.mock
async def test_archive_team(server):
    route = respx.post(f"{GRAPH_BASE}/teams/t1/archive").mock(return_value=httpx.Response(202))
    result = await server.call_tool("teams_archive_team", {"team_id": "t1"})
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body == {}


@pytest.mark.asyncio
@respx.mock
async def test_unarchive_team(server):
    route = respx.post(f"{GRAPH_BASE}/teams/t1/unarchive").mock(return_value=httpx.Response(202))
    result = await server.call_tool("teams_unarchive_team", {"team_id": "t1"})
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body == {}


@pytest.mark.asyncio
@respx.mock
async def test_list_members(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/members").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "m1"}]})
    )
    result = await server.call_tool("teams_list_members", {"team_id": "t1"})
    assert _get_result_data(result)["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_add_member(server):
    route = respx.post(f"{GRAPH_BASE}/teams/t1/members").mock(
        return_value=httpx.Response(201, json={"id": "m_new"})
    )
    result = await server.call_tool("teams_add_member", {"team_id": "t1", "user_id": "u1"})
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["@odata.type"] == "#microsoft.graph.aadUserConversationMember"
    assert body["roles"] == []
    assert "users('u1')" in body["user@odata.bind"]


@pytest.mark.asyncio
@respx.mock
async def test_remove_member(server):
    respx.delete(f"{GRAPH_BASE}/teams/t1/members/m1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("teams_remove_member", {
        "team_id": "t1", "membership_id": "m1",
    })
    assert _get_result_data(result)["status"] == "success"


# --- Channel Management ---


@pytest.mark.asyncio
@respx.mock
async def test_list_channels(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/channels").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "c1"}]})
    )
    result = await server.call_tool("teams_list_channels", {"team_id": "t1"})
    assert _get_result_data(result)["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_channel(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/channels/c1").mock(
        return_value=httpx.Response(200, json={"id": "c1"})
    )
    result = await server.call_tool("teams_get_channel", {"team_id": "t1", "channel_id": "c1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_channel(server):
    route = respx.post(f"{GRAPH_BASE}/teams/t1/channels").mock(
        return_value=httpx.Response(201, json={"id": "c_new"})
    )
    result = await server.call_tool("teams_create_channel", {
        "team_id": "t1", "display_name": "General",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["displayName"] == "General"
    assert body["membershipType"] == "standard"


@pytest.mark.asyncio
@respx.mock
async def test_update_channel(server):
    route = respx.patch(f"{GRAPH_BASE}/teams/t1/channels/c1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("teams_update_channel", {
        "team_id": "t1", "channel_id": "c1", "display_name": "Renamed",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["displayName"] == "Renamed"


@pytest.mark.asyncio
@respx.mock
async def test_delete_channel(server):
    respx.delete(f"{GRAPH_BASE}/teams/t1/channels/c1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("teams_delete_channel", {"team_id": "t1", "channel_id": "c1"})
    assert _get_result_data(result)["status"] == "success"


# --- Messaging ---


@pytest.mark.asyncio
@respx.mock
async def test_list_channel_messages(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/channels/c1/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "msg1"}]})
    )
    result = await server.call_tool("teams_list_channel_messages", {
        "team_id": "t1", "channel_id": "c1",
    })
    assert _get_result_data(result)["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_message(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/channels/c1/messages/msg1").mock(
        return_value=httpx.Response(200, json={"id": "msg1"})
    )
    result = await server.call_tool("teams_get_message", {
        "team_id": "t1", "channel_id": "c1", "message_id": "msg1",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_message_replies(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/channels/c1/messages/msg1/replies").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "r1"}]})
    )
    result = await server.call_tool("teams_list_message_replies", {
        "team_id": "t1", "channel_id": "c1", "message_id": "msg1",
    })
    assert _get_result_data(result)["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_send_webhook_message(server):
    webhook_url = "https://prod-123.westus.logic.azure.com/workflows/abc/triggers/manual"
    route = respx.post(webhook_url).mock(return_value=httpx.Response(200))
    result = await server.call_tool("teams_send_webhook_message", {
        "webhook_url": webhook_url, "text": "Hello Teams!",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["text"] == "Hello Teams!"


@pytest.mark.asyncio
async def test_send_channel_message_delegated_fails(server):
    with pytest.raises(Exception, match="delegated"):
        await server.call_tool("teams_send_channel_message_delegated", {
            "team_id": "t1", "channel_id": "c1", "content": "Hello",
        })


# --- Meetings ---


@pytest.mark.asyncio
@respx.mock
async def test_create_meeting(server):
    route = respx.post(f"{GRAPH_BASE}/users/user@example.com/onlineMeetings").mock(
        return_value=httpx.Response(201, json={"id": "m1", "joinWebUrl": "https://..."})
    )
    result = await server.call_tool("teams_create_meeting", {
        "subject": "Standup", "start_time": "2025-06-15T10:00:00Z",
        "end_time": "2025-06-15T10:30:00Z",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["subject"] == "Standup"
    assert body["startDateTime"] == "2025-06-15T10:00:00Z"
    assert body["endDateTime"] == "2025-06-15T10:30:00Z"


@pytest.mark.asyncio
@respx.mock
async def test_list_meetings(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/onlineMeetings").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "m1"}]})
    )
    result = await server.call_tool("teams_list_meetings", {
        "join_web_url": "https://teams.microsoft.com/l/meetup/test",
    })
    assert _get_result_data(result)["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_meeting(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/onlineMeetings/m1").mock(
        return_value=httpx.Response(200, json={"id": "m1"})
    )
    result = await server.call_tool("teams_get_meeting", {"meeting_id": "m1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_meeting(server):
    respx.delete(f"{GRAPH_BASE}/users/user@example.com/onlineMeetings/m1").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("teams_delete_meeting", {"meeting_id": "m1"})
    assert _get_result_data(result)["status"] == "success"


# --- Presence & Chat ---


@pytest.mark.asyncio
@respx.mock
async def test_get_presence(server):
    respx.get(f"{GRAPH_BASE}/users/u1/presence").mock(
        return_value=httpx.Response(200, json={"availability": "Available"})
    )
    result = await server.call_tool("teams_get_presence", {"user_id": "u1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_get_presence_bulk(server):
    route = respx.post(f"{GRAPH_BASE}/communications/getPresencesByUserId").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "u1"}]})
    )
    result = await server.call_tool("teams_get_presence_bulk", {"user_ids": ["u1", "u2"]})
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["ids"] == ["u1", "u2"]


@pytest.mark.asyncio
@respx.mock
async def test_list_chats(server):
    respx.get(f"{GRAPH_BASE}/users/u1/chats").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "chat1"}]})
    )
    result = await server.call_tool("teams_list_chats", {"user_id": "u1"})
    assert _get_result_data(result)["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_chat(server):
    respx.get(f"{GRAPH_BASE}/chats/chat1").mock(
        return_value=httpx.Response(200, json={"id": "chat1"})
    )
    result = await server.call_tool("teams_get_chat", {"chat_id": "chat1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_chat_messages(server):
    respx.get(f"{GRAPH_BASE}/chats/chat1/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "cm1"}]})
    )
    result = await server.call_tool("teams_list_chat_messages", {"chat_id": "chat1"})
    assert _get_result_data(result)["count"] == 1
