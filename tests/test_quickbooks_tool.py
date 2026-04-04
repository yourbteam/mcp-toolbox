"""Tests for QuickBooks Online tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.quickbooks_tool import register_tools

BASE = "https://quickbooks.api.intuit.com/v3/company/realm123"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


def _ok(result) -> None:
    assert _r(result)["status"] == "success"


@pytest.fixture
def server():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.quickbooks_tool.QB_CLIENT_ID", "cid"), \
         patch("mcp_toolbox.tools.quickbooks_tool.QB_CLIENT_SECRET", "cs"), \
         patch("mcp_toolbox.tools.quickbooks_tool.QB_REFRESH_TOKEN", "rt"), \
         patch("mcp_toolbox.tools.quickbooks_tool.QB_REALM_ID", "realm123"), \
         patch("mcp_toolbox.tools.quickbooks_tool.QB_ENVIRONMENT", "production"), \
         patch("mcp_toolbox.tools.quickbooks_tool._client", None), \
         patch("mcp_toolbox.tools.quickbooks_tool._access_token", "tok"), \
         patch("mcp_toolbox.tools.quickbooks_tool._token_expires_at", 9999999999.0):
        register_tools(mcp)
        yield mcp


# --- Auth/Error ---

@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.quickbooks_tool.QB_CLIENT_ID", None), \
         patch("mcp_toolbox.tools.quickbooks_tool.QB_CLIENT_SECRET", None), \
         patch("mcp_toolbox.tools.quickbooks_tool.QB_REFRESH_TOKEN", None), \
         patch("mcp_toolbox.tools.quickbooks_tool.QB_REALM_ID", None), \
         patch("mcp_toolbox.tools.quickbooks_tool._client", None), \
         patch("mcp_toolbox.tools.quickbooks_tool._access_token", None), \
         patch("mcp_toolbox.tools.quickbooks_tool._token_expires_at", 0.0):
        register_tools(mcp)
        with pytest.raises(Exception, match="QuickBooks not configured"):
            await mcp.call_tool("qb_query_customers", {})


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit(server):
    respx.get(f"{BASE}/customer/1").mock(
        return_value=httpx.Response(429),
    )
    with pytest.raises(Exception, match="rate limit"):
        await server.call_tool("qb_get_customer", {"customer_id": "1"})


@pytest.mark.asyncio
@respx.mock
async def test_api_error(server):
    respx.get(f"{BASE}/customer/bad").mock(
        return_value=httpx.Response(400, json={
            "Fault": {"Error": [{"Message": "Invalid Id", "Detail": "bad"}]},
        }),
    )
    with pytest.raises(Exception, match="Invalid Id"):
        await server.call_tool("qb_get_customer", {"customer_id": "bad"})


# --- Customers ---

@pytest.mark.asyncio
@respx.mock
async def test_create_customer(server):
    respx.post(f"{BASE}/customer").mock(
        return_value=httpx.Response(200, json={"Customer": {"Id": "1"}}),
    )
    _ok(await server.call_tool(
        "qb_create_customer", {"display_name": "Test"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_customer(server):
    respx.get(f"{BASE}/customer/1").mock(
        return_value=httpx.Response(200, json={"Customer": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_get_customer", {"customer_id": "1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_customer(server):
    respx.post(f"{BASE}/customer").mock(
        return_value=httpx.Response(200, json={"Customer": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_update_customer", {
        "customer_id": "1", "sync_token": "0", "display_name": "New",
    }))


@pytest.mark.asyncio
async def test_update_customer_no_fields(server):
    with pytest.raises(Exception, match="At least one field"):
        await server.call_tool("qb_update_customer", {
            "customer_id": "1", "sync_token": "0",
        })


@pytest.mark.asyncio
@respx.mock
async def test_query_customers(server):
    respx.get(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json={
            "QueryResponse": {"Customer": [{"Id": "1"}], "totalCount": 1},
        }),
    )
    r = _r(await server.call_tool("qb_query_customers", {}))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_delete_customer(server):
    respx.post(f"{BASE}/customer").mock(
        return_value=httpx.Response(200, json={
            "Customer": {"Id": "1", "Active": False},
        }),
    )
    _ok(await server.call_tool("qb_delete_customer", {
        "customer_id": "1", "sync_token": "0",
    }))


# --- Invoices ---

@pytest.mark.asyncio
@respx.mock
async def test_create_invoice(server):
    respx.post(f"{BASE}/invoice").mock(
        return_value=httpx.Response(200, json={"Invoice": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_create_invoice", {
        "customer_id": "1",
        "line_items": [{"DetailType": "SalesItemLineDetail", "Amount": 100}],
    }))


@pytest.mark.asyncio
@respx.mock
async def test_get_invoice(server):
    respx.get(f"{BASE}/invoice/1").mock(
        return_value=httpx.Response(200, json={"Invoice": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_get_invoice", {"invoice_id": "1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_invoice(server):
    respx.post(f"{BASE}/invoice").mock(
        return_value=httpx.Response(200, json={"Invoice": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_update_invoice", {
        "invoice_id": "1", "sync_token": "0", "due_date": "2026-05-01",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_query_invoices(server):
    respx.get(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json={
            "QueryResponse": {"Invoice": [], "totalCount": 0},
        }),
    )
    _ok(await server.call_tool("qb_query_invoices", {}))


@pytest.mark.asyncio
@respx.mock
async def test_send_invoice(server):
    respx.post(f"{BASE}/invoice/1/send").mock(
        return_value=httpx.Response(200, json={"Invoice": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_send_invoice", {"invoice_id": "1"}))


@pytest.mark.asyncio
@respx.mock
async def test_void_invoice(server):
    respx.post(f"{BASE}/invoice").mock(
        return_value=httpx.Response(200, json={"Invoice": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_void_invoice", {
        "invoice_id": "1", "sync_token": "0",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_delete_invoice(server):
    respx.post(f"{BASE}/invoice").mock(
        return_value=httpx.Response(200, json={"status": "Deleted"}),
    )
    _ok(await server.call_tool("qb_delete_invoice", {
        "invoice_id": "1", "sync_token": "0",
    }))


# --- Payments ---

@pytest.mark.asyncio
@respx.mock
async def test_create_payment(server):
    respx.post(f"{BASE}/payment").mock(
        return_value=httpx.Response(200, json={"Payment": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_create_payment", {
        "customer_id": "1", "total_amt": 150.0,
    }))


@pytest.mark.asyncio
@respx.mock
async def test_get_payment(server):
    respx.get(f"{BASE}/payment/1").mock(
        return_value=httpx.Response(200, json={"Payment": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_get_payment", {"payment_id": "1"}))


@pytest.mark.asyncio
@respx.mock
async def test_query_payments(server):
    respx.get(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json={
            "QueryResponse": {"Payment": [], "totalCount": 0},
        }),
    )
    _ok(await server.call_tool("qb_query_payments", {}))


@pytest.mark.asyncio
@respx.mock
async def test_void_payment(server):
    respx.post(f"{BASE}/payment").mock(
        return_value=httpx.Response(200, json={"Payment": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_void_payment", {
        "payment_id": "1", "sync_token": "0",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_delete_payment(server):
    respx.post(f"{BASE}/payment").mock(
        return_value=httpx.Response(200, json={"status": "Deleted"}),
    )
    _ok(await server.call_tool("qb_delete_payment", {
        "payment_id": "1", "sync_token": "0",
    }))


# --- Items ---

@pytest.mark.asyncio
@respx.mock
async def test_create_item(server):
    respx.post(f"{BASE}/item").mock(
        return_value=httpx.Response(200, json={"Item": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_create_item", {
        "name": "Service", "income_account_ref": "1",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_get_item(server):
    respx.get(f"{BASE}/item/1").mock(
        return_value=httpx.Response(200, json={"Item": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_get_item", {"item_id": "1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_item(server):
    respx.post(f"{BASE}/item").mock(
        return_value=httpx.Response(200, json={"Item": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_update_item", {
        "item_id": "1", "sync_token": "0", "name": "Updated",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_query_items(server):
    respx.get(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json={
            "QueryResponse": {"Item": [], "totalCount": 0},
        }),
    )
    _ok(await server.call_tool("qb_query_items", {}))


# --- Accounts ---

@pytest.mark.asyncio
@respx.mock
async def test_get_account(server):
    respx.get(f"{BASE}/account/1").mock(
        return_value=httpx.Response(200, json={"Account": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_get_account", {"account_id": "1"}))


@pytest.mark.asyncio
@respx.mock
async def test_query_accounts(server):
    respx.get(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json={
            "QueryResponse": {"Account": [], "totalCount": 0},
        }),
    )
    _ok(await server.call_tool("qb_query_accounts", {}))


# --- Bills ---

@pytest.mark.asyncio
@respx.mock
async def test_create_bill(server):
    respx.post(f"{BASE}/bill").mock(
        return_value=httpx.Response(200, json={"Bill": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_create_bill", {
        "vendor_id": "1",
        "line_items": [{"DetailType": "AccountBasedExpenseLineDetail", "Amount": 200}],
    }))


@pytest.mark.asyncio
@respx.mock
async def test_get_bill(server):
    respx.get(f"{BASE}/bill/1").mock(
        return_value=httpx.Response(200, json={"Bill": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_get_bill", {"bill_id": "1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_bill(server):
    respx.post(f"{BASE}/bill").mock(
        return_value=httpx.Response(200, json={"Bill": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_update_bill", {
        "bill_id": "1", "sync_token": "0", "due_date": "2026-06-01",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_query_bills(server):
    respx.get(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json={
            "QueryResponse": {"Bill": [], "totalCount": 0},
        }),
    )
    _ok(await server.call_tool("qb_query_bills", {}))


# --- Vendors ---

@pytest.mark.asyncio
@respx.mock
async def test_create_vendor(server):
    respx.post(f"{BASE}/vendor").mock(
        return_value=httpx.Response(200, json={"Vendor": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_create_vendor", {
        "display_name": "Acme",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_get_vendor(server):
    respx.get(f"{BASE}/vendor/1").mock(
        return_value=httpx.Response(200, json={"Vendor": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_get_vendor", {"vendor_id": "1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_vendor(server):
    respx.post(f"{BASE}/vendor").mock(
        return_value=httpx.Response(200, json={"Vendor": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_update_vendor", {
        "vendor_id": "1", "sync_token": "0", "display_name": "New",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_query_vendors(server):
    respx.get(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json={
            "QueryResponse": {"Vendor": [], "totalCount": 0},
        }),
    )
    _ok(await server.call_tool("qb_query_vendors", {}))


# --- Estimates ---

@pytest.mark.asyncio
@respx.mock
async def test_create_estimate(server):
    respx.post(f"{BASE}/estimate").mock(
        return_value=httpx.Response(200, json={"Estimate": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_create_estimate", {
        "customer_id": "1",
        "line_items": [{"DetailType": "SalesItemLineDetail", "Amount": 50}],
    }))


@pytest.mark.asyncio
@respx.mock
async def test_get_estimate(server):
    respx.get(f"{BASE}/estimate/1").mock(
        return_value=httpx.Response(200, json={"Estimate": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_get_estimate", {"estimate_id": "1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_estimate(server):
    respx.post(f"{BASE}/estimate").mock(
        return_value=httpx.Response(200, json={"Estimate": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_update_estimate", {
        "estimate_id": "1", "sync_token": "0", "txn_status": "Accepted",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_query_estimates(server):
    respx.get(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json={
            "QueryResponse": {"Estimate": [], "totalCount": 0},
        }),
    )
    _ok(await server.call_tool("qb_query_estimates", {}))


@pytest.mark.asyncio
@respx.mock
async def test_send_estimate(server):
    respx.post(f"{BASE}/estimate/1/send").mock(
        return_value=httpx.Response(200, json={"Estimate": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_send_estimate", {"estimate_id": "1"}))


# --- Credit Memos ---

@pytest.mark.asyncio
@respx.mock
async def test_create_credit_memo(server):
    respx.post(f"{BASE}/creditmemo").mock(
        return_value=httpx.Response(200, json={"CreditMemo": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_create_credit_memo", {
        "customer_id": "1",
        "line_items": [{"DetailType": "SalesItemLineDetail", "Amount": 25}],
    }))


@pytest.mark.asyncio
@respx.mock
async def test_get_credit_memo(server):
    respx.get(f"{BASE}/creditmemo/1").mock(
        return_value=httpx.Response(200, json={"CreditMemo": {"Id": "1"}}),
    )
    _ok(await server.call_tool(
        "qb_get_credit_memo", {"credit_memo_id": "1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_query_credit_memos(server):
    respx.get(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json={
            "QueryResponse": {"CreditMemo": [], "totalCount": 0},
        }),
    )
    _ok(await server.call_tool("qb_query_credit_memos", {}))


# --- Purchases ---

@pytest.mark.asyncio
@respx.mock
async def test_create_purchase(server):
    respx.post(f"{BASE}/purchase").mock(
        return_value=httpx.Response(200, json={"Purchase": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_create_purchase", {
        "account_ref": "35", "payment_type": "Cash",
        "line_items": [{"DetailType": "AccountBasedExpenseLineDetail", "Amount": 25}],
    }))


@pytest.mark.asyncio
@respx.mock
async def test_get_purchase(server):
    respx.get(f"{BASE}/purchase/1").mock(
        return_value=httpx.Response(200, json={"Purchase": {"Id": "1"}}),
    )
    _ok(await server.call_tool("qb_get_purchase", {"purchase_id": "1"}))


@pytest.mark.asyncio
@respx.mock
async def test_query_purchases(server):
    respx.get(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json={
            "QueryResponse": {"Purchase": [], "totalCount": 0},
        }),
    )
    _ok(await server.call_tool("qb_query_purchases", {}))


# --- Reports ---

@pytest.mark.asyncio
@respx.mock
async def test_report_profit_and_loss(server):
    respx.get(f"{BASE}/reports/ProfitAndLoss").mock(
        return_value=httpx.Response(200, json={"Header": {}, "Rows": {}}),
    )
    _ok(await server.call_tool("qb_report_profit_and_loss", {}))


@pytest.mark.asyncio
@respx.mock
async def test_report_balance_sheet(server):
    respx.get(f"{BASE}/reports/BalanceSheet").mock(
        return_value=httpx.Response(200, json={"Header": {}, "Rows": {}}),
    )
    _ok(await server.call_tool("qb_report_balance_sheet", {}))


@pytest.mark.asyncio
@respx.mock
async def test_report_ar_aging(server):
    respx.get(f"{BASE}/reports/AgedReceivables").mock(
        return_value=httpx.Response(200, json={"Header": {}, "Rows": {}}),
    )
    _ok(await server.call_tool(
        "qb_report_accounts_receivable_aging", {},
    ))


# --- Company Info ---

@pytest.mark.asyncio
@respx.mock
async def test_get_company_info(server):
    respx.get(f"{BASE}/companyinfo/realm123").mock(
        return_value=httpx.Response(200, json={
            "CompanyInfo": {"CompanyName": "Test Co"},
        }),
    )
    _ok(await server.call_tool("qb_get_company_info", {}))
