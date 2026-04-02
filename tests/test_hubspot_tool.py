"""Tests for HubSpot CRM tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.hubspot_tool import register_tools

HB = "https://api.hubapi.com"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.hubspot_tool.HUBSPOT_API_TOKEN", "pat-test"), \
         patch("mcp_toolbox.tools.hubspot_tool._client", None):
        register_tools(mcp)
        yield mcp


# --- Auth ---

@pytest.mark.asyncio
async def test_missing_token():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.hubspot_tool.HUBSPOT_API_TOKEN", None), \
         patch("mcp_toolbox.tools.hubspot_tool._client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="HUBSPOT_API_TOKEN"):
            await mcp.call_tool("hubspot_list_contacts", {})


@pytest.mark.asyncio
@respx.mock
async def test_api_error_429(server):
    respx.get(f"{HB}/crm/v3/objects/contacts").mock(
        return_value=httpx.Response(429)
    )
    with pytest.raises(Exception, match="rate limit"):
        await server.call_tool("hubspot_list_contacts", {})


# --- Contacts ---

@pytest.mark.asyncio
@respx.mock
async def test_create_contact(server):
    respx.post(f"{HB}/crm/v3/objects/contacts").mock(
        return_value=httpx.Response(201, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_create_contact", {
        "email": "j@e.com",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_get_contact(server):
    respx.get(f"{HB}/crm/v3/objects/contacts/1").mock(
        return_value=httpx.Response(200, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_get_contact", {
        "contact_id": "1",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_update_contact(server):
    respx.patch(f"{HB}/crm/v3/objects/contacts/1").mock(
        return_value=httpx.Response(200, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_update_contact", {
        "contact_id": "1", "firstname": "John",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_delete_contact(server):
    respx.delete(f"{HB}/crm/v3/objects/contacts/1").mock(
        return_value=httpx.Response(204)
    )
    assert _r(await server.call_tool("hubspot_delete_contact", {
        "contact_id": "1",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_contacts(server):
    respx.get(f"{HB}/crm/v3/objects/contacts").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "1"}]})
    )
    assert _r(await server.call_tool("hubspot_list_contacts", {}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_search_contacts(server):
    respx.post(f"{HB}/crm/v3/objects/contacts/search").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "1"}]})
    )
    assert _r(await server.call_tool("hubspot_search_contacts", {
        "query": "john",
    }))["count"] == 1

# --- Companies ---

@pytest.mark.asyncio
@respx.mock
async def test_create_company(server):
    respx.post(f"{HB}/crm/v3/objects/companies").mock(
        return_value=httpx.Response(201, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_create_company", {
        "name": "Acme",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_get_company(server):
    respx.get(f"{HB}/crm/v3/objects/companies/1").mock(
        return_value=httpx.Response(200, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_get_company", {
        "company_id": "1",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_update_company(server):
    respx.patch(f"{HB}/crm/v3/objects/companies/1").mock(
        return_value=httpx.Response(200, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_update_company", {
        "company_id": "1", "name": "New Name",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_delete_company(server):
    respx.delete(f"{HB}/crm/v3/objects/companies/1").mock(
        return_value=httpx.Response(204)
    )
    assert _r(await server.call_tool("hubspot_delete_company", {
        "company_id": "1",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_companies(server):
    respx.get(f"{HB}/crm/v3/objects/companies").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    assert _r(await server.call_tool("hubspot_list_companies", {}))["count"] == 0

@pytest.mark.asyncio
@respx.mock
async def test_search_companies(server):
    respx.post(f"{HB}/crm/v3/objects/companies/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    assert _r(await server.call_tool("hubspot_search_companies", {}))["count"] == 0

# --- Deals ---

@pytest.mark.asyncio
@respx.mock
async def test_create_deal(server):
    respx.post(f"{HB}/crm/v3/objects/deals").mock(
        return_value=httpx.Response(201, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_create_deal", {
        "dealname": "Big Deal",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_get_deal(server):
    respx.get(f"{HB}/crm/v3/objects/deals/1").mock(
        return_value=httpx.Response(200, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_get_deal", {"deal_id": "1"}))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_update_deal(server):
    respx.patch(f"{HB}/crm/v3/objects/deals/1").mock(
        return_value=httpx.Response(200, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_update_deal", {
        "deal_id": "1", "amount": "5000",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_delete_deal(server):
    respx.delete(f"{HB}/crm/v3/objects/deals/1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("hubspot_delete_deal", {"deal_id": "1"})
    assert _r(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_deals(server):
    respx.get(f"{HB}/crm/v3/objects/deals").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    assert _r(await server.call_tool("hubspot_list_deals", {}))["count"] == 0

@pytest.mark.asyncio
@respx.mock
async def test_search_deals(server):
    respx.post(f"{HB}/crm/v3/objects/deals/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    assert _r(await server.call_tool("hubspot_search_deals", {}))["count"] == 0

# --- Tickets ---

@pytest.mark.asyncio
@respx.mock
async def test_create_ticket(server):
    respx.post(f"{HB}/crm/v3/objects/tickets").mock(
        return_value=httpx.Response(201, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_create_ticket", {
        "subject": "Bug",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_get_ticket(server):
    respx.get(f"{HB}/crm/v3/objects/tickets/1").mock(
        return_value=httpx.Response(200, json={"id": "1"})
    )
    result = await server.call_tool("hubspot_get_ticket", {"ticket_id": "1"})
    assert _r(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_update_ticket(server):
    respx.patch(f"{HB}/crm/v3/objects/tickets/1").mock(
        return_value=httpx.Response(200, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_update_ticket", {
        "ticket_id": "1", "subject": "Fixed",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_delete_ticket(server):
    respx.delete(f"{HB}/crm/v3/objects/tickets/1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("hubspot_delete_ticket", {"ticket_id": "1"})
    assert _r(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_tickets(server):
    respx.get(f"{HB}/crm/v3/objects/tickets").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    assert _r(await server.call_tool("hubspot_list_tickets", {}))["count"] == 0

@pytest.mark.asyncio
@respx.mock
async def test_search_tickets(server):
    respx.post(f"{HB}/crm/v3/objects/tickets/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    assert _r(await server.call_tool("hubspot_search_tickets", {}))["count"] == 0

# --- Notes ---

@pytest.mark.asyncio
@respx.mock
async def test_create_note(server):
    respx.post(f"{HB}/crm/v3/objects/notes").mock(
        return_value=httpx.Response(201, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_create_note", {
        "body": "Called client",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_get_note(server):
    respx.get(f"{HB}/crm/v3/objects/notes/1").mock(
        return_value=httpx.Response(200, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_get_note", {"note_id": "1"}))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_notes(server):
    respx.get(f"{HB}/crm/v3/objects/notes").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    assert _r(await server.call_tool("hubspot_list_notes", {}))["count"] == 0

@pytest.mark.asyncio
@respx.mock
async def test_update_note(server):
    respx.patch(f"{HB}/crm/v3/objects/notes/1").mock(
        return_value=httpx.Response(200, json={"id": "1"})
    )
    assert _r(await server.call_tool("hubspot_update_note", {
        "note_id": "1", "body": "Updated",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_delete_note(server):
    respx.delete(f"{HB}/crm/v3/objects/notes/1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("hubspot_delete_note", {"note_id": "1"})
    assert _r(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_search_notes(server):
    respx.post(f"{HB}/crm/v3/objects/notes/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    assert _r(await server.call_tool("hubspot_search_notes", {}))["count"] == 0

# --- Associations ---

@pytest.mark.asyncio
@respx.mock
async def test_create_association(server):
    respx.put(f"{HB}/crm/v4/objects/contacts/1/associations/companies/2").mock(
        return_value=httpx.Response(200, json={})
    )
    assert _r(await server.call_tool("hubspot_create_association", {
        "from_object_type": "contacts", "from_object_id": "1",
        "to_object_type": "companies", "to_object_id": "2",
        "association_type_id": 1,
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_remove_association(server):
    respx.delete(f"{HB}/crm/v4/objects/contacts/1/associations/companies/2").mock(
        return_value=httpx.Response(204)
    )
    assert _r(await server.call_tool("hubspot_remove_association", {
        "from_object_type": "contacts", "from_object_id": "1",
        "to_object_type": "companies", "to_object_id": "2",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_get_associations(server):
    respx.get(f"{HB}/crm/v4/objects/contacts/1/associations/companies").mock(
        return_value=httpx.Response(200, json={"results": [{"toObjectId": "2"}]})
    )
    assert _r(await server.call_tool("hubspot_get_associations", {
        "from_object_type": "contacts", "from_object_id": "1",
        "to_object_type": "companies",
    }))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_list_association_types(server):
    respx.get(f"{HB}/crm/v4/associations/contacts/companies/labels").mock(
        return_value=httpx.Response(200, json={"results": [{"typeId": 1}]})
    )
    assert _r(await server.call_tool("hubspot_list_association_types", {
        "from_object_type": "contacts", "to_object_type": "companies",
    }))["count"] == 1

# --- Pipelines ---

@pytest.mark.asyncio
@respx.mock
async def test_list_pipelines(server):
    respx.get(f"{HB}/crm/v3/pipelines/deals").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "p1"}]})
    )
    assert _r(await server.call_tool("hubspot_list_pipelines", {}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_list_pipeline_stages(server):
    respx.get(f"{HB}/crm/v3/pipelines/deals/p1/stages").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "s1"}]})
    )
    assert _r(await server.call_tool("hubspot_list_pipeline_stages", {
        "pipeline_id": "p1",
    }))["count"] == 1

# --- Owners ---

@pytest.mark.asyncio
@respx.mock
async def test_list_owners(server):
    respx.get(f"{HB}/crm/v3/owners").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "o1"}]})
    )
    assert _r(await server.call_tool("hubspot_list_owners", {}))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_get_owner(server):
    respx.get(f"{HB}/crm/v3/owners/o1").mock(
        return_value=httpx.Response(200, json={"id": "o1"})
    )
    result = await server.call_tool("hubspot_get_owner", {"owner_id": "o1"})
    assert _r(result)["status"] == "success"

# --- Properties ---

@pytest.mark.asyncio
@respx.mock
async def test_list_properties(server):
    respx.get(f"{HB}/crm/v3/properties/contacts").mock(
        return_value=httpx.Response(200, json={"results": [{"name": "email"}]})
    )
    assert _r(await server.call_tool("hubspot_list_properties", {
        "object_type": "contacts",
    }))["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_get_property(server):
    respx.get(f"{HB}/crm/v3/properties/contacts/email").mock(
        return_value=httpx.Response(200, json={"name": "email"})
    )
    assert _r(await server.call_tool("hubspot_get_property", {
        "object_type": "contacts", "property_name": "email",
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_create_property(server):
    respx.post(f"{HB}/crm/v3/properties/contacts").mock(
        return_value=httpx.Response(201, json={"name": "custom_field"})
    )
    assert _r(await server.call_tool("hubspot_create_property", {
        "object_type": "contacts", "name": "custom_field",
        "label": "Custom Field", "type": "string", "field_type": "text",
    }))["status"] == "success"

# --- Batch ---

@pytest.mark.asyncio
@respx.mock
async def test_batch_create(server):
    respx.post(f"{HB}/crm/v3/objects/contacts/batch/create").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "1"}]})
    )
    assert _r(await server.call_tool("hubspot_batch_create", {
        "object_type": "contacts",
        "inputs": [{"properties": {"email": "a@b.com"}}],
    }))["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_batch_update(server):
    respx.post(f"{HB}/crm/v3/objects/contacts/batch/update").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "1"}]})
    )
    assert _r(await server.call_tool("hubspot_batch_update", {
        "object_type": "contacts",
        "inputs": [{"id": "1", "properties": {"firstname": "Jane"}}],
    }))["status"] == "success"
