"""Tests for Slack tool integration."""

import json
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP
from slack_sdk.errors import SlackApiError

from mcp_toolbox.tools.slack_tool import register_tools


def _get_result_data(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_client = MagicMock()
    with patch("mcp_toolbox.tools.slack_tool.SLACK_BOT_TOKEN", "xoxb-test"), \
         patch("mcp_toolbox.tools.slack_tool._slack_client", mock_client):
        register_tools(mcp)
        yield mcp, mock_client


# --- Auth/Error ---

@pytest.mark.asyncio
async def test_missing_token():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.slack_tool.SLACK_BOT_TOKEN", None), \
         patch("mcp_toolbox.tools.slack_tool._slack_client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="SLACK_BOT_TOKEN"):
            await mcp.call_tool("slack_list_channels", {})


@pytest.mark.asyncio
async def test_slack_api_error():
    mcp = FastMCP("test")
    mock_client = MagicMock()
    resp = MagicMock()
    resp.get.return_value = "channel_not_found"
    resp.__getitem__ = lambda s, k: "channel_not_found" if k == "error" else ""
    mock_client.conversations_info.side_effect = SlackApiError("err", resp)
    with patch("mcp_toolbox.tools.slack_tool.SLACK_BOT_TOKEN", "xoxb-test"), \
         patch("mcp_toolbox.tools.slack_tool._slack_client", mock_client):
        register_tools(mcp)
        with pytest.raises(Exception, match="Slack error"):
            await mcp.call_tool("slack_get_channel_info", {"channel": "C123"})


# --- Messaging ---

@pytest.mark.asyncio
async def test_send_message(server):
    mcp, mc = server
    mc.chat_postMessage.return_value = {"ts": "1234.5678", "channel": "C123"}
    result = await mcp.call_tool("slack_send_message", {"channel": "C123", "text": "Hi"})
    assert _get_result_data(result)["ts"] == "1234.5678"

@pytest.mark.asyncio
async def test_send_dm(server):
    mcp, mc = server
    mc.conversations_open.return_value = {"channel": {"id": "D123"}}
    mc.chat_postMessage.return_value = {"ts": "1234.5678", "channel": "D123"}
    result = await mcp.call_tool("slack_send_dm", {"user_id": "U123", "text": "Hi"})
    assert _get_result_data(result)["channel"] == "D123"

@pytest.mark.asyncio
async def test_update_message(server):
    mcp, mc = server
    mc.chat_update.return_value = {"ts": "1234.5678", "channel": "C123"}
    result = await mcp.call_tool("slack_update_message", {
        "channel": "C123", "ts": "1234.5678", "text": "Updated",
    })
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_delete_message(server):
    mcp, mc = server
    mc.chat_delete.return_value = {"ok": True}
    result = await mcp.call_tool("slack_delete_message", {"channel": "C123", "ts": "1234.5678"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_schedule_message(server):
    mcp, mc = server
    mc.chat_scheduleMessage.return_value = {"scheduled_message_id": "Q123"}
    result = await mcp.call_tool("slack_schedule_message", {
        "channel": "C123", "text": "Later", "post_at": 1700000000,
    })
    assert _get_result_data(result)["scheduled_message_id"] == "Q123"

@pytest.mark.asyncio
async def test_get_channel_history(server):
    mcp, mc = server
    mc.conversations_history.return_value = {
        "messages": [{"ts": "1"}], "response_metadata": {"next_cursor": ""},
    }
    result = await mcp.call_tool("slack_get_channel_history", {"channel": "C123"})
    assert _get_result_data(result)["count"] == 1

@pytest.mark.asyncio
async def test_get_thread_replies(server):
    mcp, mc = server
    mc.conversations_replies.return_value = {
        "messages": [{"ts": "1"}, {"ts": "2"}],
        "response_metadata": {"next_cursor": ""},
    }
    result = await mcp.call_tool("slack_get_thread_replies", {"channel": "C123", "ts": "1"})
    assert _get_result_data(result)["count"] == 2

# --- Channel Management ---

@pytest.mark.asyncio
async def test_list_channels(server):
    mcp, mc = server
    mc.conversations_list.return_value = {
        "channels": [{"id": "C1"}], "response_metadata": {"next_cursor": ""},
    }
    result = await mcp.call_tool("slack_list_channels", {})
    assert _get_result_data(result)["count"] == 1

@pytest.mark.asyncio
async def test_get_channel_info(server):
    mcp, mc = server
    mc.conversations_info.return_value = {"channel": {"id": "C1", "name": "general"}}
    result = await mcp.call_tool("slack_get_channel_info", {"channel": "C1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_create_channel(server):
    mcp, mc = server
    mc.conversations_create.return_value = {"channel": {"id": "C_new"}}
    result = await mcp.call_tool("slack_create_channel", {"name": "test-channel"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_archive_channel(server):
    mcp, mc = server
    mc.conversations_archive.return_value = {"ok": True}
    result = await mcp.call_tool("slack_archive_channel", {"channel": "C1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_unarchive_channel(server):
    mcp, mc = server
    mc.conversations_unarchive.return_value = {"ok": True}
    result = await mcp.call_tool("slack_unarchive_channel", {"channel": "C1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_invite_to_channel(server):
    mcp, mc = server
    mc.conversations_invite.return_value = {"channel": {"id": "C1"}}
    result = await mcp.call_tool("slack_invite_to_channel", {"channel": "C1", "users": "U1,U2"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_list_channel_members(server):
    mcp, mc = server
    mc.conversations_members.return_value = {
        "members": ["U1", "U2"], "response_metadata": {"next_cursor": ""},
    }
    result = await mcp.call_tool("slack_list_channel_members", {"channel": "C1"})
    assert _get_result_data(result)["count"] == 2

@pytest.mark.asyncio
async def test_set_channel_topic(server):
    mcp, mc = server
    mc.conversations_setTopic.return_value = {"topic": {"value": "New topic"}}
    result = await mcp.call_tool("slack_set_channel_topic", {"channel": "C1", "topic": "New topic"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_set_channel_purpose(server):
    mcp, mc = server
    mc.conversations_setPurpose.return_value = {"purpose": {"value": "New purpose"}}
    result = await mcp.call_tool("slack_set_channel_purpose", {
        "channel": "C1", "purpose": "New purpose",
    })
    assert _get_result_data(result)["status"] == "success"

# --- Users ---

@pytest.mark.asyncio
async def test_list_users(server):
    mcp, mc = server
    mc.users_list.return_value = {
        "members": [{"id": "U1"}], "response_metadata": {"next_cursor": ""},
    }
    result = await mcp.call_tool("slack_list_users", {})
    assert _get_result_data(result)["count"] == 1

@pytest.mark.asyncio
async def test_get_user_info(server):
    mcp, mc = server
    mc.users_info.return_value = {"user": {"id": "U1", "name": "john"}}
    result = await mcp.call_tool("slack_get_user_info", {"user": "U1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_find_user_by_email(server):
    mcp, mc = server
    mc.users_lookupByEmail.return_value = {"user": {"id": "U1"}}
    result = await mcp.call_tool("slack_find_user_by_email", {"email": "j@e.com"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_get_user_presence(server):
    mcp, mc = server
    mc.users_getPresence.return_value = {"presence": "active", "online": True}
    result = await mcp.call_tool("slack_get_user_presence", {"user": "U1"})
    assert _get_result_data(result)["presence"] == "active"

# --- Reactions ---

@pytest.mark.asyncio
async def test_add_reaction(server):
    mcp, mc = server
    mc.reactions_add.return_value = {"ok": True}
    result = await mcp.call_tool("slack_add_reaction", {
        "channel": "C1", "timestamp": "1234", "name": "thumbsup",
    })
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_remove_reaction(server):
    mcp, mc = server
    mc.reactions_remove.return_value = {"ok": True}
    result = await mcp.call_tool("slack_remove_reaction", {
        "channel": "C1", "timestamp": "1234", "name": "thumbsup",
    })
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_get_reactions(server):
    mcp, mc = server
    mc.reactions_get.return_value = {"message": {"reactions": [{"name": "thumbsup", "count": 2}]}}
    result = await mcp.call_tool("slack_get_reactions", {"channel": "C1", "timestamp": "1234"})
    assert _get_result_data(result)["count"] == 1

# --- Pins ---

@pytest.mark.asyncio
async def test_pin_message(server):
    mcp, mc = server
    mc.pins_add.return_value = {"ok": True}
    result = await mcp.call_tool("slack_pin_message", {"channel": "C1", "timestamp": "1234"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_unpin_message(server):
    mcp, mc = server
    mc.pins_remove.return_value = {"ok": True}
    result = await mcp.call_tool("slack_unpin_message", {"channel": "C1", "timestamp": "1234"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_list_pins(server):
    mcp, mc = server
    mc.pins_list.return_value = {"items": [{"type": "message"}]}
    result = await mcp.call_tool("slack_list_pins", {"channel": "C1"})
    assert _get_result_data(result)["count"] == 1

# --- Files ---

@pytest.mark.asyncio
async def test_upload_file(server, tmp_path):
    mcp, mc = server
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello")
    mc.files_upload_v2.return_value = {"files": [{"id": "F1"}]}
    result = await mcp.call_tool("slack_upload_file", {
        "channel": "C1", "file_path": str(test_file),
    })
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_delete_file(server):
    mcp, mc = server
    mc.files_delete.return_value = {"ok": True}
    result = await mcp.call_tool("slack_delete_file", {"file_id": "F1"})
    assert _get_result_data(result)["status"] == "success"
