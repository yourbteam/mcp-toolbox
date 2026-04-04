"""Tests for Zendesk Support API v2 tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.zendesk_tool import register_tools

BASE = "https://test.zendesk.com/api/v2"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    with (
        patch(
            "mcp_toolbox.tools.zendesk_tool.ZENDESK_SUBDOMAIN",
            "test",
        ),
        patch(
            "mcp_toolbox.tools.zendesk_tool.ZENDESK_EMAIL",
            "a@b.com",
        ),
        patch(
            "mcp_toolbox.tools.zendesk_tool.ZENDESK_API_TOKEN",
            "tok",
        ),
        patch(
            "mcp_toolbox.tools.zendesk_tool._client",
            None,
        ),
    ):
        register_tools(mcp)
        yield mcp


# =========================================================
# AUTH / ERROR TESTS
# =========================================================


@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with (
        patch(
            "mcp_toolbox.tools.zendesk_tool.ZENDESK_SUBDOMAIN",
            None,
        ),
        patch(
            "mcp_toolbox.tools.zendesk_tool.ZENDESK_EMAIL",
            None,
        ),
        patch(
            "mcp_toolbox.tools.zendesk_tool.ZENDESK_API_TOKEN",
            None,
        ),
        patch(
            "mcp_toolbox.tools.zendesk_tool._client",
            None,
        ),
    ):
        register_tools(mcp)
        with pytest.raises(
            Exception, match="Zendesk credentials"
        ):
            await mcp.call_tool(
                "zendesk_list_tickets", {}
            )


@pytest.mark.asyncio
@respx.mock
async def test_api_error_429(server):
    respx.get(f"{BASE}/tickets.json").mock(
        return_value=httpx.Response(
            429, headers={"Retry-After": "5"},
        ),
    )
    with pytest.raises(Exception, match="rate limit"):
        await server.call_tool(
            "zendesk_list_tickets", {}
        )


@pytest.mark.asyncio
@respx.mock
async def test_api_error_400(server):
    respx.post(f"{BASE}/tickets.json").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": "InvalidRecord",
                "description": "Bad request",
            },
        ),
    )
    with pytest.raises(Exception, match="Bad request"):
        await server.call_tool(
            "zendesk_create_ticket",
            {"subject": "X", "description": "Y"},
        )


@pytest.mark.asyncio
@respx.mock
async def test_api_error_with_details(server):
    respx.post(f"{BASE}/tickets.json").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": "RecordInvalid",
                "description": "Validation failed",
                "details": {"base": [{"error": "blank"}]},
            },
        ),
    )
    with pytest.raises(
        Exception, match="Validation failed"
    ):
        await server.call_tool(
            "zendesk_create_ticket",
            {"subject": "X", "description": "Y"},
        )


# =========================================================
# TIER 1: TICKET MANAGEMENT (16 tools)
# =========================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_ticket(server):
    route = respx.post(f"{BASE}/tickets.json").mock(
        return_value=httpx.Response(
            201,
            json={"ticket": {"id": 1, "subject": "Bug"}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_ticket",
        {"subject": "Bug", "description": "It broke"},
    ))
    assert r["status"] == "success"
    assert r["data"]["id"] == 1
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "ticket" in body
    assert body["ticket"]["subject"] == "Bug"
    assert body["ticket"]["comment"]["body"] == "It broke"


@pytest.mark.asyncio
@respx.mock
async def test_create_ticket_full_params(server):
    route = respx.post(f"{BASE}/tickets.json").mock(
        return_value=httpx.Response(
            201,
            json={"ticket": {"id": 2}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_ticket",
        {
            "subject": "Bug",
            "description": "Details",
            "requester_email": "u@e.com",
            "priority": "high",
            "type": "incident",
            "status": "open",
            "tags": ["urgent"],
            "assignee_id": 10,
            "group_id": 20,
            "custom_fields": [
                {"id": 123, "value": "x"}
            ],
            "external_id": "ext-1",
            "due_at": "2026-12-31",
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    t = body["ticket"]
    assert t["priority"] == "high"
    assert t["tags"] == ["urgent"]
    assert t["requester"] == {"email": "u@e.com"}
    assert t["assignee_id"] == 10


@pytest.mark.asyncio
@respx.mock
async def test_get_ticket(server):
    respx.get(f"{BASE}/tickets/1.json").mock(
        return_value=httpx.Response(
            200,
            json={"ticket": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_ticket", {"ticket_id": 1},
    ))
    assert r["status"] == "success"
    assert r["data"]["id"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_ticket_with_include(server):
    respx.get(f"{BASE}/tickets/1.json").mock(
        return_value=httpx.Response(
            200,
            json={"ticket": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_ticket",
        {"ticket_id": 1, "include": "users,groups"},
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_ticket(server):
    route = respx.put(f"{BASE}/tickets/1.json").mock(
        return_value=httpx.Response(
            200,
            json={"ticket": {"id": 1, "status": "solved"}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_update_ticket",
        {"ticket_id": 1, "status": "solved"},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "ticket" in body
    assert body["ticket"]["status"] == "solved"


@pytest.mark.asyncio
async def test_update_ticket_no_fields(server):
    with pytest.raises(
        Exception, match="At least one field"
    ):
        await server.call_tool(
            "zendesk_update_ticket", {"ticket_id": 1},
        )


@pytest.mark.asyncio
@respx.mock
async def test_delete_ticket(server):
    respx.delete(f"{BASE}/tickets/1.json").mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "zendesk_delete_ticket", {"ticket_id": 1},
    ))
    assert r["status"] == "success"
    assert r["deleted"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_tickets(server):
    respx.get(f"{BASE}/tickets.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "tickets": [{"id": 1}, {"id": 2}],
                "meta": {
                    "has_more": True,
                    "after_cursor": "abc",
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_tickets", {},
    ))
    assert r["count"] == 2
    assert r["has_more"] is True
    assert r["after_cursor"] == "abc"


@pytest.mark.asyncio
@respx.mock
async def test_list_tickets_by_requester(server):
    respx.get(
        f"{BASE}/users/5/tickets/requested.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"tickets": [{"id": 1}], "meta": {}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_tickets",
        {"requester_id": 5},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_tickets_by_assignee(server):
    respx.get(
        f"{BASE}/users/7/tickets/assigned.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"tickets": [], "meta": {}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_tickets",
        {"assignee_id": 7},
    ))
    assert r["count"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_list_tickets_by_org(server):
    respx.get(
        f"{BASE}/organizations/3/tickets.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"tickets": [{"id": 9}], "meta": {}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_tickets",
        {"organization_id": 3},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_add_ticket_comment(server):
    route = respx.put(f"{BASE}/tickets/1.json").mock(
        return_value=httpx.Response(
            200,
            json={"ticket": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_add_ticket_comment",
        {"ticket_id": 1, "body": "Hello"},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "ticket" in body
    assert body["ticket"]["comment"]["body"] == "Hello"


@pytest.mark.asyncio
@respx.mock
async def test_add_ticket_comment_internal(server):
    route = respx.put(f"{BASE}/tickets/1.json").mock(
        return_value=httpx.Response(
            200,
            json={"ticket": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_add_ticket_comment",
        {
            "ticket_id": 1,
            "body": "Internal",
            "public": False,
            "author_id": 5,
            "html_body": "<b>Bold</b>",
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    comment = body["ticket"]["comment"]
    assert comment["body"] == "Internal"
    assert comment["public"] is False
    assert comment["author_id"] == 5
    assert comment["html_body"] == "<b>Bold</b>"


@pytest.mark.asyncio
@respx.mock
async def test_list_ticket_comments(server):
    respx.get(
        f"{BASE}/tickets/1/comments.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "comments": [{"id": 100}],
                "meta": {
                    "has_more": False,
                    "after_cursor": None,
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_ticket_comments",
        {"ticket_id": 1},
    ))
    assert r["count"] == 1
    assert r["has_more"] is False


@pytest.mark.asyncio
@respx.mock
async def test_add_ticket_tags(server):
    route = respx.put(f"{BASE}/tickets/1/tags.json").mock(
        return_value=httpx.Response(
            200,
            json={"tags": ["bug", "urgent"]},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_add_ticket_tags",
        {"ticket_id": 1, "tags": ["urgent"]},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["tags"] == ["urgent"]


@pytest.mark.asyncio
@respx.mock
async def test_remove_ticket_tags(server):
    respx.delete(
        f"{BASE}/tickets/1/tags.json"
    ).mock(
        return_value=httpx.Response(
            200, json={"tags": ["bug"]},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_remove_ticket_tags",
        {"ticket_id": 1, "tags": ["urgent"]},
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_set_ticket_tags(server):
    route = respx.post(f"{BASE}/tickets/1/tags.json").mock(
        return_value=httpx.Response(
            200, json={"tags": ["new"]},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_set_ticket_tags",
        {"ticket_id": 1, "tags": ["new"]},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["tags"] == ["new"]


@pytest.mark.asyncio
@respx.mock
async def test_merge_tickets(server):
    route = respx.post(f"{BASE}/tickets/1/merge.json").mock(
        return_value=httpx.Response(
            200, json={"job_status": {"id": "abc"}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_merge_tickets",
        {
            "target_ticket_id": 1,
            "source_ticket_ids": [2, 3],
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["ids"] == [2, 3]


@pytest.mark.asyncio
@respx.mock
async def test_merge_tickets_with_comments(server):
    route = respx.post(f"{BASE}/tickets/1/merge.json").mock(
        return_value=httpx.Response(
            200, json={"job_status": {"id": "abc"}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_merge_tickets",
        {
            "target_ticket_id": 1,
            "source_ticket_ids": [2],
            "target_comment": "Merged",
            "source_comment": "See #1",
            "target_comment_is_public": False,
            "source_comment_is_public": False,
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["ids"] == [2]
    assert body["target_comment"] == "Merged"
    assert body["source_comment"] == "See #1"
    assert body["target_comment_is_public"] is False
    assert body["source_comment_is_public"] is False


@pytest.mark.asyncio
@respx.mock
async def test_bulk_update_tickets(server):
    route = respx.put(url__startswith=f"{BASE}/tickets/update_many.json").mock(
        return_value=httpx.Response(
            200,
            json={"job_status": {"id": "j1"}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_bulk_update_tickets",
        {
            "ticket_ids": [1, 2, 3],
            "status": "solved",
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "ticket" in body
    assert body["ticket"]["status"] == "solved"


@pytest.mark.asyncio
@respx.mock
async def test_apply_macro(server):
    respx.get(
        f"{BASE}/tickets/1/macros/10/apply.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "ticket": {"status": "solved"}
                }
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_apply_macro",
        {"ticket_id": 1, "macro_id": 10},
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_ticket_audits(server):
    respx.get(
        f"{BASE}/tickets/1/audits.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "audits": [{"id": 50}],
                "meta": {
                    "has_more": False,
                    "after_cursor": None,
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_ticket_audits",
        {"ticket_id": 1},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_ticket_collaborators(server):
    respx.get(
        f"{BASE}/tickets/1/collaborators.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"users": [{"id": 5}, {"id": 6}]},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_ticket_collaborators",
        {"ticket_id": 1},
    ))
    assert r["count"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_list_ticket_incidents(server):
    respx.get(
        f"{BASE}/tickets/1/incidents.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"tickets": [{"id": 10}]},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_ticket_incidents",
        {"ticket_id": 1},
    ))
    assert r["count"] == 1


# =========================================================
# TIER 2: USER MANAGEMENT (10 tools)
# =========================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_user(server):
    route = respx.post(f"{BASE}/users.json").mock(
        return_value=httpx.Response(
            201,
            json={"user": {"id": 1, "name": "Jo"}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_user",
        {"name": "Jo", "email": "jo@e.com"},
    ))
    assert r["status"] == "success"
    assert r["data"]["id"] == 1
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "user" in body
    assert body["user"]["name"] == "Jo"
    assert body["user"]["email"] == "jo@e.com"


@pytest.mark.asyncio
@respx.mock
async def test_create_user_full_params(server):
    route = respx.post(f"{BASE}/users.json").mock(
        return_value=httpx.Response(
            201,
            json={"user": {"id": 2}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_user",
        {
            "name": "Jo",
            "email": "jo@e.com",
            "role": "agent",
            "organization_id": 5,
            "phone": "+1555",
            "tags": ["vip"],
            "user_fields": {"tier": "gold"},
            "external_id": "ext-u1",
            "verified": True,
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    u = body["user"]
    assert u["role"] == "agent"
    assert u["organization_id"] == 5
    assert u["tags"] == ["vip"]
    assert u["user_fields"] == {"tier": "gold"}
    assert u["verified"] is True


@pytest.mark.asyncio
@respx.mock
async def test_get_user(server):
    respx.get(f"{BASE}/users/1.json").mock(
        return_value=httpx.Response(
            200,
            json={"user": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_user", {"user_id": 1},
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_user(server):
    route = respx.put(f"{BASE}/users/1.json").mock(
        return_value=httpx.Response(
            200,
            json={"user": {"id": 1, "name": "New"}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_update_user",
        {"user_id": 1, "name": "New"},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "user" in body
    assert body["user"]["name"] == "New"


@pytest.mark.asyncio
async def test_update_user_no_fields(server):
    with pytest.raises(
        Exception, match="At least one field"
    ):
        await server.call_tool(
            "zendesk_update_user", {"user_id": 1},
        )


@pytest.mark.asyncio
@respx.mock
async def test_delete_user(server):
    respx.delete(f"{BASE}/users/1.json").mock(
        return_value=httpx.Response(
            200,
            json={"user": {"id": 1, "active": False}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_delete_user", {"user_id": 1},
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_users(server):
    respx.get(f"{BASE}/users.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "users": [{"id": 1}],
                "meta": {
                    "has_more": False,
                    "after_cursor": None,
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_users", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_users_filtered(server):
    respx.get(f"{BASE}/users.json").mock(
        return_value=httpx.Response(
            200,
            json={"users": [], "meta": {}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_users",
        {"role": "agent", "page_size": 10},
    ))
    assert r["count"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_search_users(server):
    respx.get(f"{BASE}/users/search.json").mock(
        return_value=httpx.Response(
            200,
            json={"users": [{"id": 1}]},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_search_users", {"query": "jo"},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_merge_users(server):
    route = respx.put(f"{BASE}/users/2/merge.json").mock(
        return_value=httpx.Response(
            200,
            json={"user": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_merge_users",
        {"user_id": 2, "target_user_id": 1},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["user"]["id"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_user_identities(server):
    respx.get(
        f"{BASE}/users/1/identities.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "identities": [
                    {"id": 10, "type": "email"}
                ]
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_user_identities",
        {"user_id": 1},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_create_or_update_user(server):
    route = respx.post(
        f"{BASE}/users/create_or_update.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"user": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_or_update_user",
        {"name": "Jo", "email": "jo@e.com"},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "user" in body
    assert body["user"]["name"] == "Jo"
    assert body["user"]["email"] == "jo@e.com"


@pytest.mark.asyncio
@respx.mock
async def test_list_user_tickets(server):
    respx.get(
        f"{BASE}/users/1/tickets/requested.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "tickets": [{"id": 5}],
                "meta": {
                    "has_more": True,
                    "after_cursor": "cur1",
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_user_tickets",
        {"user_id": 1},
    ))
    assert r["count"] == 1
    assert r["has_more"] is True


# =========================================================
# TIER 3: ORGANIZATION MANAGEMENT (6 tools)
# =========================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_organization(server):
    route = respx.post(f"{BASE}/organizations.json").mock(
        return_value=httpx.Response(
            201,
            json={
                "organization": {"id": 1, "name": "Acme"}
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_organization",
        {"name": "Acme"},
    ))
    assert r["status"] == "success"
    assert r["data"]["name"] == "Acme"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "organization" in body
    assert body["organization"]["name"] == "Acme"


@pytest.mark.asyncio
@respx.mock
async def test_create_organization_full(server):
    route = respx.post(f"{BASE}/organizations.json").mock(
        return_value=httpx.Response(
            201,
            json={"organization": {"id": 2}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_organization",
        {
            "name": "Acme",
            "details": "Corp",
            "notes": "Notes",
            "domain_names": ["acme.com"],
            "tags": ["enterprise"],
            "organization_fields": {"size": "large"},
            "external_id": "ext-o1",
            "group_id": 5,
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    org = body["organization"]
    assert org["name"] == "Acme"
    assert org["details"] == "Corp"
    assert org["domain_names"] == ["acme.com"]
    assert org["tags"] == ["enterprise"]
    assert org["group_id"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_get_organization(server):
    respx.get(
        f"{BASE}/organizations/1.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"organization": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_organization",
        {"organization_id": 1},
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_organization(server):
    route = respx.put(
        f"{BASE}/organizations/1.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "organization": {
                    "id": 1, "name": "New"
                }
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_update_organization",
        {"organization_id": 1, "name": "New"},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "organization" in body
    assert body["organization"]["name"] == "New"


@pytest.mark.asyncio
async def test_update_organization_no_fields(server):
    with pytest.raises(
        Exception, match="At least one field"
    ):
        await server.call_tool(
            "zendesk_update_organization",
            {"organization_id": 1},
        )


@pytest.mark.asyncio
@respx.mock
async def test_delete_organization(server):
    respx.delete(
        f"{BASE}/organizations/1.json"
    ).mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "zendesk_delete_organization",
        {"organization_id": 1},
    ))
    assert r["status"] == "success"
    assert r["deleted"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_organizations(server):
    respx.get(f"{BASE}/organizations.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "organizations": [{"id": 1}],
                "meta": {
                    "has_more": False,
                    "after_cursor": None,
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_organizations", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_search_organizations(server):
    respx.get(
        f"{BASE}/organizations/search.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "organizations": [{"id": 1}]
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_search_organizations",
        {"name": "Acme"},
    ))
    assert r["count"] == 1


# =========================================================
# TIER 4: GROUP MANAGEMENT (7 tools)
# =========================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_group(server):
    route = respx.post(f"{BASE}/groups.json").mock(
        return_value=httpx.Response(
            201,
            json={
                "group": {"id": 1, "name": "Support"}
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_group",
        {"name": "Support"},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "group" in body
    assert body["group"]["name"] == "Support"


@pytest.mark.asyncio
@respx.mock
async def test_get_group(server):
    respx.get(f"{BASE}/groups/1.json").mock(
        return_value=httpx.Response(
            200,
            json={"group": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_group", {"group_id": 1},
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_group(server):
    route = respx.put(f"{BASE}/groups/1.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "group": {"id": 1, "name": "Sales"}
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_update_group",
        {"group_id": 1, "name": "Sales"},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "group" in body
    assert body["group"]["name"] == "Sales"


@pytest.mark.asyncio
async def test_update_group_no_fields(server):
    with pytest.raises(
        Exception, match="At least one field"
    ):
        await server.call_tool(
            "zendesk_update_group",
            {"group_id": 1},
        )


@pytest.mark.asyncio
@respx.mock
async def test_delete_group(server):
    respx.delete(f"{BASE}/groups/1.json").mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "zendesk_delete_group", {"group_id": 1},
    ))
    assert r["status"] == "success"
    assert r["deleted"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_groups(server):
    respx.get(f"{BASE}/groups.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "groups": [{"id": 1}],
                "meta": {
                    "has_more": False,
                    "after_cursor": None,
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_groups", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_group_memberships(server):
    respx.get(
        f"{BASE}/groups/1/memberships.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "group_memberships": [{"id": 10}],
                "meta": {
                    "has_more": False,
                    "after_cursor": None,
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_group_memberships",
        {"group_id": 1},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_create_group_membership(server):
    route = respx.post(
        f"{BASE}/group_memberships.json"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "group_membership": {
                    "id": 1,
                    "user_id": 5,
                    "group_id": 1,
                }
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_group_membership",
        {"group_id": 1, "user_id": 5},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "group_membership" in body
    assert body["group_membership"]["user_id"] == 5
    assert body["group_membership"]["group_id"] == 1


# =========================================================
# TIER 5: TICKET FIELDS & FORMS (7 tools)
# =========================================================


@pytest.mark.asyncio
@respx.mock
async def test_list_ticket_fields(server):
    respx.get(f"{BASE}/ticket_fields.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "ticket_fields": [{"id": 1}],
                "meta": {
                    "has_more": False,
                    "after_cursor": None,
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_ticket_fields", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_ticket_field(server):
    respx.get(
        f"{BASE}/ticket_fields/1.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"ticket_field": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_ticket_field",
        {"ticket_field_id": 1},
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_ticket_field(server):
    route = respx.post(f"{BASE}/ticket_fields.json").mock(
        return_value=httpx.Response(
            201,
            json={"ticket_field": {"id": 99}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_ticket_field",
        {"type": "text", "title": "Priority Level"},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "ticket_field" in body
    assert body["ticket_field"]["type"] == "text"
    assert body["ticket_field"]["title"] == "Priority Level"


@pytest.mark.asyncio
@respx.mock
async def test_create_ticket_field_dropdown(server):
    route = respx.post(f"{BASE}/ticket_fields.json").mock(
        return_value=httpx.Response(
            201,
            json={"ticket_field": {"id": 100}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_ticket_field",
        {
            "type": "tagger",
            "title": "Category",
            "required": True,
            "active": True,
            "visible_in_portal": True,
            "editable_in_portal": False,
            "tag": "cat",
            "custom_field_options": [
                {"name": "A", "value": "a"},
            ],
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    tf = body["ticket_field"]
    assert tf["type"] == "tagger"
    assert tf["required"] is True
    assert tf["tag"] == "cat"
    assert tf["custom_field_options"] == [{"name": "A", "value": "a"}]


@pytest.mark.asyncio
@respx.mock
async def test_update_ticket_field(server):
    route = respx.put(
        f"{BASE}/ticket_fields/1.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"ticket_field": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_update_ticket_field",
        {"ticket_field_id": 1, "title": "New Title"},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "ticket_field" in body
    assert body["ticket_field"]["title"] == "New Title"


@pytest.mark.asyncio
async def test_update_ticket_field_no_fields(server):
    with pytest.raises(
        Exception, match="At least one field"
    ):
        await server.call_tool(
            "zendesk_update_ticket_field",
            {"ticket_field_id": 1},
        )


@pytest.mark.asyncio
@respx.mock
async def test_delete_ticket_field(server):
    respx.delete(
        f"{BASE}/ticket_fields/1.json"
    ).mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "zendesk_delete_ticket_field",
        {"ticket_field_id": 1},
    ))
    assert r["status"] == "success"
    assert r["deleted"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_ticket_forms(server):
    respx.get(f"{BASE}/ticket_forms.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "ticket_forms": [{"id": 1}]
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_ticket_forms", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_ticket_forms_active(server):
    respx.get(f"{BASE}/ticket_forms.json").mock(
        return_value=httpx.Response(
            200,
            json={"ticket_forms": []},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_ticket_forms",
        {"active": True},
    ))
    assert r["count"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_ticket_form(server):
    respx.get(
        f"{BASE}/ticket_forms/1.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"ticket_form": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_ticket_form",
        {"ticket_form_id": 1},
    ))
    assert r["status"] == "success"


# =========================================================
# TIER 6: VIEWS (4 tools)
# =========================================================


@pytest.mark.asyncio
@respx.mock
async def test_list_views(server):
    respx.get(f"{BASE}/views.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "views": [{"id": 1}],
                "meta": {
                    "has_more": False,
                    "after_cursor": None,
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_views", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_view(server):
    respx.get(f"{BASE}/views/1.json").mock(
        return_value=httpx.Response(
            200,
            json={"view": {"id": 1, "title": "Open"}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_view", {"view_id": 1},
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_execute_view(server):
    respx.get(
        f"{BASE}/views/1/execute.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"rows": [{"ticket": {"id": 1}}]},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_execute_view", {"view_id": 1},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_view_count(server):
    respx.get(
        f"{BASE}/views/1/count.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "view_count": {
                    "value": 42, "fresh": True,
                }
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_view_count", {"view_id": 1},
    ))
    assert r["status"] == "success"
    assert r["data"]["value"] == 42


# =========================================================
# TIER 7: SEARCH (2 tools)
# =========================================================


@pytest.mark.asyncio
@respx.mock
async def test_search(server):
    respx.get(f"{BASE}/search.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"id": 1, "result_type": "ticket"}
                ],
                "count": 1,
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_search",
        {"query": "type:ticket status:open"},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_search_with_pagination(server):
    respx.get(f"{BASE}/search.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"id": 1}],
                "count": 50,
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_search",
        {
            "query": "type:ticket",
            "per_page": 25,
            "page": 2,
            "sort_by": "created_at",
            "sort_order": "desc",
        },
    ))
    assert r["count"] == 50


@pytest.mark.asyncio
@respx.mock
async def test_search_count(server):
    respx.get(f"{BASE}/search/count.json").mock(
        return_value=httpx.Response(
            200,
            json={"count": 123},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_search_count",
        {"query": "type:user"},
    ))
    assert r["status"] == "success"
    assert r["data"] == 123


# =========================================================
# TIER 8: SATISFACTION RATINGS (3 tools)
# =========================================================


@pytest.mark.asyncio
@respx.mock
async def test_list_satisfaction_ratings(server):
    respx.get(
        f"{BASE}/satisfaction_ratings.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "satisfaction_ratings": [
                    {"id": 1, "score": "good"}
                ],
                "meta": {
                    "has_more": False,
                    "after_cursor": None,
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_satisfaction_ratings", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_satisfaction_ratings_filtered(
    server,
):
    respx.get(
        f"{BASE}/satisfaction_ratings.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "satisfaction_ratings": [],
                "meta": {},
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_satisfaction_ratings",
        {
            "score": "bad",
            "start_time": 1700000000,
            "end_time": 1710000000,
        },
    ))
    assert r["count"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_satisfaction_rating(server):
    respx.get(
        f"{BASE}/satisfaction_ratings/1.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "satisfaction_rating": {
                    "id": 1, "score": "good",
                }
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_satisfaction_rating",
        {"rating_id": 1},
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_satisfaction_rating(server):
    route = respx.post(
        f"{BASE}/tickets/1/satisfaction_rating.json"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "satisfaction_rating": {
                    "id": 10, "score": "good",
                }
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_satisfaction_rating",
        {"ticket_id": 1, "score": "good"},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "satisfaction_rating" in body
    assert body["satisfaction_rating"]["score"] == "good"


@pytest.mark.asyncio
@respx.mock
async def test_create_satisfaction_rating_comment(
    server,
):
    route = respx.post(
        f"{BASE}/tickets/1/satisfaction_rating.json"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "satisfaction_rating": {
                    "id": 11, "score": "bad",
                }
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_satisfaction_rating",
        {
            "ticket_id": 1,
            "score": "bad",
            "comment": "Slow response",
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    sr = body["satisfaction_rating"]
    assert sr["score"] == "bad"
    assert sr["comment"] == "Slow response"


# =========================================================
# TIER 9: ATTACHMENTS (2 tools)
# =========================================================


@pytest.mark.asyncio
@respx.mock
async def test_upload_attachment(server, tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    respx.post(f"{BASE}/uploads.json").mock(
        return_value=httpx.Response(
            201,
            json={
                "upload": {
                    "token": "tok123",
                    "attachment": {"id": 1},
                }
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_upload_attachment",
        {"file_path": str(f)},
    ))
    assert r["status"] == "success"
    assert r["data"]["token"] == "tok123"


@pytest.mark.asyncio
async def test_upload_attachment_missing_file(server):
    with pytest.raises(
        Exception, match="File not found"
    ):
        await server.call_tool(
            "zendesk_upload_attachment",
            {"file_path": "/no/such/file.txt"},
        )


@pytest.mark.asyncio
@respx.mock
async def test_delete_upload(server):
    respx.delete(f"{BASE}/uploads/tok123.json").mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "zendesk_delete_upload",
        {"token": "tok123"},
    ))
    assert r["status"] == "success"


# =========================================================
# TIER 10: SUSPENDED TICKETS (4 tools)
# =========================================================


@pytest.mark.asyncio
@respx.mock
async def test_list_suspended_tickets(server):
    respx.get(
        f"{BASE}/suspended_tickets.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "suspended_tickets": [{"id": 1}],
                "meta": {
                    "has_more": False,
                    "after_cursor": None,
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_suspended_tickets", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_suspended_ticket(server):
    respx.get(
        f"{BASE}/suspended_tickets/1.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "suspended_ticket": {"id": 1}
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_suspended_ticket",
        {"suspended_ticket_id": 1},
    ))
    assert r["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_recover_suspended_ticket(server):
    route = respx.put(
        f"{BASE}/suspended_tickets/1/recover.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"ticket": {"id": 99}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_recover_suspended_ticket",
        {"suspended_ticket_id": 1},
    ))
    assert r["status"] == "success"
    assert route.calls


@pytest.mark.asyncio
@respx.mock
async def test_delete_suspended_ticket(server):
    respx.delete(
        f"{BASE}/suspended_tickets/1.json"
    ).mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "zendesk_delete_suspended_ticket",
        {"suspended_ticket_id": 1},
    ))
    assert r["status"] == "success"
    assert r["deleted"] == 1


# =========================================================
# TIER 11: MACROS (5 tools)
# =========================================================


@pytest.mark.asyncio
@respx.mock
async def test_list_macros(server):
    respx.get(f"{BASE}/macros.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "macros": [{"id": 1}],
                "meta": {
                    "has_more": False,
                    "after_cursor": None,
                },
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_macros", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_macros_filtered(server):
    respx.get(f"{BASE}/macros.json").mock(
        return_value=httpx.Response(
            200,
            json={"macros": [], "meta": {}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_list_macros",
        {
            "active": True,
            "category": 5,
            "group_id": 2,
            "sort_by": "alphabetical",
            "sort_order": "asc",
            "include": "usage_7d",
        },
    ))
    assert r["count"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_macro(server):
    respx.get(f"{BASE}/macros/1.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "macro": {"id": 1, "title": "Close"}
            },
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_get_macro", {"macro_id": 1},
    ))
    assert r["status"] == "success"
    assert r["data"]["title"] == "Close"


@pytest.mark.asyncio
@respx.mock
async def test_create_macro(server):
    route = respx.post(f"{BASE}/macros.json").mock(
        return_value=httpx.Response(
            201,
            json={"macro": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_macro",
        {
            "title": "Close & Tag",
            "actions": [
                {"field": "status", "value": "solved"},
            ],
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "macro" in body
    assert body["macro"]["title"] == "Close & Tag"
    assert body["macro"]["actions"][0]["field"] == "status"


@pytest.mark.asyncio
@respx.mock
async def test_create_macro_full_params(server):
    route = respx.post(f"{BASE}/macros.json").mock(
        return_value=httpx.Response(
            201,
            json={"macro": {"id": 2}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_create_macro",
        {
            "title": "Escalate",
            "actions": [
                {
                    "field": "priority",
                    "value": "urgent",
                },
            ],
            "description": "Escalate to urgent",
            "active": True,
            "restriction": {
                "type": "Group", "id": 5,
            },
        },
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    m = body["macro"]
    assert m["title"] == "Escalate"
    assert m["description"] == "Escalate to urgent"
    assert m["active"] is True
    assert m["restriction"]["type"] == "Group"


@pytest.mark.asyncio
@respx.mock
async def test_update_macro(server):
    route = respx.put(f"{BASE}/macros/1.json").mock(
        return_value=httpx.Response(
            200,
            json={"macro": {"id": 1}},
        ),
    )
    r = _r(await server.call_tool(
        "zendesk_update_macro",
        {"macro_id": 1, "title": "New Title"},
    ))
    assert r["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "macro" in body
    assert body["macro"]["title"] == "New Title"


@pytest.mark.asyncio
async def test_update_macro_no_fields(server):
    with pytest.raises(
        Exception, match="At least one field"
    ):
        await server.call_tool(
            "zendesk_update_macro",
            {"macro_id": 1},
        )


@pytest.mark.asyncio
@respx.mock
async def test_delete_macro(server):
    respx.delete(f"{BASE}/macros/1.json").mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "zendesk_delete_macro", {"macro_id": 1},
    ))
    assert r["status"] == "success"
    assert r["deleted"] == 1
