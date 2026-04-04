"""Tests for Salesforce REST API tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.salesforce_tool import register_tools

BASE = (
    "https://test.salesforce.com/services/data/v59.0"
)


def _r(result) -> dict:
    return json.loads(result[0][0].text)


def _ok(result) -> None:
    assert _r(result)["status"] == "success"


MOD = "mcp_toolbox.tools.salesforce_tool"


@pytest.fixture
def server():
    mcp = FastMCP("test")
    with (
        patch(f"{MOD}.SF_CLIENT_ID", "cid"),
        patch(f"{MOD}.SF_CLIENT_SECRET", "cs"),
        patch(f"{MOD}.SF_REFRESH_TOKEN", "rt"),
        patch(f"{MOD}.SF_INSTANCE_URL",
              "https://test.salesforce.com"),
        patch(f"{MOD}.SF_API_VERSION", "v59.0"),
        patch(f"{MOD}._client", None),
        patch(f"{MOD}._access_token", "tok"),
        patch(f"{MOD}._token_expires_at", 9999999999.0),
        patch(f"{MOD}._instance_url",
              "https://test.salesforce.com"),
    ):
        register_tools(mcp)
        yield mcp


# ===================================================
# AUTH / ERROR TESTS
# ===================================================


@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with (
        patch(f"{MOD}.SF_CLIENT_ID", None),
        patch(f"{MOD}.SF_CLIENT_SECRET", None),
        patch(f"{MOD}.SF_REFRESH_TOKEN", None),
        patch(f"{MOD}.SF_INSTANCE_URL", None),
        patch(f"{MOD}.SF_API_VERSION", "v59.0"),
        patch(f"{MOD}._client", None),
        patch(f"{MOD}._access_token", None),
        patch(f"{MOD}._token_expires_at", 0.0),
        patch(f"{MOD}._instance_url", None),
    ):
        register_tools(mcp)
        with pytest.raises(
            Exception, match="not configured"
        ):
            await mcp.call_tool(
                "sf_query", {"query": "SELECT Id FROM Account"},
            )


@pytest.mark.asyncio
@respx.mock
async def test_api_error(server):
    respx.get(f"{BASE}/sobjects/Account/bad").mock(
        return_value=httpx.Response(
            400,
            json=[{"message": "invalid id", "errorCode": "X"}],
        ),
    )
    with pytest.raises(Exception, match="invalid id"):
        await server.call_tool(
            "sf_get_account", {"account_id": "bad"},
        )


@pytest.mark.asyncio
@respx.mock
async def test_api_error_dict(server):
    respx.get(f"{BASE}/sobjects/Account/bad2").mock(
        return_value=httpx.Response(
            404,
            json={"message": "not found"},
        ),
    )
    with pytest.raises(Exception, match="not found"):
        await server.call_tool(
            "sf_get_account", {"account_id": "bad2"},
        )


@pytest.mark.asyncio
async def test_update_no_fields(server):
    with pytest.raises(
        Exception, match="At least one field"
    ):
        await server.call_tool(
            "sf_update_account",
            {"account_id": "001xx"},
        )


# ===================================================
# ACCOUNT SOBJECT (6 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_account(server):
    route = respx.post(f"{BASE}/sobjects/Account/").mock(
        return_value=httpx.Response(
            201, json={"id": "001xx", "success": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_create_account", {"name": "Acme Corp"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["Name"] == "Acme Corp"


@pytest.mark.asyncio
@respx.mock
async def test_get_account(server):
    respx.get(f"{BASE}/sobjects/Account/001xx").mock(
        return_value=httpx.Response(
            200, json={"Id": "001xx", "Name": "Acme"},
        ),
    )
    _ok(await server.call_tool(
        "sf_get_account", {"account_id": "001xx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_account(server):
    route = respx.patch(f"{BASE}/sobjects/Account/001xx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_update_account",
        {"account_id": "001xx", "name": "New Name"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["Name"] == "New Name"


@pytest.mark.asyncio
@respx.mock
async def test_delete_account(server):
    respx.delete(f"{BASE}/sobjects/Account/001xx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_delete_account", {"account_id": "001xx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_accounts(server):
    respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 1, "done": True,
            "records": [{"Id": "001xx"}],
        }),
    )
    r = _r(await server.call_tool(
        "sf_list_accounts", {},
    ))
    assert r["data"]["totalSize"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_upsert_account(server):
    respx.patch(
        f"{BASE}/sobjects/Account/ExtId__c/ext1"
    ).mock(
        return_value=httpx.Response(
            201, json={"id": "001xx", "created": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_upsert_account", {
            "external_id_field": "ExtId__c",
            "external_id_value": "ext1",
            "name": "Upserted",
        },
    ))


# ===================================================
# CONTACT SOBJECT (6 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_contact(server):
    route = respx.post(f"{BASE}/sobjects/Contact/").mock(
        return_value=httpx.Response(
            201, json={"id": "003xx", "success": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_create_contact", {"last_name": "Smith"},
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["LastName"] == "Smith"


@pytest.mark.asyncio
@respx.mock
async def test_get_contact(server):
    respx.get(f"{BASE}/sobjects/Contact/003xx").mock(
        return_value=httpx.Response(
            200, json={"Id": "003xx"},
        ),
    )
    _ok(await server.call_tool(
        "sf_get_contact", {"contact_id": "003xx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_contact(server):
    respx.patch(f"{BASE}/sobjects/Contact/003xx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_update_contact",
        {"contact_id": "003xx", "email": "a@b.com"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_contact(server):
    respx.delete(f"{BASE}/sobjects/Contact/003xx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_delete_contact", {"contact_id": "003xx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_contacts(server):
    respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 0, "done": True, "records": [],
        }),
    )
    _ok(await server.call_tool("sf_list_contacts", {}))


@pytest.mark.asyncio
@respx.mock
async def test_upsert_contact(server):
    respx.patch(
        f"{BASE}/sobjects/Contact/ExtId__c/ext2"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_upsert_contact", {
            "external_id_field": "ExtId__c",
            "external_id_value": "ext2",
            "last_name": "Jones",
        },
    ))


# ===================================================
# OPPORTUNITY SOBJECT (6 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_opportunity(server):
    route = respx.post(f"{BASE}/sobjects/Opportunity/").mock(
        return_value=httpx.Response(
            201, json={"id": "006xx", "success": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_create_opportunity", {
            "name": "Big Deal",
            "stage_name": "Prospecting",
            "close_date": "2026-12-31",
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["Name"] == "Big Deal"
    assert body["StageName"] == "Prospecting"
    assert body["CloseDate"] == "2026-12-31"


@pytest.mark.asyncio
@respx.mock
async def test_get_opportunity(server):
    respx.get(
        f"{BASE}/sobjects/Opportunity/006xx"
    ).mock(
        return_value=httpx.Response(
            200, json={"Id": "006xx"},
        ),
    )
    _ok(await server.call_tool(
        "sf_get_opportunity",
        {"opportunity_id": "006xx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_opportunity(server):
    respx.patch(
        f"{BASE}/sobjects/Opportunity/006xx"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_update_opportunity", {
            "opportunity_id": "006xx",
            "stage_name": "Closed Won",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_opportunity(server):
    respx.delete(
        f"{BASE}/sobjects/Opportunity/006xx"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_delete_opportunity",
        {"opportunity_id": "006xx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_opportunities(server):
    respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 2, "done": True,
            "records": [{"Id": "006xx"}, {"Id": "006yy"}],
        }),
    )
    r = _r(await server.call_tool(
        "sf_list_opportunities", {},
    ))
    assert r["data"]["totalSize"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_upsert_opportunity(server):
    respx.patch(
        f"{BASE}/sobjects/Opportunity/ExtId__c/ext3"
    ).mock(
        return_value=httpx.Response(
            201, json={"id": "006xx", "created": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_upsert_opportunity", {
            "external_id_field": "ExtId__c",
            "external_id_value": "ext3",
            "name": "Upserted Opp",
        },
    ))


# ===================================================
# LEAD SOBJECT (6 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_lead(server):
    respx.post(f"{BASE}/sobjects/Lead/").mock(
        return_value=httpx.Response(
            201, json={"id": "00Qxx", "success": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_create_lead", {
            "last_name": "Doe",
            "company": "Acme",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_lead(server):
    respx.get(f"{BASE}/sobjects/Lead/00Qxx").mock(
        return_value=httpx.Response(
            200, json={"Id": "00Qxx"},
        ),
    )
    _ok(await server.call_tool(
        "sf_get_lead", {"lead_id": "00Qxx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_lead(server):
    respx.patch(f"{BASE}/sobjects/Lead/00Qxx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_update_lead", {
            "lead_id": "00Qxx",
            "status": "Working",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_lead(server):
    respx.delete(f"{BASE}/sobjects/Lead/00Qxx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_delete_lead", {"lead_id": "00Qxx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_leads(server):
    respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 0, "done": True, "records": [],
        }),
    )
    _ok(await server.call_tool("sf_list_leads", {}))


@pytest.mark.asyncio
@respx.mock
async def test_convert_lead(server):
    respx.post(
        f"{BASE}/actions/standard/convertLead"
    ).mock(
        return_value=httpx.Response(200, json=[{
            "actionName": "convertLead",
            "isSuccess": True,
            "outputValues": {"accountId": "001xx"},
        }]),
    )
    _ok(await server.call_tool(
        "sf_convert_lead", {
            "lead_id": "00Qxx",
            "converted_status": "Qualified",
        },
    ))


# ===================================================
# CASE SOBJECT (6 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_case(server):
    respx.post(f"{BASE}/sobjects/Case/").mock(
        return_value=httpx.Response(
            201, json={"id": "500xx", "success": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_create_case", {
            "subject": "Bug report",
            "status": "New",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_case(server):
    respx.get(f"{BASE}/sobjects/Case/500xx").mock(
        return_value=httpx.Response(
            200, json={"Id": "500xx"},
        ),
    )
    _ok(await server.call_tool(
        "sf_get_case", {"case_id": "500xx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_case(server):
    respx.patch(f"{BASE}/sobjects/Case/500xx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_update_case", {
            "case_id": "500xx",
            "status": "Closed",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_case(server):
    respx.delete(f"{BASE}/sobjects/Case/500xx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_delete_case", {"case_id": "500xx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_cases(server):
    respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 0, "done": True, "records": [],
        }),
    )
    _ok(await server.call_tool("sf_list_cases", {}))


@pytest.mark.asyncio
@respx.mock
async def test_add_case_comment(server):
    respx.post(f"{BASE}/sobjects/CaseComment/").mock(
        return_value=httpx.Response(
            201,
            json={"id": "00axx", "success": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_add_case_comment", {
            "case_id": "500xx",
            "body": "Fixed now",
        },
    ))


# ===================================================
# TASK SOBJECT (5 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_task(server):
    respx.post(f"{BASE}/sobjects/Task/").mock(
        return_value=httpx.Response(
            201, json={"id": "00Txx", "success": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_create_task", {"subject": "Follow up"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_task(server):
    respx.get(f"{BASE}/sobjects/Task/00Txx").mock(
        return_value=httpx.Response(
            200, json={"Id": "00Txx"},
        ),
    )
    _ok(await server.call_tool(
        "sf_get_task", {"task_id": "00Txx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_task(server):
    respx.patch(f"{BASE}/sobjects/Task/00Txx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_update_task", {
            "task_id": "00Txx",
            "status": "Completed",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_task(server):
    respx.delete(f"{BASE}/sobjects/Task/00Txx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_delete_task", {"task_id": "00Txx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_tasks(server):
    respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 0, "done": True, "records": [],
        }),
    )
    _ok(await server.call_tool("sf_list_tasks", {}))


# ===================================================
# EVENT SOBJECT (5 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_event(server):
    respx.post(f"{BASE}/sobjects/Event/").mock(
        return_value=httpx.Response(
            201, json={"id": "00Uxx", "success": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_create_event", {
            "start_date_time": "2026-05-01T09:00:00Z",
            "end_date_time": "2026-05-01T10:00:00Z",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_event(server):
    respx.get(f"{BASE}/sobjects/Event/00Uxx").mock(
        return_value=httpx.Response(
            200, json={"Id": "00Uxx"},
        ),
    )
    _ok(await server.call_tool(
        "sf_get_event", {"event_id": "00Uxx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_event(server):
    respx.patch(f"{BASE}/sobjects/Event/00Uxx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_update_event", {
            "event_id": "00Uxx",
            "subject": "Updated Meeting",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_event(server):
    respx.delete(f"{BASE}/sobjects/Event/00Uxx").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_delete_event", {"event_id": "00Uxx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_events(server):
    respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 0, "done": True, "records": [],
        }),
    )
    _ok(await server.call_tool("sf_list_events", {}))


# ===================================================
# SOQL QUERIES (3 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_query(server):
    route = respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 1, "done": True,
            "records": [{"Id": "001xx"}],
        }),
    )
    r = _r(await server.call_tool(
        "sf_query",
        {"query": "SELECT Id FROM Account LIMIT 1"},
    ))
    assert r["data"]["totalSize"] == 1
    req = route.calls[0].request
    assert "q=" in str(req.url)
    assert "SELECT" in str(req.url)


@pytest.mark.asyncio
@respx.mock
async def test_query_more(server):
    next_url = (
        "/services/data/v59.0/query/01gxx-2000"
    )
    respx.get(
        f"https://test.salesforce.com{next_url}"
    ).mock(
        return_value=httpx.Response(200, json={
            "totalSize": 5000, "done": True,
            "records": [{"Id": "001yy"}],
        }),
    )
    _ok(await server.call_tool(
        "sf_query_more",
        {"next_records_url": next_url},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_query_all(server):
    respx.get(f"{BASE}/queryAll/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 3, "done": True,
            "records": [{"Id": "001xx", "IsDeleted": True}],
        }),
    )
    _ok(await server.call_tool(
        "sf_query_all",
        {"query": "SELECT Id FROM Account WHERE IsDeleted=true"},
    ))


# ===================================================
# SOSL SEARCH (1 tool)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_search(server):
    respx.get(f"{BASE}/search/").mock(
        return_value=httpx.Response(200, json={
            "searchRecords": [{"Id": "001xx"}],
        }),
    )
    _ok(await server.call_tool(
        "sf_search",
        {"search": "FIND {test} IN ALL FIELDS"},
    ))


# ===================================================
# DESCRIBE / METADATA (4 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_describe_sobject(server):
    respx.get(
        f"{BASE}/sobjects/Account/describe/"
    ).mock(
        return_value=httpx.Response(200, json={
            "name": "Account", "fields": [],
        }),
    )
    _ok(await server.call_tool(
        "sf_describe_sobject",
        {"sobject_name": "Account"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_describe_global(server):
    respx.get(f"{BASE}/sobjects/").mock(
        return_value=httpx.Response(200, json={
            "sobjects": [{"name": "Account"}],
        }),
    )
    _ok(await server.call_tool(
        "sf_describe_global", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_record_types(server):
    respx.get(
        f"{BASE}/sobjects/Account/describe/"
    ).mock(
        return_value=httpx.Response(200, json={
            "name": "Account",
            "recordTypeInfos": [
                {"name": "Master", "active": True},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "sf_get_record_types",
        {"sobject_name": "Account"},
    ))
    assert len(r["data"]) == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_picklist_values(server):
    respx.get(
        f"{BASE}/sobjects/Account/describe/"
    ).mock(
        return_value=httpx.Response(200, json={
            "name": "Account",
            "fields": [{
                "name": "Industry",
                "picklistValues": [
                    {"value": "Tech", "active": True},
                ],
            }],
        }),
    )
    r = _r(await server.call_tool(
        "sf_get_picklist_values", {
            "sobject_name": "Account",
            "field_name": "Industry",
        },
    ))
    assert r["data"][0]["value"] == "Tech"


@pytest.mark.asyncio
@respx.mock
async def test_get_picklist_values_not_found(server):
    respx.get(
        f"{BASE}/sobjects/Account/describe/"
    ).mock(
        return_value=httpx.Response(200, json={
            "name": "Account", "fields": [],
        }),
    )
    with pytest.raises(Exception, match="not found"):
        await server.call_tool(
            "sf_get_picklist_values", {
                "sobject_name": "Account",
                "field_name": "Bogus",
            },
        )


# ===================================================
# GENERIC SOBJECT CRUD (5 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_record(server):
    route = respx.post(
        f"{BASE}/sobjects/CustomObj__c/"
    ).mock(
        return_value=httpx.Response(
            201, json={"id": "a00xx", "success": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_create_record", {
            "sobject_name": "CustomObj__c",
            "fields": {"Name": "Test"},
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["Name"] == "Test"


@pytest.mark.asyncio
@respx.mock
async def test_get_record(server):
    respx.get(
        f"{BASE}/sobjects/CustomObj__c/a00xx"
    ).mock(
        return_value=httpx.Response(
            200, json={"Id": "a00xx"},
        ),
    )
    _ok(await server.call_tool(
        "sf_get_record", {
            "sobject_name": "CustomObj__c",
            "record_id": "a00xx",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_record(server):
    respx.patch(
        f"{BASE}/sobjects/CustomObj__c/a00xx"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_update_record", {
            "sobject_name": "CustomObj__c",
            "record_id": "a00xx",
            "fields": {"Name": "Updated"},
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_record(server):
    respx.delete(
        f"{BASE}/sobjects/CustomObj__c/a00xx"
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "sf_delete_record", {
            "sobject_name": "CustomObj__c",
            "record_id": "a00xx",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_upsert_record(server):
    respx.patch(
        f"{BASE}/sobjects/CustomObj__c/ExtId__c/val1"
    ).mock(
        return_value=httpx.Response(
            201, json={"id": "a00xx", "created": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_upsert_record", {
            "sobject_name": "CustomObj__c",
            "external_id_field": "ExtId__c",
            "external_id_value": "val1",
            "fields": {"Name": "Upserted"},
        },
    ))


# ===================================================
# BULK OPERATIONS (4 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_bulk_create_job(server):
    route = respx.post(f"{BASE}/jobs/ingest/").mock(
        return_value=httpx.Response(201, json={
            "id": "750xx",
            "state": "Open",
            "object": "Account",
        }),
    )
    _ok(await server.call_tool(
        "sf_bulk_create_job", {
            "sobject_name": "Account",
            "operation": "insert",
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["object"] == "Account"
    assert body["operation"] == "insert"


@pytest.mark.asyncio
@respx.mock
async def test_bulk_upload_data(server):
    respx.put(
        f"{BASE}/jobs/ingest/750xx/batches"
    ).mock(
        return_value=httpx.Response(201),
    )
    _ok(await server.call_tool(
        "sf_bulk_upload_data", {
            "job_id": "750xx",
            "csv_data": "Name\nAcme\nGlobex",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_bulk_close_job(server):
    respx.patch(f"{BASE}/jobs/ingest/750xx").mock(
        return_value=httpx.Response(200, json={
            "id": "750xx", "state": "UploadComplete",
        }),
    )
    _ok(await server.call_tool(
        "sf_bulk_close_job", {"job_id": "750xx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_bulk_get_job_status(server):
    respx.get(f"{BASE}/jobs/ingest/750xx").mock(
        return_value=httpx.Response(200, json={
            "id": "750xx",
            "state": "JobComplete",
            "numberRecordsProcessed": 2,
        }),
    )
    r = _r(await server.call_tool(
        "sf_bulk_get_job_status", {"job_id": "750xx"},
    ))
    assert r["data"]["state"] == "JobComplete"


@pytest.mark.asyncio
@respx.mock
async def test_bulk_get_job_results(server):
    respx.get(
        f"{BASE}/jobs/ingest/750xx/successfulResults"
    ).mock(
        return_value=httpx.Response(200, json={
            "records": [{"Id": "001xx"}],
        }),
    )
    _ok(await server.call_tool(
        "sf_bulk_get_job_status", {
            "job_id": "750xx",
            "result_type": "successfulResults",
        },
    ))


# ===================================================
# COMPOSITE REQUESTS (2 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_composite(server):
    route = respx.post(f"{BASE}/composite/").mock(
        return_value=httpx.Response(200, json={
            "compositeResponse": [
                {"httpStatusCode": 200, "body": {"Id": "001xx"}},
            ],
        }),
    )
    _ok(await server.call_tool(
        "sf_composite", {
            "composite_request": [{
                "method": "GET",
                "url": "/services/data/v59.0/sobjects/Account/001xx",
                "referenceId": "ref1",
            }],
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "compositeRequest" in body
    assert isinstance(body["compositeRequest"], list)
    assert body["compositeRequest"][0]["referenceId"] == "ref1"
    assert body["allOrNone"] is False


@pytest.mark.asyncio
@respx.mock
async def test_composite_batch(server):
    route = respx.post(f"{BASE}/composite/batch").mock(
        return_value=httpx.Response(200, json={
            "hasErrors": False,
            "results": [
                {"statusCode": 200, "result": {"Id": "001xx"}},
            ],
        }),
    )
    _ok(await server.call_tool(
        "sf_composite_batch", {
            "batch_requests": [{
                "method": "GET",
                "url": "/services/data/v59.0/sobjects/Account/001xx",
            }],
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert "batchRequests" in body
    assert isinstance(body["batchRequests"], list)


# ===================================================
# REPORTS (3 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_list_reports(server):
    respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 1, "done": True,
            "records": [{"Id": "00Oxx", "Name": "R1"}],
        }),
    )
    _ok(await server.call_tool(
        "sf_list_reports", {},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_run_report(server):
    respx.post(
        f"{BASE}/analytics/reports/00Oxx"
    ).mock(
        return_value=httpx.Response(200, json={
            "reportMetadata": {"id": "00Oxx"},
            "factMap": {},
        }),
    )
    _ok(await server.call_tool(
        "sf_run_report", {"report_id": "00Oxx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_describe_report(server):
    respx.get(
        f"{BASE}/analytics/reports/00Oxx/describe"
    ).mock(
        return_value=httpx.Response(200, json={
            "reportMetadata": {"id": "00Oxx"},
        }),
    )
    _ok(await server.call_tool(
        "sf_describe_report", {"report_id": "00Oxx"},
    ))


# ===================================================
# MISCELLANEOUS (4 tools)
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_get_limits(server):
    respx.get(f"{BASE}/limits/").mock(
        return_value=httpx.Response(200, json={
            "DailyApiRequests": {
                "Max": 15000, "Remaining": 14900,
            },
        }),
    )
    _ok(await server.call_tool("sf_get_limits", {}))


@pytest.mark.asyncio
@respx.mock
async def test_get_user(server):
    respx.get(f"{BASE}/sobjects/User/005xx").mock(
        return_value=httpx.Response(200, json={
            "Id": "005xx", "Username": "admin@test.com",
        }),
    )
    _ok(await server.call_tool(
        "sf_get_user", {"user_id": "005xx"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_current_user(server):
    id_url = (
        "https://test.salesforce.com/id/00Dxx/005xx"
    )
    with patch(f"{MOD}._id_url", id_url):
        respx.get(id_url).mock(
            return_value=httpx.Response(200, json={
                "user_id": "005xx",
                "display_name": "Admin",
            }),
        )
        _ok(await server.call_tool(
            "sf_get_current_user", {},
        ))


@pytest.mark.asyncio
@respx.mock
async def test_get_current_user_no_id_url(server):
    with patch(f"{MOD}._id_url", None):
        with pytest.raises(
            Exception, match="No identity URL"
        ):
            await server.call_tool(
                "sf_get_current_user", {},
            )


@pytest.mark.asyncio
@respx.mock
async def test_get_api_versions(server):
    respx.get(
        "https://test.salesforce.com/services/data/"
    ).mock(
        return_value=httpx.Response(200, json=[
            {"version": "59.0", "url": "/services/data/v59.0"},
        ]),
    )
    _ok(await server.call_tool(
        "sf_get_api_versions", {},
    ))


# ===================================================
# ADDITIONAL EDGE-CASE / PARAM TESTS
# ===================================================


@pytest.mark.asyncio
@respx.mock
async def test_create_account_full_params(server):
    route = respx.post(f"{BASE}/sobjects/Account/").mock(
        return_value=httpx.Response(
            201, json={"id": "001xx", "success": True},
        ),
    )
    _ok(await server.call_tool(
        "sf_create_account", {
            "name": "Full Corp",
            "industry": "Technology",
            "type": "Customer",
            "phone": "555-1234",
            "website": "https://full.com",
            "description": "A company",
            "billing_city": "SF",
            "custom_fields": {"Rating": "Hot"},
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["Name"] == "Full Corp"
    assert body["Industry"] == "Technology"
    assert body["Rating"] == "Hot"


@pytest.mark.asyncio
@respx.mock
async def test_list_accounts_with_filters(server):
    respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 0, "done": True, "records": [],
        }),
    )
    _ok(await server.call_tool(
        "sf_list_accounts", {
            "name_like": "Acme",
            "industry": "Technology",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_opportunities_with_ranges(server):
    respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 0, "done": True, "records": [],
        }),
    )
    _ok(await server.call_tool(
        "sf_list_opportunities", {
            "close_date_gte": "2026-01-01",
            "close_date_lte": "2026-12-31",
            "amount_gte": 1000.0,
            "amount_lte": 50000.0,
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_events_with_date_range(server):
    respx.get(f"{BASE}/query/").mock(
        return_value=httpx.Response(200, json={
            "totalSize": 0, "done": True, "records": [],
        }),
    )
    _ok(await server.call_tool(
        "sf_list_events", {
            "start_date_gte": "2026-04-01T00:00:00Z",
            "start_date_lte": "2026-04-30T23:59:59Z",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_bulk_create_job_upsert(server):
    respx.post(f"{BASE}/jobs/ingest/").mock(
        return_value=httpx.Response(201, json={
            "id": "750yy", "state": "Open",
        }),
    )
    _ok(await server.call_tool(
        "sf_bulk_create_job", {
            "sobject_name": "Contact",
            "operation": "upsert",
            "external_id_field": "Email",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_run_report_with_filters(server):
    respx.post(
        f"{BASE}/analytics/reports/00Oxx"
    ).mock(
        return_value=httpx.Response(200, json={
            "reportMetadata": {"id": "00Oxx"},
            "factMap": {},
        }),
    )
    _ok(await server.call_tool(
        "sf_run_report", {
            "report_id": "00Oxx",
            "include_details": False,
            "filters": [
                {
                    "column": "ACCOUNT.NAME",
                    "operator": "contains",
                    "value": "Acme",
                },
            ],
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_upsert_record_returns_204(server):
    respx.patch(
        f"{BASE}/sobjects/Account/ExtId__c/exist1"
    ).mock(
        return_value=httpx.Response(204),
    )
    r = _r(await server.call_tool(
        "sf_upsert_account", {
            "external_id_field": "ExtId__c",
            "external_id_value": "exist1",
            "name": "Existing",
        },
    ))
    assert r["status_code"] == 204


@pytest.mark.asyncio
@respx.mock
async def test_composite_all_or_none(server):
    route = respx.post(f"{BASE}/composite/").mock(
        return_value=httpx.Response(200, json={
            "compositeResponse": [],
        }),
    )
    _ok(await server.call_tool(
        "sf_composite", {
            "composite_request": [],
            "all_or_none": True,
        },
    ))
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["allOrNone"] is True
