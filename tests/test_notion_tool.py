"""Tests for Notion integration — pages, databases, blocks, users, search, comments."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.notion_tool import register_tools

BASE = "https://api.notion.com/v1"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    with patch(
        "mcp_toolbox.tools.notion_tool.NOTION_API_TOKEN",
        "ntn_test",
    ), patch(
        "mcp_toolbox.tools.notion_tool._client", None
    ):
        register_tools(mcp)
        yield mcp


# ================================================================
# Auth / error tests
# ================================================================


@pytest.mark.asyncio
async def test_missing_token():
    mcp = FastMCP("test")
    with patch(
        "mcp_toolbox.tools.notion_tool.NOTION_API_TOKEN",
        None,
    ), patch(
        "mcp_toolbox.tools.notion_tool._client", None
    ):
        register_tools(mcp)
        with pytest.raises(
            Exception, match="NOTION_API_TOKEN"
        ):
            await mcp.call_tool(
                "notion_list_users", {}
            )


@pytest.mark.asyncio
@respx.mock
async def test_api_error_429(server):
    respx.get(f"{BASE}/users").mock(
        return_value=httpx.Response(
            429, headers={"Retry-After": "2"}
        )
    )
    with pytest.raises(
        Exception, match="rate limit"
    ):
        await server.call_tool(
            "notion_list_users", {}
        )


@pytest.mark.asyncio
@respx.mock
async def test_api_error_400(server):
    respx.get(f"{BASE}/pages/bad-id").mock(
        return_value=httpx.Response(
            400,
            json={"message": "Invalid page ID"},
        )
    )
    with pytest.raises(
        Exception, match="Invalid page ID"
    ):
        await server.call_tool(
            "notion_get_page", {"page_id": "bad-id"}
        )


# ================================================================
# Tier 1: Pages (5 tools)
# ================================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_page_under_page(server):
    route = respx.post(f"{BASE}/pages").mock(
        return_value=httpx.Response(
            200, json={"id": "page-1", "object": "page"}
        )
    )
    r = _r(await server.call_tool(
        "notion_create_page",
        {
            "parent_type": "page_id",
            "parent_id": "parent-1",
            "title": "My Page",
        },
    ))
    assert r["status"] == "success"
    assert r["data"]["id"] == "page-1"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["parent"] == {"page_id": "parent-1"}
    assert "title" in body["properties"]


@pytest.mark.asyncio
@respx.mock
async def test_create_page_under_database(server):
    route = respx.post(f"{BASE}/pages").mock(
        return_value=httpx.Response(
            200, json={"id": "page-2", "object": "page"}
        )
    )
    r = _r(await server.call_tool(
        "notion_create_page",
        {
            "parent_type": "database_id",
            "parent_id": "db-1",
            "title": "DB Entry",
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["parent"] == {"database_id": "db-1"}
    assert "Name" in body["properties"]


@pytest.mark.asyncio
@respx.mock
async def test_get_page(server):
    respx.get(f"{BASE}/pages/page-1").mock(
        return_value=httpx.Response(
            200, json={"id": "page-1", "object": "page"}
        )
    )
    r = _r(await server.call_tool(
        "notion_get_page", {"page_id": "page-1"}
    ))
    assert r["status"] == "success"
    assert r["data"]["id"] == "page-1"


@pytest.mark.asyncio
@respx.mock
async def test_get_page_with_filter(server):
    respx.get(f"{BASE}/pages/page-1").mock(
        return_value=httpx.Response(
            200, json={"id": "page-1"}
        )
    )
    r = _r(await server.call_tool(
        "notion_get_page",
        {
            "page_id": "page-1",
            "filter_properties": ["title"],
        },
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_page(server):
    route = respx.patch(f"{BASE}/pages/page-1").mock(
        return_value=httpx.Response(
            200, json={"id": "page-1", "archived": False}
        )
    )
    r = _r(await server.call_tool(
        "notion_update_page",
        {
            "page_id": "page-1",
            "properties": {"Name": {"title": []}},
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["properties"] == {"Name": {"title": []}}


@pytest.mark.asyncio
async def test_update_page_no_fields(server):
    with pytest.raises(
        Exception, match="At least one field"
    ):
        await server.call_tool(
            "notion_update_page",
            {"page_id": "page-1"},
        )


@pytest.mark.asyncio
@respx.mock
async def test_archive_page(server):
    route = respx.patch(f"{BASE}/pages/page-1").mock(
        return_value=httpx.Response(
            200,
            json={"id": "page-1", "archived": True},
        )
    )
    r = _r(await server.call_tool(
        "notion_archive_page",
        {"page_id": "page-1"},
    ))
    assert r["status"] == "success"
    assert r["data"]["archived"] is True
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body == {"archived": True}


@pytest.mark.asyncio
@respx.mock
async def test_get_page_property(server):
    respx.get(
        f"{BASE}/pages/page-1/properties/prop-1"
    ).mock(
        return_value=httpx.Response(
            200, json={"object": "list", "results": []}
        )
    )
    r = _r(await server.call_tool(
        "notion_get_page_property",
        {
            "page_id": "page-1",
            "property_id": "prop-1",
        },
    ))
    assert r["status"] == "success"


# ================================================================
# Tier 2: Databases (5 tools)
# ================================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_database(server):
    route = respx.post(f"{BASE}/databases").mock(
        return_value=httpx.Response(
            200,
            json={"id": "db-1", "object": "database"},
        )
    )
    r = _r(await server.call_tool(
        "notion_create_database",
        {
            "parent_page_id": "page-1",
            "title": "Tasks",
            "properties": {
                "Name": {"title": {}},
                "Status": {
                    "select": {
                        "options": [
                            {"name": "Done"}
                        ]
                    }
                },
            },
        },
    ))
    assert r["status"] == "success"
    assert r["data"]["id"] == "db-1"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["parent"] == {
        "type": "page_id", "page_id": "page-1",
    }
    assert "title" in body
    assert body["properties"]["Name"] == {"title": {}}
    assert body["properties"]["Status"]["select"]["options"][0]["name"] == "Done"


@pytest.mark.asyncio
@respx.mock
async def test_get_database(server):
    respx.get(f"{BASE}/databases/db-1").mock(
        return_value=httpx.Response(
            200,
            json={"id": "db-1", "object": "database"},
        )
    )
    r = _r(await server.call_tool(
        "notion_get_database",
        {"database_id": "db-1"},
    ))
    assert r["status"] == "success"
    assert r["data"]["id"] == "db-1"


@pytest.mark.asyncio
@respx.mock
async def test_update_database(server):
    route = respx.patch(f"{BASE}/databases/db-1").mock(
        return_value=httpx.Response(
            200, json={"id": "db-1", "title": []}
        )
    )
    r = _r(await server.call_tool(
        "notion_update_database",
        {
            "database_id": "db-1",
            "title": "Updated DB",
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "title" in body


@pytest.mark.asyncio
async def test_update_database_no_fields(server):
    with pytest.raises(
        Exception, match="At least one field"
    ):
        await server.call_tool(
            "notion_update_database",
            {"database_id": "db-1"},
        )


@pytest.mark.asyncio
@respx.mock
async def test_query_database(server):
    route = respx.post(f"{BASE}/databases/db-1/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"id": "p1"}, {"id": "p2"}],
                "has_more": False,
                "next_cursor": None,
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_query_database",
        {"database_id": "db-1"},
    ))
    assert r["status"] == "success"
    assert r["count"] == 2
    assert r["has_more"] is False
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body == {}


@pytest.mark.asyncio
@respx.mock
async def test_query_database_with_filter(server):
    route = respx.post(f"{BASE}/databases/db-1/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"id": "p1"}],
                "has_more": True,
                "next_cursor": "cursor-abc",
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_query_database",
        {
            "database_id": "db-1",
            "filter": {
                "property": "Status",
                "select": {"equals": "Done"},
            },
            "page_size": 1,
        },
    ))
    assert r["count"] == 1
    assert r["has_more"] is True
    assert r["next_cursor"] == "cursor-abc"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["filter"]["property"] == "Status"
    assert body["filter"]["select"] == {"equals": "Done"}
    assert body["page_size"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_archive_database(server):
    route = respx.patch(f"{BASE}/databases/db-1").mock(
        return_value=httpx.Response(
            200,
            json={"id": "db-1", "archived": True},
        )
    )
    r = _r(await server.call_tool(
        "notion_archive_database",
        {"database_id": "db-1"},
    ))
    assert r["status"] == "success"
    assert r["data"]["archived"] is True
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body == {"archived": True}


# ================================================================
# Tier 3: Blocks (5 tools)
# ================================================================


@pytest.mark.asyncio
@respx.mock
async def test_get_block(server):
    respx.get(f"{BASE}/blocks/blk-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "blk-1",
                "type": "paragraph",
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_get_block", {"block_id": "blk-1"}
    ))
    assert r["status"] == "success"
    assert r["data"]["type"] == "paragraph"


@pytest.mark.asyncio
@respx.mock
async def test_get_block_children(server):
    respx.get(f"{BASE}/blocks/blk-1/children").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "c1", "type": "paragraph"}
                ],
                "has_more": False,
                "next_cursor": None,
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_get_block_children",
        {"block_id": "blk-1"},
    ))
    assert r["status"] == "success"
    assert r["count"] == 1
    assert r["has_more"] is False


@pytest.mark.asyncio
@respx.mock
async def test_get_block_children_paginated(server):
    respx.get(f"{BASE}/blocks/blk-1/children").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"id": "c1"}],
                "has_more": True,
                "next_cursor": "cur-1",
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_get_block_children",
        {
            "block_id": "blk-1",
            "page_size": 1,
        },
    ))
    assert r["has_more"] is True
    assert r["next_cursor"] == "cur-1"


@pytest.mark.asyncio
@respx.mock
async def test_append_block_children(server):
    route = respx.patch(f"{BASE}/blocks/blk-1/children").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "new-1", "type": "paragraph"}
                ]
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_append_block_children",
        {
            "block_id": "blk-1",
            "children": [
                {
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "Hi"
                                },
                            }
                        ]
                    },
                }
            ],
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert len(body["children"]) == 1
    assert body["children"][0]["type"] == "paragraph"
    rich = body["children"][0]["paragraph"]["rich_text"]
    assert rich[0]["text"]["content"] == "Hi"


@pytest.mark.asyncio
@respx.mock
async def test_update_block(server):
    route = respx.patch(f"{BASE}/blocks/blk-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "blk-1",
                "type": "paragraph",
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_update_block",
        {
            "block_id": "blk-1",
            "block_type": "paragraph",
            "content": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": "Updated"},
                    }
                ]
            },
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "paragraph" in body
    assert body["paragraph"]["rich_text"][0]["text"]["content"] == "Updated"


@pytest.mark.asyncio
@respx.mock
async def test_delete_block(server):
    respx.delete(f"{BASE}/blocks/blk-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "blk-1",
                "archived": True,
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_delete_block",
        {"block_id": "blk-1"},
    ))
    assert r["status"] == "success"
    assert r["data"]["archived"] is True


# ================================================================
# Tier 4: Users (3 tools)
# ================================================================


@pytest.mark.asyncio
@respx.mock
async def test_list_users(server):
    respx.get(f"{BASE}/users").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "u1", "name": "Alice"},
                    {"id": "u2", "name": "Bob"},
                ],
                "has_more": False,
                "next_cursor": None,
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_list_users", {}
    ))
    assert r["status"] == "success"
    assert r["count"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_list_users_paginated(server):
    respx.get(f"{BASE}/users").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"id": "u1"}],
                "has_more": True,
                "next_cursor": "cur-u",
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_list_users",
        {"page_size": 1},
    ))
    assert r["has_more"] is True
    assert r["next_cursor"] == "cur-u"


@pytest.mark.asyncio
@respx.mock
async def test_get_user(server):
    respx.get(f"{BASE}/users/u1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "u1",
                "name": "Alice",
                "type": "person",
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_get_user", {"user_id": "u1"}
    ))
    assert r["status"] == "success"
    assert r["data"]["name"] == "Alice"


@pytest.mark.asyncio
@respx.mock
async def test_get_bot_user(server):
    respx.get(f"{BASE}/users/me").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "bot-1",
                "type": "bot",
                "name": "My Integration",
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_get_bot_user", {}
    ))
    assert r["status"] == "success"
    assert r["data"]["type"] == "bot"


# ================================================================
# Tier 5: Search (1 tool)
# ================================================================


@pytest.mark.asyncio
@respx.mock
async def test_search(server):
    route = respx.post(f"{BASE}/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "p1", "object": "page"}
                ],
                "has_more": False,
                "next_cursor": None,
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_search",
        {"query": "meeting notes"},
    ))
    assert r["status"] == "success"
    assert r["count"] == 1
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["query"] == "meeting notes"


@pytest.mark.asyncio
@respx.mock
async def test_search_with_filter(server):
    route = respx.post(f"{BASE}/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [],
                "has_more": False,
                "next_cursor": None,
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_search",
        {
            "filter_object_type": "database",
            "sort_direction": "descending",
            "page_size": 10,
        },
    ))
    assert r["count"] == 0
    assert r["has_more"] is False
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["filter"] == {
        "value": "database", "property": "object",
    }
    assert body["sort"] == {
        "direction": "descending",
        "timestamp": "last_edited_time",
    }
    assert body["page_size"] == 10


# ================================================================
# Tier 6: Comments (2 tools)
# ================================================================


@pytest.mark.asyncio
@respx.mock
async def test_list_comments(server):
    respx.get(f"{BASE}/comments").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": "cmt-1", "rich_text": []}
                ],
                "has_more": False,
                "next_cursor": None,
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_list_comments",
        {"block_id": "page-1"},
    ))
    assert r["status"] == "success"
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_create_comment_on_page(server):
    route = respx.post(f"{BASE}/comments").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "cmt-2",
                "object": "comment",
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_create_comment",
        {
            "content": "Looks good!",
            "parent_page_id": "page-1",
        },
    ))
    assert r["status"] == "success"
    assert r["data"]["id"] == "cmt-2"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["parent"] == {"page_id": "page-1"}
    assert "rich_text" in body


@pytest.mark.asyncio
@respx.mock
async def test_create_comment_reply(server):
    route = respx.post(f"{BASE}/comments").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "cmt-3",
                "object": "comment",
            },
        )
    )
    r = _r(await server.call_tool(
        "notion_create_comment",
        {
            "content": "Thanks!",
            "discussion_id": "disc-1",
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["discussion_id"] == "disc-1"
    assert "rich_text" in body


@pytest.mark.asyncio
async def test_create_comment_no_target(server):
    with pytest.raises(
        Exception,
        match="parent_page_id or discussion_id",
    ):
        await server.call_tool(
            "notion_create_comment",
            {"content": "Orphan comment"},
        )
