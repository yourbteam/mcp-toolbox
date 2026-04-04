"""Tests for Google Drive tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.gdrive_tool import register_tools

BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"


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
        "mcp_toolbox.tools.gdrive_tool"
        ".GOOGLE_SERVICE_ACCOUNT_JSON",
        "/fake/key.json",
    ), patch(
        "mcp_toolbox.tools.gdrive_tool"
        ".GDRIVE_DEFAULT_FOLDER_ID",
        None,
    ), patch(
        "mcp_toolbox.tools.gdrive_tool._credentials",
        mock_creds,
    ), patch(
        "mcp_toolbox.tools.gdrive_tool._client",
        None,
    ):
        register_tools(mcp)
        yield mcp


# --- Auth/Error ---


@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with patch(
        "mcp_toolbox.tools.gdrive_tool"
        ".GOOGLE_SERVICE_ACCOUNT_JSON",
        None,
    ), patch(
        "mcp_toolbox.tools.gdrive_tool"
        ".GDRIVE_DEFAULT_FOLDER_ID",
        None,
    ), patch(
        "mcp_toolbox.tools.gdrive_tool._credentials",
        None,
    ), patch(
        "mcp_toolbox.tools.gdrive_tool._client",
        None,
    ):
        register_tools(mcp)
        with pytest.raises(
            Exception,
            match="GOOGLE_SERVICE_ACCOUNT_JSON",
        ):
            await mcp.call_tool(
                "gdrive_list_files", {},
            )


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit(server):
    respx.get(f"{BASE}/files").mock(
        return_value=httpx.Response(429),
    )
    with pytest.raises(
        Exception, match="rate limit"
    ):
        await server.call_tool(
            "gdrive_list_files", {},
        )


@pytest.mark.asyncio
@respx.mock
async def test_api_error(server):
    respx.get(f"{BASE}/files").mock(
        return_value=httpx.Response(403, json={
            "error": {"message": "forbidden"},
        }),
    )
    with pytest.raises(
        Exception, match="forbidden"
    ):
        await server.call_tool(
            "gdrive_list_files", {},
        )


# --- Tier 1: File Operations (10 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_files(server):
    respx.get(f"{BASE}/files").mock(
        return_value=httpx.Response(200, json={
            "files": [
                {"id": "f1", "name": "doc.txt"},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_list_files", {},
    ))
    assert r["files"][0]["id"] == "f1"


@pytest.mark.asyncio
@respx.mock
async def test_list_files_with_query(server):
    respx.get(f"{BASE}/files").mock(
        return_value=httpx.Response(200, json={
            "files": [],
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_list_files", {
            "q": "name contains 'report'",
            "folder_id": "folder1",
            "page_size": 10,
        },
    ))
    assert "files" in r


@pytest.mark.asyncio
@respx.mock
async def test_get_file(server):
    respx.get(f"{BASE}/files/f1").mock(
        return_value=httpx.Response(200, json={
            "id": "f1", "name": "doc.txt",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_get_file", {"file_id": "f1"},
    ))
    assert r["id"] == "f1"


@pytest.mark.asyncio
@respx.mock
async def test_create_file_folder(server):
    respx.post(f"{BASE}/files").mock(
        return_value=httpx.Response(200, json={
            "id": "f2", "name": "New Folder",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_create_file", {"name": "New Folder"},
    ))
    assert r["status"] == "success"
    assert r["file"]["id"] == "f2"


@pytest.mark.asyncio
@respx.mock
async def test_create_file_with_content(server):
    respx.post(url__startswith=UPLOAD_BASE).mock(
        return_value=httpx.Response(200, json={
            "id": "f3", "name": "hello.txt",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_create_file", {
            "name": "hello.txt",
            "content": "Hello, world!",
            "mime_type": "text/plain",
        },
    ))
    assert r["file"]["id"] == "f3"


@pytest.mark.asyncio
@respx.mock
async def test_copy_file(server):
    respx.post(f"{BASE}/files/f1/copy").mock(
        return_value=httpx.Response(200, json={
            "id": "f1_copy", "name": "doc (copy)",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_copy_file", {
            "file_id": "f1",
            "name": "doc (copy)",
        },
    ))
    assert r["file"]["id"] == "f1_copy"


@pytest.mark.asyncio
@respx.mock
async def test_update_file_metadata(server):
    respx.patch(f"{BASE}/files/f1").mock(
        return_value=httpx.Response(200, json={
            "id": "f1", "name": "renamed.txt",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_update_file", {
            "file_id": "f1",
            "name": "renamed.txt",
            "starred": True,
        },
    ))
    assert r["file"]["name"] == "renamed.txt"


@pytest.mark.asyncio
@respx.mock
async def test_update_file_with_content(server):
    respx.patch(url__startswith=UPLOAD_BASE).mock(
        return_value=httpx.Response(200, json={
            "id": "f1", "name": "updated.txt",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_update_file", {
            "file_id": "f1",
            "content": "Updated content",
        },
    ))
    assert r["file"]["id"] == "f1"


@pytest.mark.asyncio
@respx.mock
async def test_delete_file(server):
    respx.delete(f"{BASE}/files/f1").mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "gdrive_delete_file", {"file_id": "f1"},
    ))
    assert r["status_code"] == 204


@pytest.mark.asyncio
@respx.mock
async def test_export_file_text(server):
    respx.get(f"{BASE}/files/f1/export").mock(
        return_value=httpx.Response(
            200,
            text="Exported content here",
            headers={
                "content-type": "text/plain",
            },
        ),
    )
    r = _r(await server.call_tool(
        "gdrive_export_file", {
            "file_id": "f1",
            "mime_type": "text/plain",
        },
    ))
    assert r["content"] == "Exported content here"


@pytest.mark.asyncio
@respx.mock
async def test_export_file_binary(server):
    respx.get(f"{BASE}/files/f1/export").mock(
        return_value=httpx.Response(
            200,
            content=b"\x00\x01\x02",
            headers={
                "content-type": "application/pdf",
            },
        ),
    )
    r = _r(await server.call_tool(
        "gdrive_export_file", {
            "file_id": "f1",
            "mime_type": "application/pdf",
        },
    ))
    assert "Binary export" in r["message"]


@pytest.mark.asyncio
@respx.mock
async def test_empty_trash(server):
    respx.delete(f"{BASE}/files/emptyTrash").mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "gdrive_empty_trash", {},
    ))
    assert r["status_code"] == 204


@pytest.mark.asyncio
@respx.mock
async def test_download_file_text(server):
    respx.get(f"{BASE}/files/f1").mock(
        return_value=httpx.Response(
            200,
            text="file content here",
            headers={
                "content-type": "text/plain",
            },
        ),
    )
    r = _r(await server.call_tool(
        "gdrive_download_file", {"file_id": "f1"},
    ))
    assert r["content"] == "file content here"


@pytest.mark.asyncio
@respx.mock
async def test_download_file_binary(server):
    respx.get(f"{BASE}/files/f1").mock(
        return_value=httpx.Response(
            200,
            content=b"\x89PNG\r\n",
            headers={
                "content-type": "image/png",
            },
        ),
    )
    r = _r(await server.call_tool(
        "gdrive_download_file", {"file_id": "f1"},
    ))
    assert "Binary file" in r["message"]


@pytest.mark.asyncio
@respx.mock
async def test_stop_channel(server):
    respx.post(f"{BASE}/channels/stop").mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "gdrive_stop_channel", {
            "channel_id": "ch1",
            "resource_id": "res1",
        },
    ))
    assert r["status_code"] == 204


# --- Tier 2: Permissions (5 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_permissions(server):
    respx.get(
        f"{BASE}/files/f1/permissions",
    ).mock(
        return_value=httpx.Response(200, json={
            "permissions": [
                {
                    "id": "p1",
                    "role": "reader",
                    "type": "user",
                },
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_list_permissions",
        {"file_id": "f1"},
    ))
    assert r["permissions"][0]["id"] == "p1"


@pytest.mark.asyncio
@respx.mock
async def test_get_permission(server):
    respx.get(
        f"{BASE}/files/f1/permissions/p1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "p1",
            "role": "writer",
            "type": "user",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_get_permission", {
            "file_id": "f1",
            "permission_id": "p1",
        },
    ))
    assert r["role"] == "writer"


@pytest.mark.asyncio
@respx.mock
async def test_create_permission(server):
    respx.post(
        f"{BASE}/files/f1/permissions",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "p2",
            "role": "reader",
            "type": "user",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_create_permission", {
            "file_id": "f1",
            "role": "reader",
            "type": "user",
            "email_address": "a@test.com",
        },
    ))
    assert r["permission"]["id"] == "p2"


@pytest.mark.asyncio
@respx.mock
async def test_update_permission(server):
    respx.patch(
        f"{BASE}/files/f1/permissions/p1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "p1",
            "role": "writer",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_update_permission", {
            "file_id": "f1",
            "permission_id": "p1",
            "role": "writer",
        },
    ))
    assert r["permission"]["role"] == "writer"


@pytest.mark.asyncio
@respx.mock
async def test_delete_permission(server):
    respx.delete(
        f"{BASE}/files/f1/permissions/p1",
    ).mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "gdrive_delete_permission", {
            "file_id": "f1",
            "permission_id": "p1",
        },
    ))
    assert r["status_code"] == 204


# --- Tier 3: Comments (5 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_comments(server):
    respx.get(
        f"{BASE}/files/f1/comments",
    ).mock(
        return_value=httpx.Response(200, json={
            "comments": [
                {"id": "c1", "content": "Nice!"},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_list_comments",
        {"file_id": "f1"},
    ))
    assert r["comments"][0]["id"] == "c1"


@pytest.mark.asyncio
@respx.mock
async def test_get_comment(server):
    respx.get(
        f"{BASE}/files/f1/comments/c1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "c1", "content": "Nice!",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_get_comment", {
            "file_id": "f1",
            "comment_id": "c1",
        },
    ))
    assert r["id"] == "c1"


@pytest.mark.asyncio
@respx.mock
async def test_create_comment(server):
    respx.post(
        f"{BASE}/files/f1/comments",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "c2", "content": "Great work!",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_create_comment", {
            "file_id": "f1",
            "content": "Great work!",
        },
    ))
    assert r["comment"]["id"] == "c2"


@pytest.mark.asyncio
@respx.mock
async def test_update_comment(server):
    respx.patch(
        f"{BASE}/files/f1/comments/c1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "c1", "content": "Updated",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_update_comment", {
            "file_id": "f1",
            "comment_id": "c1",
            "content": "Updated",
        },
    ))
    assert r["comment"]["content"] == "Updated"


@pytest.mark.asyncio
@respx.mock
async def test_delete_comment(server):
    respx.delete(
        f"{BASE}/files/f1/comments/c1",
    ).mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "gdrive_delete_comment", {
            "file_id": "f1",
            "comment_id": "c1",
        },
    ))
    assert r["status_code"] == 204


# --- Tier 4: Replies (5 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_replies(server):
    respx.get(
        f"{BASE}/files/f1/comments/c1/replies",
    ).mock(
        return_value=httpx.Response(200, json={
            "replies": [
                {"id": "r1", "content": "Thanks!"},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_list_replies", {
            "file_id": "f1",
            "comment_id": "c1",
        },
    ))
    assert r["replies"][0]["id"] == "r1"


@pytest.mark.asyncio
@respx.mock
async def test_get_reply(server):
    respx.get(
        f"{BASE}/files/f1/comments/c1/replies/r1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "r1", "content": "Thanks!",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_get_reply", {
            "file_id": "f1",
            "comment_id": "c1",
            "reply_id": "r1",
        },
    ))
    assert r["id"] == "r1"


@pytest.mark.asyncio
@respx.mock
async def test_create_reply(server):
    respx.post(
        f"{BASE}/files/f1/comments/c1/replies",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "r2", "content": "You're welcome",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_create_reply", {
            "file_id": "f1",
            "comment_id": "c1",
            "content": "You're welcome",
        },
    ))
    assert r["reply"]["id"] == "r2"


@pytest.mark.asyncio
@respx.mock
async def test_create_reply_with_action(server):
    respx.post(
        f"{BASE}/files/f1/comments/c1/replies",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "r3",
            "content": "Done",
            "action": "resolve",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_create_reply", {
            "file_id": "f1",
            "comment_id": "c1",
            "content": "Done",
            "action": "resolve",
        },
    ))
    assert r["reply"]["action"] == "resolve"


@pytest.mark.asyncio
@respx.mock
async def test_update_reply(server):
    respx.patch(
        f"{BASE}/files/f1/comments/c1/replies/r1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "r1", "content": "Edited reply",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_update_reply", {
            "file_id": "f1",
            "comment_id": "c1",
            "reply_id": "r1",
            "content": "Edited reply",
        },
    ))
    assert r["reply"]["content"] == "Edited reply"


@pytest.mark.asyncio
@respx.mock
async def test_delete_reply(server):
    respx.delete(
        f"{BASE}/files/f1/comments/c1/replies/r1",
    ).mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "gdrive_delete_reply", {
            "file_id": "f1",
            "comment_id": "c1",
            "reply_id": "r1",
        },
    ))
    assert r["status_code"] == 204


# --- Tier 5: Revisions (4 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_revisions(server):
    respx.get(
        f"{BASE}/files/f1/revisions",
    ).mock(
        return_value=httpx.Response(200, json={
            "revisions": [
                {"id": "rev1", "size": "1024"},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_list_revisions",
        {"file_id": "f1"},
    ))
    assert r["revisions"][0]["id"] == "rev1"


@pytest.mark.asyncio
@respx.mock
async def test_get_revision(server):
    respx.get(
        f"{BASE}/files/f1/revisions/rev1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "rev1",
            "mimeType": "text/plain",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_get_revision", {
            "file_id": "f1",
            "revision_id": "rev1",
        },
    ))
    assert r["id"] == "rev1"


@pytest.mark.asyncio
@respx.mock
async def test_update_revision(server):
    respx.patch(
        f"{BASE}/files/f1/revisions/rev1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "rev1", "keepForever": True,
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_update_revision", {
            "file_id": "f1",
            "revision_id": "rev1",
            "keep_forever": True,
        },
    ))
    assert r["revision"]["keepForever"] is True


@pytest.mark.asyncio
@respx.mock
async def test_delete_revision(server):
    respx.delete(
        f"{BASE}/files/f1/revisions/rev1",
    ).mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "gdrive_delete_revision", {
            "file_id": "f1",
            "revision_id": "rev1",
        },
    ))
    assert r["status_code"] == 204


# --- Tier 6: Changes (3 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_get_start_page_token(server):
    respx.get(
        f"{BASE}/changes/startPageToken",
    ).mock(
        return_value=httpx.Response(200, json={
            "startPageToken": "42",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_get_start_page_token", {},
    ))
    assert r["startPageToken"] == "42"


@pytest.mark.asyncio
@respx.mock
async def test_list_changes(server):
    respx.get(f"{BASE}/changes").mock(
        return_value=httpx.Response(200, json={
            "changes": [
                {"fileId": "f1", "removed": False},
            ],
            "newStartPageToken": "43",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_list_changes",
        {"page_token": "42"},
    ))
    assert r["changes"][0]["fileId"] == "f1"


@pytest.mark.asyncio
@respx.mock
async def test_watch_changes(server):
    respx.post(f"{BASE}/changes/watch").mock(
        return_value=httpx.Response(200, json={
            "kind": "api#channel",
            "id": "ch1",
            "resourceId": "res1",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_watch_changes", {
            "page_token": "42",
            "channel_id": "ch1",
            "webhook_url": "https://example.com/hook",
        },
    ))
    assert r["channel"]["id"] == "ch1"


# --- Tier 7: Shared Drives (5 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_drives(server):
    respx.get(f"{BASE}/drives").mock(
        return_value=httpx.Response(200, json={
            "drives": [
                {"id": "d1", "name": "Team Drive"},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_list_drives", {},
    ))
    assert r["drives"][0]["id"] == "d1"


@pytest.mark.asyncio
@respx.mock
async def test_get_drive(server):
    respx.get(f"{BASE}/drives/d1").mock(
        return_value=httpx.Response(200, json={
            "id": "d1", "name": "Team Drive",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_get_drive", {"drive_id": "d1"},
    ))
    assert r["name"] == "Team Drive"


@pytest.mark.asyncio
@respx.mock
async def test_create_drive(server):
    respx.post(f"{BASE}/drives").mock(
        return_value=httpx.Response(200, json={
            "id": "d2", "name": "New Drive",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_create_drive", {
            "name": "New Drive",
            "request_id": "uuid-123",
        },
    ))
    assert r["drive"]["id"] == "d2"


@pytest.mark.asyncio
@respx.mock
async def test_update_drive(server):
    respx.patch(f"{BASE}/drives/d1").mock(
        return_value=httpx.Response(200, json={
            "id": "d1", "name": "Renamed Drive",
        }),
    )
    r = _r(await server.call_tool(
        "gdrive_update_drive", {
            "drive_id": "d1",
            "name": "Renamed Drive",
        },
    ))
    assert r["drive"]["name"] == "Renamed Drive"


@pytest.mark.asyncio
@respx.mock
async def test_delete_drive(server):
    respx.delete(f"{BASE}/drives/d1").mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "gdrive_delete_drive", {"drive_id": "d1"},
    ))
    assert r["status_code"] == 204
