"""Tests for O365 email tool integration."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.o365_tool import register_tools

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _get_result_data(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_msal = MagicMock()
    mock_msal.acquire_token_for_client.return_value = {"access_token": "test-token-123"}
    with patch("mcp_toolbox.tools.o365_tool.O365_TENANT_ID", "tenant_123"), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_ID", "client_123"), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_SECRET", "secret_123"), \
         patch("mcp_toolbox.tools.o365_tool.O365_USER_ID", "user@example.com"), \
         patch("mcp_toolbox.tools.o365_tool._msal_app", mock_msal), \
         patch("mcp_toolbox.tools.o365_tool._http_client", None):
        register_tools(mcp)
        yield mcp


# --- Config & Auth Errors ---


@pytest.mark.asyncio
async def test_missing_credentials():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.o365_tool.O365_TENANT_ID", None), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_ID", None), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_SECRET", None), \
         patch("mcp_toolbox.tools.o365_tool.O365_USER_ID", "user@example.com"), \
         patch("mcp_toolbox.tools.o365_tool._msal_app", None), \
         patch("mcp_toolbox.tools.o365_tool._http_client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="O365 credentials not configured"):
            await mcp.call_tool("o365_list_folders", {})


@pytest.mark.asyncio
async def test_token_acquisition_failure():
    mcp = FastMCP("test")
    mock_msal = MagicMock()
    mock_msal.acquire_token_for_client.return_value = {
        "error": "invalid_client", "error_description": "Bad credentials"
    }
    with patch("mcp_toolbox.tools.o365_tool.O365_TENANT_ID", "t"), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_ID", "c"), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_SECRET", "s"), \
         patch("mcp_toolbox.tools.o365_tool.O365_USER_ID", "u@e.com"), \
         patch("mcp_toolbox.tools.o365_tool._msal_app", mock_msal), \
         patch("mcp_toolbox.tools.o365_tool._http_client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="Failed to acquire O365 token"):
            await mcp.call_tool("o365_list_folders", {})


# --- Sending Tools ---


@pytest.mark.asyncio
@respx.mock
async def test_send_email(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/sendMail").mock(
        return_value=httpx.Response(202)
    )
    result = await server.call_tool("o365_send_email", {
        "to": "recipient@example.com", "subject": "Hello", "body": "<p>Hi</p>",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_send_email_with_attachment(server, tmp_path):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/sendMail").mock(
        return_value=httpx.Response(202)
    )
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello")
    result = await server.call_tool("o365_send_email_with_attachment", {
        "to": "r@example.com", "subject": "With file", "body": "See attached",
        "attachments": [{"file_path": str(test_file)}],
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_reply(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1/reply").mock(
        return_value=httpx.Response(202)
    )
    result = await server.call_tool("o365_reply", {
        "message_id": "msg_1", "comment": "Thanks!",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_reply_all(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1/replyAll").mock(
        return_value=httpx.Response(202)
    )
    result = await server.call_tool("o365_reply_all", {
        "message_id": "msg_1", "comment": "Agreed!",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_forward(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1/forward").mock(
        return_value=httpx.Response(202)
    )
    result = await server.call_tool("o365_forward", {
        "message_id": "msg_1", "to": "other@example.com",
    })
    assert _get_result_data(result)["status"] == "success"


# --- Mailbox Reading ---


@pytest.mark.asyncio
@respx.mock
async def test_list_messages(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/mailFolders/Inbox/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "m1", "subject": "Test"}]})
    )
    result = await server.call_tool("o365_list_messages", {})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_message(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1").mock(
        return_value=httpx.Response(200, json={"id": "msg_1", "subject": "Test"})
    )
    result = await server.call_tool("o365_get_message", {"message_id": "msg_1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_search_messages(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "m1"}]})
    )
    result = await server.call_tool("o365_search_messages", {"query": "subject:invoice"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_attachments(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1/attachments").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "a1", "name": "file.pdf"}]})
    )
    result = await server.call_tool("o365_list_attachments", {"message_id": "msg_1"})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_move_message(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1/move").mock(
        return_value=httpx.Response(200, json={"id": "msg_1"})
    )
    result = await server.call_tool("o365_move_message", {
        "message_id": "msg_1", "destination_folder": "Archive",
    })
    assert _get_result_data(result)["status"] == "success"


# --- Draft Management ---


@pytest.mark.asyncio
@respx.mock
async def test_create_draft(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages").mock(
        return_value=httpx.Response(201, json={"id": "draft_1"})
    )
    result = await server.call_tool("o365_create_draft", {
        "subject": "Draft", "body": "<p>WIP</p>",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_draft(server):
    respx.patch(f"{GRAPH_BASE}/users/user@example.com/messages/draft_1").mock(
        return_value=httpx.Response(200, json={"id": "draft_1"})
    )
    result = await server.call_tool("o365_update_draft", {
        "message_id": "draft_1", "subject": "Updated Draft",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
async def test_update_draft_no_fields(server):
    with pytest.raises(Exception, match="At least one field"):
        await server.call_tool("o365_update_draft", {"message_id": "draft_1"})


@pytest.mark.asyncio
@respx.mock
async def test_add_draft_attachment(server, tmp_path):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/draft_1/attachments").mock(
        return_value=httpx.Response(201, json={"id": "att_1"})
    )
    test_file = tmp_path / "doc.pdf"
    test_file.write_bytes(b"PDF content")
    result = await server.call_tool("o365_add_draft_attachment", {
        "message_id": "draft_1", "file_path": str(test_file),
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_send_draft(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/draft_1/send").mock(
        return_value=httpx.Response(202)
    )
    result = await server.call_tool("o365_send_draft", {"message_id": "draft_1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_draft(server):
    respx.delete(f"{GRAPH_BASE}/users/user@example.com/messages/draft_1").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("o365_delete_draft", {"message_id": "draft_1"})
    assert _get_result_data(result)["status"] == "success"


# --- Folder Management ---


@pytest.mark.asyncio
@respx.mock
async def test_get_folder(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/mailFolders/Inbox").mock(
        return_value=httpx.Response(200, json={"id": "inbox_id", "displayName": "Inbox"})
    )
    result = await server.call_tool("o365_get_folder", {"folder_id": "Inbox"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_folders(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/mailFolders").mock(
        return_value=httpx.Response(200, json={"value": [
            {"id": "f1", "displayName": "Inbox"},
            {"id": "f2", "displayName": "Drafts"},
        ]})
    )
    result = await server.call_tool("o365_list_folders", {})
    data = _get_result_data(result)
    assert data["count"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_create_folder(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/mailFolders").mock(
        return_value=httpx.Response(201, json={"id": "f_new", "displayName": "Custom"})
    )
    result = await server.call_tool("o365_create_folder", {"name": "Custom"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_folder(server):
    respx.delete(f"{GRAPH_BASE}/users/user@example.com/mailFolders/f1").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("o365_delete_folder", {"folder_id": "f1"})
    assert _get_result_data(result)["status"] == "success"


# --- API Error Handling ---


@pytest.mark.asyncio
@respx.mock
async def test_api_error_401(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/mailFolders").mock(
        return_value=httpx.Response(401, json={
            "error": {"code": "InvalidAuthenticationToken", "message": "Token expired"}
        })
    )
    with pytest.raises(Exception, match="Graph API error.*401.*Token expired"):
        await server.call_tool("o365_list_folders", {})


@pytest.mark.asyncio
@respx.mock
async def test_api_error_429(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/mailFolders").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )
    with pytest.raises(Exception, match="rate limit.*30 seconds"):
        await server.call_tool("o365_list_folders", {})
