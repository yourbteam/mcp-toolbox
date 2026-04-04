"""Tests for Gmail API tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.gmail_tool import register_tools

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


def _ok(result) -> None:
    assert _r(result)["status"] == "success"


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_creds = type("C", (), {
        "valid": True, "token": "tok",
        "refresh": lambda self, r: None,
    })()
    with patch(
        "mcp_toolbox.tools.gmail_tool.GOOGLE_SERVICE_ACCOUNT_JSON",
        "/fake/key.json",
    ), patch(
        "mcp_toolbox.tools.gmail_tool.GMAIL_DELEGATED_USER",
        "user@test.com",
    ), patch(
        "mcp_toolbox.tools.gmail_tool._credentials", mock_creds,
    ), patch(
        "mcp_toolbox.tools.gmail_tool._client", None,
    ):
        register_tools(mcp)
        yield mcp


# ================================================================
# Auth / Error tests
# ================================================================

@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with patch(
        "mcp_toolbox.tools.gmail_tool"
        ".GOOGLE_SERVICE_ACCOUNT_JSON", None,
    ), patch(
        "mcp_toolbox.tools.gmail_tool.GMAIL_DELEGATED_USER",
        None,
    ), patch(
        "mcp_toolbox.tools.gmail_tool._credentials", None,
    ), patch(
        "mcp_toolbox.tools.gmail_tool._client", None,
    ):
        register_tools(mcp)
        with pytest.raises(
            Exception, match="GOOGLE_SERVICE_ACCOUNT_JSON",
        ):
            await mcp.call_tool(
                "gmail_list_messages", {},
            )


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit(server):
    respx.get(f"{BASE}/messages").mock(
        return_value=httpx.Response(429),
    )
    with pytest.raises(Exception, match="rate limit"):
        await server.call_tool("gmail_list_messages", {})


# ================================================================
# TIER 1: MESSAGES (12 tools)
# ================================================================

@pytest.mark.asyncio
@respx.mock
async def test_send_message(server):
    route = respx.post(f"{BASE}/messages/send").mock(
        return_value=httpx.Response(200, json={
            "id": "m1", "threadId": "t1",
        }),
    )
    _ok(await server.call_tool("gmail_send_message", {
        "to": "bob@test.com",
        "subject": "Hi",
        "body": "Hello",
    }))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "raw" in body


@pytest.mark.asyncio
@respx.mock
async def test_send_message_with_attachment(server):
    route = respx.post(f"{BASE}/messages/send").mock(
        return_value=httpx.Response(200, json={
            "id": "m2", "threadId": "t1",
        }),
    )
    _ok(await server.call_tool(
        "gmail_send_message_with_attachment", {
            "to": "bob@test.com",
            "subject": "File",
            "body": "See attached",
            "attachment_data": "aGVsbG8=",
            "attachment_filename": "hello.txt",
            "attachment_content_type": "text/plain",
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "raw" in body


@pytest.mark.asyncio
@respx.mock
async def test_list_messages(server):
    respx.get(f"{BASE}/messages").mock(
        return_value=httpx.Response(200, json={
            "messages": [{"id": "m1", "threadId": "t1"}],
        }),
    )
    r = _r(await server.call_tool(
        "gmail_list_messages", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_messages_with_query(server):
    respx.get(f"{BASE}/messages").mock(
        return_value=httpx.Response(200, json={
            "messages": [{"id": "m1"}],
            "nextPageToken": "tok2",
        }),
    )
    r = _r(await server.call_tool("gmail_list_messages", {
        "query": "from:alice@test.com",
        "max_results": 10,
    }))
    assert r["next_page_token"] == "tok2"


@pytest.mark.asyncio
@respx.mock
async def test_get_message(server):
    respx.get(f"{BASE}/messages/m1").mock(
        return_value=httpx.Response(200, json={
            "id": "m1", "payload": {
                "mimeType": "text/plain",
                "body": {"data": "aGVsbG8="},
            },
        }),
    )
    _ok(await server.call_tool(
        "gmail_get_message", {"message_id": "m1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_modify_message(server):
    route = respx.post(f"{BASE}/messages/m1/modify").mock(
        return_value=httpx.Response(200, json={
            "id": "m1", "labelIds": ["INBOX", "STARRED"],
        }),
    )
    _ok(await server.call_tool("gmail_modify_message", {
        "message_id": "m1",
        "add_label_ids": ["STARRED"],
    }))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["addLabelIds"] == ["STARRED"]


@pytest.mark.asyncio
@respx.mock
async def test_delete_message(server):
    respx.delete(f"{BASE}/messages/m1").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gmail_delete_message", {"message_id": "m1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_trash_message(server):
    respx.post(f"{BASE}/messages/m1/trash").mock(
        return_value=httpx.Response(200, json={
            "id": "m1", "labelIds": ["TRASH"],
        }),
    )
    _ok(await server.call_tool(
        "gmail_trash_message", {"message_id": "m1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_untrash_message(server):
    respx.post(f"{BASE}/messages/m1/untrash").mock(
        return_value=httpx.Response(200, json={
            "id": "m1", "labelIds": ["INBOX"],
        }),
    )
    _ok(await server.call_tool(
        "gmail_untrash_message", {"message_id": "m1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_batch_modify_messages(server):
    route = respx.post(f"{BASE}/messages/batchModify").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gmail_batch_modify_messages", {
            "message_ids": ["m1", "m2"],
            "add_label_ids": ["STARRED"],
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["ids"] == ["m1", "m2"]
    assert body["addLabelIds"] == ["STARRED"]


@pytest.mark.asyncio
@respx.mock
async def test_batch_delete_messages(server):
    route = respx.post(f"{BASE}/messages/batchDelete").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gmail_batch_delete_messages", {
            "message_ids": ["m1", "m2"],
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["ids"] == ["m1", "m2"]


@pytest.mark.asyncio
@respx.mock
async def test_import_message(server):
    respx.post(f"{BASE}/messages/import").mock(
        return_value=httpx.Response(200, json={
            "id": "m3",
        }),
    )
    _ok(await server.call_tool("gmail_import_message", {
        "raw": "cmF3IG1lc3NhZ2U=",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_insert_message(server):
    respx.post(f"{BASE}/messages").mock(
        return_value=httpx.Response(200, json={
            "id": "m4",
        }),
    )
    _ok(await server.call_tool("gmail_insert_message", {
        "raw": "cmF3IG1lc3NhZ2U=",
    }))


# ================================================================
# TIER 2: THREADS (6 tools)
# ================================================================

@pytest.mark.asyncio
@respx.mock
async def test_list_threads(server):
    respx.get(f"{BASE}/threads").mock(
        return_value=httpx.Response(200, json={
            "threads": [{"id": "t1", "snippet": "Hi"}],
        }),
    )
    r = _r(await server.call_tool(
        "gmail_list_threads", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_threads_with_query(server):
    respx.get(f"{BASE}/threads").mock(
        return_value=httpx.Response(200, json={
            "threads": [{"id": "t1"}],
            "nextPageToken": "npt",
        }),
    )
    r = _r(await server.call_tool("gmail_list_threads", {
        "query": "is:unread",
    }))
    assert r["next_page_token"] == "npt"


@pytest.mark.asyncio
@respx.mock
async def test_get_thread(server):
    respx.get(f"{BASE}/threads/t1").mock(
        return_value=httpx.Response(200, json={
            "id": "t1",
            "messages": [{"id": "m1"}],
        }),
    )
    _ok(await server.call_tool(
        "gmail_get_thread", {"thread_id": "t1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_modify_thread(server):
    route = respx.post(f"{BASE}/threads/t1/modify").mock(
        return_value=httpx.Response(200, json={
            "id": "t1",
        }),
    )
    _ok(await server.call_tool("gmail_modify_thread", {
        "thread_id": "t1",
        "add_label_ids": ["IMPORTANT"],
    }))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["addLabelIds"] == ["IMPORTANT"]


@pytest.mark.asyncio
@respx.mock
async def test_delete_thread(server):
    respx.delete(f"{BASE}/threads/t1").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gmail_delete_thread", {"thread_id": "t1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_trash_thread(server):
    respx.post(f"{BASE}/threads/t1/trash").mock(
        return_value=httpx.Response(200, json={
            "id": "t1",
        }),
    )
    _ok(await server.call_tool(
        "gmail_trash_thread", {"thread_id": "t1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_untrash_thread(server):
    respx.post(f"{BASE}/threads/t1/untrash").mock(
        return_value=httpx.Response(200, json={
            "id": "t1",
        }),
    )
    _ok(await server.call_tool(
        "gmail_untrash_thread", {"thread_id": "t1"},
    ))


# ================================================================
# TIER 3: LABELS (6 tools)
# ================================================================

@pytest.mark.asyncio
@respx.mock
async def test_list_labels(server):
    respx.get(f"{BASE}/labels").mock(
        return_value=httpx.Response(200, json={
            "labels": [
                {"id": "INBOX", "name": "INBOX"},
                {"id": "SENT", "name": "SENT"},
            ],
        }),
    )
    r = _r(await server.call_tool("gmail_list_labels", {}))
    assert r["count"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_label(server):
    respx.get(f"{BASE}/labels/INBOX").mock(
        return_value=httpx.Response(200, json={
            "id": "INBOX", "name": "INBOX",
        }),
    )
    _ok(await server.call_tool(
        "gmail_get_label", {"label_id": "INBOX"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_create_label(server):
    route = respx.post(f"{BASE}/labels").mock(
        return_value=httpx.Response(200, json={
            "id": "Label_1", "name": "Projects",
        }),
    )
    _ok(await server.call_tool("gmail_create_label", {
        "name": "Projects",
    }))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["name"] == "Projects"


@pytest.mark.asyncio
@respx.mock
async def test_create_label_with_color(server):
    route = respx.post(f"{BASE}/labels").mock(
        return_value=httpx.Response(200, json={
            "id": "Label_2", "name": "Urgent",
        }),
    )
    _ok(await server.call_tool("gmail_create_label", {
        "name": "Urgent",
        "background_color": "#ff0000",
        "text_color": "#ffffff",
    }))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["name"] == "Urgent"
    assert "color" in body


@pytest.mark.asyncio
@respx.mock
async def test_update_label(server):
    respx.put(f"{BASE}/labels/Label_1").mock(
        return_value=httpx.Response(200, json={
            "id": "Label_1", "name": "Updated",
        }),
    )
    _ok(await server.call_tool("gmail_update_label", {
        "label_id": "Label_1", "name": "Updated",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_patch_label(server):
    respx.patch(f"{BASE}/labels/Label_1").mock(
        return_value=httpx.Response(200, json={
            "id": "Label_1", "name": "Patched",
        }),
    )
    _ok(await server.call_tool("gmail_patch_label", {
        "label_id": "Label_1", "name": "Patched",
    }))


@pytest.mark.asyncio
async def test_patch_label_no_fields(server):
    with pytest.raises(Exception, match="At least one field"):
        await server.call_tool(
            "gmail_patch_label", {"label_id": "Label_1"},
        )


@pytest.mark.asyncio
@respx.mock
async def test_delete_label(server):
    respx.delete(f"{BASE}/labels/Label_1").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gmail_delete_label", {"label_id": "Label_1"},
    ))


# ================================================================
# TIER 4: DRAFTS (6 tools)
# ================================================================

@pytest.mark.asyncio
@respx.mock
async def test_list_drafts(server):
    respx.get(f"{BASE}/drafts").mock(
        return_value=httpx.Response(200, json={
            "drafts": [{"id": "d1", "message": {"id": "m1"}}],
        }),
    )
    r = _r(await server.call_tool(
        "gmail_list_drafts", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_draft(server):
    respx.get(f"{BASE}/drafts/d1").mock(
        return_value=httpx.Response(200, json={
            "id": "d1",
            "message": {"id": "m1"},
        }),
    )
    _ok(await server.call_tool(
        "gmail_get_draft", {"draft_id": "d1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_create_draft(server):
    respx.post(f"{BASE}/drafts").mock(
        return_value=httpx.Response(200, json={
            "id": "d2",
            "message": {"id": "m2"},
        }),
    )
    _ok(await server.call_tool("gmail_create_draft", {
        "to": "bob@test.com",
        "subject": "Draft",
        "body": "WIP",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_update_draft(server):
    respx.put(f"{BASE}/drafts/d1").mock(
        return_value=httpx.Response(200, json={
            "id": "d1",
            "message": {"id": "m1"},
        }),
    )
    _ok(await server.call_tool("gmail_update_draft", {
        "draft_id": "d1",
        "to": "bob@test.com",
        "subject": "Updated draft",
        "body": "New body",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_delete_draft(server):
    respx.delete(f"{BASE}/drafts/d1").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gmail_delete_draft", {"draft_id": "d1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_send_draft(server):
    respx.post(f"{BASE}/drafts/send").mock(
        return_value=httpx.Response(200, json={
            "id": "m5", "threadId": "t3",
        }),
    )
    _ok(await server.call_tool(
        "gmail_send_draft", {"draft_id": "d1"},
    ))


# ================================================================
# TIER 5: HISTORY (1 tool)
# ================================================================

@pytest.mark.asyncio
@respx.mock
async def test_list_history(server):
    respx.get(f"{BASE}/history").mock(
        return_value=httpx.Response(200, json={
            "history": [
                {"id": "12346", "messages": [{"id": "m1"}]},
            ],
            "historyId": "12347",
        }),
    )
    r = _r(await server.call_tool("gmail_list_history", {
        "start_history_id": "12345",
    }))
    assert r["count"] == 1
    assert r["history_id"] == "12347"


# ================================================================
# TIER 6: SETTINGS & PROFILE (11 tools)
# ================================================================

@pytest.mark.asyncio
@respx.mock
async def test_get_vacation_settings(server):
    respx.get(f"{BASE}/settings/vacation").mock(
        return_value=httpx.Response(200, json={
            "enableAutoReply": False,
        }),
    )
    _ok(await server.call_tool(
        "gmail_get_vacation_settings", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_vacation_settings(server):
    respx.put(f"{BASE}/settings/vacation").mock(
        return_value=httpx.Response(200, json={
            "enableAutoReply": True,
        }),
    )
    _ok(await server.call_tool(
        "gmail_update_vacation_settings", {
            "enable_auto_reply": True,
            "response_subject": "OOO",
            "response_body_plain_text": "I am away.",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_auto_forwarding(server):
    respx.get(f"{BASE}/settings/autoForwarding").mock(
        return_value=httpx.Response(200, json={
            "enabled": False,
        }),
    )
    _ok(await server.call_tool(
        "gmail_get_auto_forwarding", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_auto_forwarding(server):
    respx.put(f"{BASE}/settings/autoForwarding").mock(
        return_value=httpx.Response(200, json={
            "enabled": True,
        }),
    )
    _ok(await server.call_tool(
        "gmail_update_auto_forwarding", {
            "enabled": True,
            "email_address": "fwd@test.com",
            "disposition": "archive",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_imap_settings(server):
    respx.get(f"{BASE}/settings/imap").mock(
        return_value=httpx.Response(200, json={
            "enabled": True,
        }),
    )
    _ok(await server.call_tool(
        "gmail_get_imap_settings", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_imap_settings(server):
    respx.put(f"{BASE}/settings/imap").mock(
        return_value=httpx.Response(200, json={
            "enabled": True,
        }),
    )
    _ok(await server.call_tool(
        "gmail_update_imap_settings", {
            "enabled": True,
            "auto_expunge": True,
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_pop_settings(server):
    respx.get(f"{BASE}/settings/pop").mock(
        return_value=httpx.Response(200, json={
            "accessWindow": "disabled",
        }),
    )
    _ok(await server.call_tool(
        "gmail_get_pop_settings", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_pop_settings(server):
    respx.put(f"{BASE}/settings/pop").mock(
        return_value=httpx.Response(200, json={
            "accessWindow": "allMail",
        }),
    )
    _ok(await server.call_tool(
        "gmail_update_pop_settings", {
            "access_window": "allMail",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_language_settings(server):
    respx.get(f"{BASE}/settings/language").mock(
        return_value=httpx.Response(200, json={
            "displayLanguage": "en",
        }),
    )
    _ok(await server.call_tool(
        "gmail_get_language_settings", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_language_settings(server):
    respx.put(f"{BASE}/settings/language").mock(
        return_value=httpx.Response(200, json={
            "displayLanguage": "fr",
        }),
    )
    _ok(await server.call_tool(
        "gmail_update_language_settings", {
            "display_language": "fr",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_profile(server):
    respx.get(f"{BASE}/profile").mock(
        return_value=httpx.Response(200, json={
            "emailAddress": "user@test.com",
            "messagesTotal": 42,
            "threadsTotal": 10,
            "historyId": "12345",
        }),
    )
    _ok(await server.call_tool("gmail_get_profile", {}))


# ================================================================
# TIER 7: SEND-AS ALIASES (7 tools)
# ================================================================

@pytest.mark.asyncio
@respx.mock
async def test_list_send_as(server):
    respx.get(f"{BASE}/settings/sendAs").mock(
        return_value=httpx.Response(200, json={
            "sendAs": [
                {"sendAsEmail": "user@test.com"},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gmail_list_send_as", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_send_as(server):
    respx.get(
        f"{BASE}/settings/sendAs/alias@test.com",
    ).mock(
        return_value=httpx.Response(200, json={
            "sendAsEmail": "alias@test.com",
        }),
    )
    _ok(await server.call_tool("gmail_get_send_as", {
        "send_as_email": "alias@test.com",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_create_send_as(server):
    route = respx.post(f"{BASE}/settings/sendAs").mock(
        return_value=httpx.Response(200, json={
            "sendAsEmail": "alias@test.com",
        }),
    )
    _ok(await server.call_tool("gmail_create_send_as", {
        "send_as_email": "alias@test.com",
        "display_name": "My Alias",
    }))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["sendAsEmail"] == "alias@test.com"
    assert body["displayName"] == "My Alias"


@pytest.mark.asyncio
@respx.mock
async def test_create_send_as_with_smtp(server):
    respx.post(f"{BASE}/settings/sendAs").mock(
        return_value=httpx.Response(200, json={
            "sendAsEmail": "ext@other.com",
        }),
    )
    _ok(await server.call_tool("gmail_create_send_as", {
        "send_as_email": "ext@other.com",
        "smtp_host": "smtp.other.com",
        "smtp_port": 587,
        "smtp_username": "ext@other.com",
        "smtp_password": "secret",
        "smtp_security_mode": "starttls",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_update_send_as(server):
    respx.put(
        f"{BASE}/settings/sendAs/alias@test.com",
    ).mock(
        return_value=httpx.Response(200, json={
            "sendAsEmail": "alias@test.com",
        }),
    )
    _ok(await server.call_tool("gmail_update_send_as", {
        "send_as_email": "alias@test.com",
        "display_name": "Updated Alias",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_patch_send_as(server):
    respx.patch(
        f"{BASE}/settings/sendAs/alias@test.com",
    ).mock(
        return_value=httpx.Response(200, json={
            "sendAsEmail": "alias@test.com",
        }),
    )
    _ok(await server.call_tool("gmail_patch_send_as", {
        "send_as_email": "alias@test.com",
        "display_name": "Patched",
    }))


@pytest.mark.asyncio
async def test_patch_send_as_no_fields(server):
    with pytest.raises(Exception, match="At least one field"):
        await server.call_tool("gmail_patch_send_as", {
            "send_as_email": "alias@test.com",
        })


@pytest.mark.asyncio
@respx.mock
async def test_delete_send_as(server):
    respx.delete(
        f"{BASE}/settings/sendAs/alias@test.com",
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool("gmail_delete_send_as", {
        "send_as_email": "alias@test.com",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_verify_send_as(server):
    respx.post(
        f"{BASE}/settings/sendAs/alias@test.com/verify",
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool("gmail_verify_send_as", {
        "send_as_email": "alias@test.com",
    }))


# ================================================================
# TIER 8: FILTERS (4 tools)
# ================================================================

@pytest.mark.asyncio
@respx.mock
async def test_list_filters(server):
    respx.get(f"{BASE}/settings/filters").mock(
        return_value=httpx.Response(200, json={
            "filter": [{"id": "f1"}],
        }),
    )
    r = _r(await server.call_tool(
        "gmail_list_filters", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_filter(server):
    respx.get(f"{BASE}/settings/filters/f1").mock(
        return_value=httpx.Response(200, json={
            "id": "f1",
            "criteria": {"from": "news@test.com"},
        }),
    )
    _ok(await server.call_tool(
        "gmail_get_filter", {"filter_id": "f1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_create_filter(server):
    route = respx.post(f"{BASE}/settings/filters").mock(
        return_value=httpx.Response(200, json={
            "id": "f2",
        }),
    )
    _ok(await server.call_tool("gmail_create_filter", {
        "criteria_from": "news@test.com",
        "action_add_label_ids": ["Label_1"],
    }))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "criteria" in body
    assert body["criteria"]["from"] == "news@test.com"
    assert "action" in body
    assert body["action"]["addLabelIds"] == ["Label_1"]


@pytest.mark.asyncio
@respx.mock
async def test_delete_filter(server):
    respx.delete(f"{BASE}/settings/filters/f1").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gmail_delete_filter", {"filter_id": "f1"},
    ))


# ================================================================
# TIER 9: FORWARDING ADDRESSES (4 tools)
# ================================================================

@pytest.mark.asyncio
@respx.mock
async def test_list_forwarding_addresses(server):
    respx.get(
        f"{BASE}/settings/forwardingAddresses",
    ).mock(
        return_value=httpx.Response(200, json={
            "forwardingAddresses": [
                {"forwardingEmail": "fwd@test.com"},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gmail_list_forwarding_addresses", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_forwarding_address(server):
    respx.get(
        f"{BASE}/settings/forwardingAddresses"
        "/fwd@test.com",
    ).mock(
        return_value=httpx.Response(200, json={
            "forwardingEmail": "fwd@test.com",
            "verificationStatus": "accepted",
        }),
    )
    _ok(await server.call_tool(
        "gmail_get_forwarding_address", {
            "forwarding_email": "fwd@test.com",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_create_forwarding_address(server):
    route = respx.post(
        f"{BASE}/settings/forwardingAddresses",
    ).mock(
        return_value=httpx.Response(200, json={
            "forwardingEmail": "new-fwd@test.com",
            "verificationStatus": "pending",
        }),
    )
    _ok(await server.call_tool(
        "gmail_create_forwarding_address", {
            "forwarding_email": "new-fwd@test.com",
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["forwardingEmail"] == "new-fwd@test.com"


@pytest.mark.asyncio
@respx.mock
async def test_delete_forwarding_address(server):
    respx.delete(
        f"{BASE}/settings/forwardingAddresses"
        "/fwd@test.com",
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gmail_delete_forwarding_address", {
            "forwarding_email": "fwd@test.com",
        },
    ))


# ================================================================
# TIER 10: DELEGATES (4 tools)
# ================================================================

@pytest.mark.asyncio
@respx.mock
async def test_list_delegates(server):
    respx.get(f"{BASE}/settings/delegates").mock(
        return_value=httpx.Response(200, json={
            "delegates": [
                {"delegateEmail": "del@test.com"},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gmail_list_delegates", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_delegate(server):
    respx.get(
        f"{BASE}/settings/delegates/del@test.com",
    ).mock(
        return_value=httpx.Response(200, json={
            "delegateEmail": "del@test.com",
            "verificationStatus": "accepted",
        }),
    )
    _ok(await server.call_tool("gmail_get_delegate", {
        "delegate_email": "del@test.com",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_create_delegate(server):
    route = respx.post(f"{BASE}/settings/delegates").mock(
        return_value=httpx.Response(200, json={
            "delegateEmail": "new-del@test.com",
            "verificationStatus": "pending",
        }),
    )
    _ok(await server.call_tool("gmail_create_delegate", {
        "delegate_email": "new-del@test.com",
    }))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["delegateEmail"] == "new-del@test.com"


@pytest.mark.asyncio
@respx.mock
async def test_delete_delegate(server):
    respx.delete(
        f"{BASE}/settings/delegates/del@test.com",
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool("gmail_delete_delegate", {
        "delegate_email": "del@test.com",
    }))


# ================================================================
# TIER 11: ATTACHMENTS (1 tool)
# ================================================================

@pytest.mark.asyncio
@respx.mock
async def test_get_attachment(server):
    respx.get(
        f"{BASE}/messages/m1/attachments/att1",
    ).mock(
        return_value=httpx.Response(200, json={
            "attachmentId": "att1",
            "size": 1024,
            "data": "ZmlsZSBkYXRh",
        }),
    )
    _ok(await server.call_tool("gmail_get_attachment", {
        "message_id": "m1",
        "attachment_id": "att1",
    }))
