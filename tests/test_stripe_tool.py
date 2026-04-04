"""Tests for Stripe payment integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.stripe_tool import register_tools

BASE = "https://api.stripe.com/v1"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


def _ok(result) -> None:
    assert _r(result)["status"] == "success"


@pytest.fixture
def server():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.stripe_tool.STRIPE_API_KEY", "sk_test_xxx"), \
         patch("mcp_toolbox.tools.stripe_tool._client", None):
        register_tools(mcp)
        yield mcp


# --- Auth/Error ---

@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.stripe_tool.STRIPE_API_KEY", None), \
         patch("mcp_toolbox.tools.stripe_tool._client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="STRIPE_API_KEY"):
            await mcp.call_tool("stripe_list_customers", {})


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit(server):
    respx.get(f"{BASE}/customers").mock(
        return_value=httpx.Response(429),
    )
    with pytest.raises(Exception, match="rate limit"):
        await server.call_tool("stripe_list_customers", {})


@pytest.mark.asyncio
@respx.mock
async def test_api_error(server):
    respx.get(f"{BASE}/customers/cus_bad").mock(
        return_value=httpx.Response(
            404,
            json={"error": {"message": "No such customer", "code": "resource_missing"}},
        ),
    )
    with pytest.raises(Exception, match="No such customer"):
        await server.call_tool("stripe_get_customer", {"customer_id": "cus_bad"})


# --- Customers ---

@pytest.mark.asyncio
@respx.mock
async def test_create_customer(server):
    route = respx.post(f"{BASE}/customers").mock(
        return_value=httpx.Response(200, json={"id": "cus_1", "email": "a@b.com"}),
    )
    _ok(await server.call_tool("stripe_create_customer", {"email": "a@b.com"}))
    req = route.calls[0].request
    form = dict(httpx.QueryParams(req.content.decode()))
    assert form["email"] == "a@b.com"


@pytest.mark.asyncio
@respx.mock
async def test_get_customer(server):
    respx.get(f"{BASE}/customers/cus_1").mock(
        return_value=httpx.Response(200, json={"id": "cus_1"}),
    )
    _ok(await server.call_tool("stripe_get_customer", {"customer_id": "cus_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_customer(server):
    route = respx.post(f"{BASE}/customers/cus_1").mock(
        return_value=httpx.Response(200, json={"id": "cus_1", "name": "New"}),
    )
    _ok(await server.call_tool(
        "stripe_update_customer", {"customer_id": "cus_1", "name": "New"},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["name"] == "New"


@pytest.mark.asyncio
async def test_update_customer_no_fields(server):
    with pytest.raises(Exception, match="At least one field"):
        await server.call_tool("stripe_update_customer", {"customer_id": "cus_1"})


@pytest.mark.asyncio
@respx.mock
async def test_delete_customer(server):
    respx.delete(f"{BASE}/customers/cus_1").mock(
        return_value=httpx.Response(200, json={"id": "cus_1", "deleted": True}),
    )
    _ok(await server.call_tool("stripe_delete_customer", {"customer_id": "cus_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_list_customers(server):
    respx.get(f"{BASE}/customers").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "cus_1"}], "has_more": False}),
    )
    r = _r(await server.call_tool("stripe_list_customers", {}))
    assert r["status"] == "success"
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_search_customers(server):
    respx.get(f"{BASE}/customers/search").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool(
        "stripe_search_customers", {"query": "email:'x@y.com'"},
    ))


# --- Payment Intents ---

@pytest.mark.asyncio
@respx.mock
async def test_create_payment_intent(server):
    route = respx.post(f"{BASE}/payment_intents").mock(
        return_value=httpx.Response(200, json={"id": "pi_1", "amount": 1000}),
    )
    _ok(await server.call_tool(
        "stripe_create_payment_intent", {"amount": 1000, "currency": "usd"},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["amount"] == "1000"
    assert form["currency"] == "usd"


@pytest.mark.asyncio
@respx.mock
async def test_get_payment_intent(server):
    respx.get(f"{BASE}/payment_intents/pi_1").mock(
        return_value=httpx.Response(200, json={"id": "pi_1"}),
    )
    _ok(await server.call_tool(
        "stripe_get_payment_intent", {"payment_intent_id": "pi_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_payment_intent(server):
    route = respx.post(f"{BASE}/payment_intents/pi_1").mock(
        return_value=httpx.Response(200, json={"id": "pi_1"}),
    )
    _ok(await server.call_tool(
        "stripe_update_payment_intent",
        {"payment_intent_id": "pi_1", "amount": 2000},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["amount"] == "2000"


@pytest.mark.asyncio
@respx.mock
async def test_confirm_payment_intent(server):
    respx.post(f"{BASE}/payment_intents/pi_1/confirm").mock(
        return_value=httpx.Response(200, json={"id": "pi_1", "status": "succeeded"}),
    )
    _ok(await server.call_tool(
        "stripe_confirm_payment_intent", {"payment_intent_id": "pi_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_cancel_payment_intent(server):
    respx.post(f"{BASE}/payment_intents/pi_1/cancel").mock(
        return_value=httpx.Response(200, json={"id": "pi_1", "status": "canceled"}),
    )
    _ok(await server.call_tool(
        "stripe_cancel_payment_intent", {"payment_intent_id": "pi_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_payment_intents(server):
    respx.get(f"{BASE}/payment_intents").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_payment_intents", {}))


# --- Charges ---

@pytest.mark.asyncio
@respx.mock
async def test_create_charge(server):
    route = respx.post(f"{BASE}/charges").mock(
        return_value=httpx.Response(200, json={"id": "ch_1"}),
    )
    _ok(await server.call_tool(
        "stripe_create_charge", {"amount": 500, "currency": "usd"},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["amount"] == "500"
    assert form["currency"] == "usd"


@pytest.mark.asyncio
@respx.mock
async def test_get_charge(server):
    respx.get(f"{BASE}/charges/ch_1").mock(
        return_value=httpx.Response(200, json={"id": "ch_1"}),
    )
    _ok(await server.call_tool("stripe_get_charge", {"charge_id": "ch_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_charge(server):
    route = respx.post(f"{BASE}/charges/ch_1").mock(
        return_value=httpx.Response(200, json={"id": "ch_1"}),
    )
    _ok(await server.call_tool(
        "stripe_update_charge", {"charge_id": "ch_1", "description": "test"},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["description"] == "test"


@pytest.mark.asyncio
@respx.mock
async def test_list_charges(server):
    respx.get(f"{BASE}/charges").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_charges", {}))


@pytest.mark.asyncio
@respx.mock
async def test_capture_charge(server):
    respx.post(f"{BASE}/charges/ch_1/capture").mock(
        return_value=httpx.Response(200, json={"id": "ch_1", "captured": True}),
    )
    _ok(await server.call_tool("stripe_capture_charge", {"charge_id": "ch_1"}))


# --- Invoices ---

@pytest.mark.asyncio
@respx.mock
async def test_create_invoice(server):
    route = respx.post(f"{BASE}/invoices").mock(
        return_value=httpx.Response(200, json={"id": "in_1"}),
    )
    _ok(await server.call_tool("stripe_create_invoice", {"customer": "cus_1"}))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["customer"] == "cus_1"


@pytest.mark.asyncio
@respx.mock
async def test_get_invoice(server):
    respx.get(f"{BASE}/invoices/in_1").mock(
        return_value=httpx.Response(200, json={"id": "in_1"}),
    )
    _ok(await server.call_tool("stripe_get_invoice", {"invoice_id": "in_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_invoice(server):
    route = respx.post(f"{BASE}/invoices/in_1").mock(
        return_value=httpx.Response(200, json={"id": "in_1"}),
    )
    _ok(await server.call_tool(
        "stripe_update_invoice", {"invoice_id": "in_1", "description": "x"},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["description"] == "x"


@pytest.mark.asyncio
@respx.mock
async def test_finalize_invoice(server):
    respx.post(f"{BASE}/invoices/in_1/finalize").mock(
        return_value=httpx.Response(200, json={"id": "in_1"}),
    )
    _ok(await server.call_tool("stripe_finalize_invoice", {"invoice_id": "in_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_pay_invoice(server):
    respx.post(f"{BASE}/invoices/in_1/pay").mock(
        return_value=httpx.Response(200, json={"id": "in_1"}),
    )
    _ok(await server.call_tool("stripe_pay_invoice", {"invoice_id": "in_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_void_invoice(server):
    respx.post(f"{BASE}/invoices/in_1/void").mock(
        return_value=httpx.Response(200, json={"id": "in_1"}),
    )
    _ok(await server.call_tool("stripe_void_invoice", {"invoice_id": "in_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_send_invoice(server):
    respx.post(f"{BASE}/invoices/in_1/send").mock(
        return_value=httpx.Response(200, json={"id": "in_1"}),
    )
    _ok(await server.call_tool("stripe_send_invoice", {"invoice_id": "in_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_list_invoices(server):
    respx.get(f"{BASE}/invoices").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_invoices", {}))


@pytest.mark.asyncio
@respx.mock
async def test_list_invoice_line_items(server):
    respx.get(f"{BASE}/invoices/in_1/lines").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool(
        "stripe_list_invoice_line_items", {"invoice_id": "in_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_add_invoice_line_item(server):
    respx.post(f"{BASE}/invoices/in_1/add_lines").mock(
        return_value=httpx.Response(200, json={"id": "in_1"}),
    )
    _ok(await server.call_tool(
        "stripe_add_invoice_line_item", {"invoice_id": "in_1", "amount": 500},
    ))


@pytest.mark.asyncio
async def test_add_invoice_line_item_no_data(server):
    with pytest.raises(Exception, match="price or amount"):
        await server.call_tool(
            "stripe_add_invoice_line_item", {"invoice_id": "in_1"},
        )


# --- Invoice Items ---

@pytest.mark.asyncio
@respx.mock
async def test_create_invoice_item(server):
    respx.post(f"{BASE}/invoiceitems").mock(
        return_value=httpx.Response(200, json={"id": "ii_1"}),
    )
    _ok(await server.call_tool(
        "stripe_create_invoice_item", {"customer": "cus_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_invoice_item(server):
    respx.get(f"{BASE}/invoiceitems/ii_1").mock(
        return_value=httpx.Response(200, json={"id": "ii_1"}),
    )
    _ok(await server.call_tool(
        "stripe_get_invoice_item", {"invoice_item_id": "ii_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_invoice_item(server):
    respx.post(f"{BASE}/invoiceitems/ii_1").mock(
        return_value=httpx.Response(200, json={"id": "ii_1"}),
    )
    _ok(await server.call_tool(
        "stripe_update_invoice_item", {"invoice_item_id": "ii_1", "amount": 100},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_invoice_item(server):
    respx.delete(f"{BASE}/invoiceitems/ii_1").mock(
        return_value=httpx.Response(200, json={"id": "ii_1", "deleted": True}),
    )
    _ok(await server.call_tool(
        "stripe_delete_invoice_item", {"invoice_item_id": "ii_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_invoice_items(server):
    respx.get(f"{BASE}/invoiceitems").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_invoice_items", {}))


# --- Subscriptions ---

@pytest.mark.asyncio
@respx.mock
async def test_create_subscription(server):
    route = respx.post(f"{BASE}/subscriptions").mock(
        return_value=httpx.Response(200, json={"id": "sub_1"}),
    )
    _ok(await server.call_tool("stripe_create_subscription", {
        "customer": "cus_1", "items": [{"price": "price_1"}],
    }))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["customer"] == "cus_1"
    assert form["items[0][price]"] == "price_1"


@pytest.mark.asyncio
@respx.mock
async def test_get_subscription(server):
    respx.get(f"{BASE}/subscriptions/sub_1").mock(
        return_value=httpx.Response(200, json={"id": "sub_1"}),
    )
    _ok(await server.call_tool(
        "stripe_get_subscription", {"subscription_id": "sub_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_subscription(server):
    route = respx.post(f"{BASE}/subscriptions/sub_1").mock(
        return_value=httpx.Response(200, json={"id": "sub_1"}),
    )
    _ok(await server.call_tool("stripe_update_subscription", {
        "subscription_id": "sub_1", "cancel_at_period_end": True,
    }))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["cancel_at_period_end"] == "true"


@pytest.mark.asyncio
@respx.mock
async def test_cancel_subscription(server):
    respx.delete(f"{BASE}/subscriptions/sub_1").mock(
        return_value=httpx.Response(200, json={"id": "sub_1", "status": "canceled"}),
    )
    _ok(await server.call_tool(
        "stripe_cancel_subscription", {"subscription_id": "sub_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_subscriptions(server):
    respx.get(f"{BASE}/subscriptions").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_subscriptions", {}))


@pytest.mark.asyncio
@respx.mock
async def test_resume_subscription(server):
    respx.post(f"{BASE}/subscriptions/sub_1/resume").mock(
        return_value=httpx.Response(200, json={"id": "sub_1"}),
    )
    _ok(await server.call_tool(
        "stripe_resume_subscription", {"subscription_id": "sub_1"},
    ))


# --- Products ---

@pytest.mark.asyncio
@respx.mock
async def test_create_product(server):
    route = respx.post(f"{BASE}/products").mock(
        return_value=httpx.Response(200, json={"id": "prod_1"}),
    )
    _ok(await server.call_tool("stripe_create_product", {"name": "Widget"}))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["name"] == "Widget"


@pytest.mark.asyncio
@respx.mock
async def test_get_product(server):
    respx.get(f"{BASE}/products/prod_1").mock(
        return_value=httpx.Response(200, json={"id": "prod_1"}),
    )
    _ok(await server.call_tool("stripe_get_product", {"product_id": "prod_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_product(server):
    route = respx.post(f"{BASE}/products/prod_1").mock(
        return_value=httpx.Response(200, json={"id": "prod_1"}),
    )
    _ok(await server.call_tool(
        "stripe_update_product", {"product_id": "prod_1", "name": "New"},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["name"] == "New"


@pytest.mark.asyncio
@respx.mock
async def test_delete_product(server):
    respx.delete(f"{BASE}/products/prod_1").mock(
        return_value=httpx.Response(200, json={"id": "prod_1", "deleted": True}),
    )
    _ok(await server.call_tool("stripe_delete_product", {"product_id": "prod_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_list_products(server):
    respx.get(f"{BASE}/products").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_products", {}))


# --- Prices ---

@pytest.mark.asyncio
@respx.mock
async def test_create_price(server):
    route = respx.post(f"{BASE}/prices").mock(
        return_value=httpx.Response(200, json={"id": "price_1"}),
    )
    _ok(await server.call_tool("stripe_create_price", {
        "unit_amount": 1000, "currency": "usd", "product": "prod_1",
    }))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["unit_amount"] == "1000"
    assert form["currency"] == "usd"
    assert form["product"] == "prod_1"


@pytest.mark.asyncio
@respx.mock
async def test_get_price(server):
    respx.get(f"{BASE}/prices/price_1").mock(
        return_value=httpx.Response(200, json={"id": "price_1"}),
    )
    _ok(await server.call_tool("stripe_get_price", {"price_id": "price_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_price(server):
    route = respx.post(f"{BASE}/prices/price_1").mock(
        return_value=httpx.Response(200, json={"id": "price_1"}),
    )
    _ok(await server.call_tool(
        "stripe_update_price", {"price_id": "price_1", "active": False},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["active"] == "false"


@pytest.mark.asyncio
@respx.mock
async def test_list_prices(server):
    respx.get(f"{BASE}/prices").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_prices", {}))


# --- Payment Methods ---

@pytest.mark.asyncio
@respx.mock
async def test_create_payment_method(server):
    route = respx.post(f"{BASE}/payment_methods").mock(
        return_value=httpx.Response(200, json={"id": "pm_1"}),
    )
    _ok(await server.call_tool(
        "stripe_create_payment_method", {"type": "card"},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["type"] == "card"


@pytest.mark.asyncio
@respx.mock
async def test_get_payment_method(server):
    respx.get(f"{BASE}/payment_methods/pm_1").mock(
        return_value=httpx.Response(200, json={"id": "pm_1"}),
    )
    _ok(await server.call_tool(
        "stripe_get_payment_method", {"payment_method_id": "pm_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_payment_methods(server):
    respx.get(f"{BASE}/payment_methods").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool(
        "stripe_list_payment_methods", {"customer": "cus_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_attach_payment_method(server):
    route = respx.post(f"{BASE}/payment_methods/pm_1/attach").mock(
        return_value=httpx.Response(200, json={"id": "pm_1"}),
    )
    _ok(await server.call_tool(
        "stripe_attach_payment_method",
        {"payment_method_id": "pm_1", "customer": "cus_1"},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["customer"] == "cus_1"


@pytest.mark.asyncio
@respx.mock
async def test_detach_payment_method(server):
    respx.post(f"{BASE}/payment_methods/pm_1/detach").mock(
        return_value=httpx.Response(200, json={"id": "pm_1"}),
    )
    _ok(await server.call_tool(
        "stripe_detach_payment_method", {"payment_method_id": "pm_1"},
    ))


# --- Refunds ---

@pytest.mark.asyncio
async def test_create_refund_no_source(server):
    with pytest.raises(Exception, match="charge or payment_intent"):
        await server.call_tool("stripe_create_refund", {})


@pytest.mark.asyncio
@respx.mock
async def test_create_refund(server):
    route = respx.post(f"{BASE}/refunds").mock(
        return_value=httpx.Response(200, json={"id": "re_1"}),
    )
    _ok(await server.call_tool("stripe_create_refund", {"charge": "ch_1"}))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["charge"] == "ch_1"


@pytest.mark.asyncio
@respx.mock
async def test_get_refund(server):
    respx.get(f"{BASE}/refunds/re_1").mock(
        return_value=httpx.Response(200, json={"id": "re_1"}),
    )
    _ok(await server.call_tool("stripe_get_refund", {"refund_id": "re_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_refund(server):
    respx.post(f"{BASE}/refunds/re_1").mock(
        return_value=httpx.Response(200, json={"id": "re_1"}),
    )
    _ok(await server.call_tool(
        "stripe_update_refund", {"refund_id": "re_1", "metadata": {"k": "v"}},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_refunds(server):
    respx.get(f"{BASE}/refunds").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_refunds", {}))


# --- Balance ---

@pytest.mark.asyncio
@respx.mock
async def test_get_balance(server):
    respx.get(f"{BASE}/balance").mock(
        return_value=httpx.Response(200, json={"available": []}),
    )
    _ok(await server.call_tool("stripe_get_balance", {}))


@pytest.mark.asyncio
@respx.mock
async def test_list_balance_transactions(server):
    respx.get(f"{BASE}/balance_transactions").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_balance_transactions", {}))


# --- Payouts ---

@pytest.mark.asyncio
@respx.mock
async def test_create_payout(server):
    route = respx.post(f"{BASE}/payouts").mock(
        return_value=httpx.Response(200, json={"id": "po_1"}),
    )
    _ok(await server.call_tool(
        "stripe_create_payout", {"amount": 1000, "currency": "usd"},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["amount"] == "1000"
    assert form["currency"] == "usd"


@pytest.mark.asyncio
@respx.mock
async def test_get_payout(server):
    respx.get(f"{BASE}/payouts/po_1").mock(
        return_value=httpx.Response(200, json={"id": "po_1"}),
    )
    _ok(await server.call_tool("stripe_get_payout", {"payout_id": "po_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_list_payouts(server):
    respx.get(f"{BASE}/payouts").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_payouts", {}))


# --- Coupons ---

@pytest.mark.asyncio
@respx.mock
async def test_create_coupon(server):
    route = respx.post(f"{BASE}/coupons").mock(
        return_value=httpx.Response(200, json={"id": "coup_1"}),
    )
    _ok(await server.call_tool(
        "stripe_create_coupon", {"percent_off": 25.0},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["percent_off"] == "25.0"
    assert form["duration"] == "once"


@pytest.mark.asyncio
@respx.mock
async def test_get_coupon(server):
    respx.get(f"{BASE}/coupons/coup_1").mock(
        return_value=httpx.Response(200, json={"id": "coup_1"}),
    )
    _ok(await server.call_tool("stripe_get_coupon", {"coupon_id": "coup_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_update_coupon(server):
    respx.post(f"{BASE}/coupons/coup_1").mock(
        return_value=httpx.Response(200, json={"id": "coup_1"}),
    )
    _ok(await server.call_tool(
        "stripe_update_coupon", {"coupon_id": "coup_1", "name": "New"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_coupon(server):
    respx.delete(f"{BASE}/coupons/coup_1").mock(
        return_value=httpx.Response(200, json={"id": "coup_1", "deleted": True}),
    )
    _ok(await server.call_tool("stripe_delete_coupon", {"coupon_id": "coup_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_list_coupons(server):
    respx.get(f"{BASE}/coupons").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_coupons", {}))


# --- Promotion Codes ---

@pytest.mark.asyncio
@respx.mock
async def test_create_promotion_code(server):
    route = respx.post(f"{BASE}/promotion_codes").mock(
        return_value=httpx.Response(200, json={"id": "promo_1"}),
    )
    _ok(await server.call_tool(
        "stripe_create_promotion_code", {"coupon": "coup_1"},
    ))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["coupon"] == "coup_1"


@pytest.mark.asyncio
@respx.mock
async def test_get_promotion_code(server):
    respx.get(f"{BASE}/promotion_codes/promo_1").mock(
        return_value=httpx.Response(200, json={"id": "promo_1"}),
    )
    _ok(await server.call_tool(
        "stripe_get_promotion_code", {"promo_code_id": "promo_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_promotion_code(server):
    respx.post(f"{BASE}/promotion_codes/promo_1").mock(
        return_value=httpx.Response(200, json={"id": "promo_1"}),
    )
    _ok(await server.call_tool(
        "stripe_update_promotion_code",
        {"promo_code_id": "promo_1", "active": False},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_promotion_codes(server):
    respx.get(f"{BASE}/promotion_codes").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_promotion_codes", {}))


# --- Events ---

@pytest.mark.asyncio
@respx.mock
async def test_get_event(server):
    respx.get(f"{BASE}/events/evt_1").mock(
        return_value=httpx.Response(200, json={"id": "evt_1"}),
    )
    _ok(await server.call_tool("stripe_get_event", {"event_id": "evt_1"}))


@pytest.mark.asyncio
@respx.mock
async def test_list_events(server):
    respx.get(f"{BASE}/events").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_events", {}))


# --- Webhook Endpoints ---

@pytest.mark.asyncio
@respx.mock
async def test_create_webhook_endpoint(server):
    route = respx.post(f"{BASE}/webhook_endpoints").mock(
        return_value=httpx.Response(200, json={"id": "we_1"}),
    )
    _ok(await server.call_tool("stripe_create_webhook_endpoint", {
        "url": "https://example.com/wh", "enabled_events": ["invoice.paid"],
    }))
    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form["url"] == "https://example.com/wh"
    assert form["enabled_events[0]"] == "invoice.paid"


@pytest.mark.asyncio
@respx.mock
async def test_get_webhook_endpoint(server):
    respx.get(f"{BASE}/webhook_endpoints/we_1").mock(
        return_value=httpx.Response(200, json={"id": "we_1"}),
    )
    _ok(await server.call_tool(
        "stripe_get_webhook_endpoint", {"webhook_endpoint_id": "we_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_webhook_endpoint(server):
    respx.post(f"{BASE}/webhook_endpoints/we_1").mock(
        return_value=httpx.Response(200, json={"id": "we_1"}),
    )
    _ok(await server.call_tool("stripe_update_webhook_endpoint", {
        "webhook_endpoint_id": "we_1", "url": "https://example.com/wh2",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_delete_webhook_endpoint(server):
    respx.delete(f"{BASE}/webhook_endpoints/we_1").mock(
        return_value=httpx.Response(200, json={"id": "we_1", "deleted": True}),
    )
    _ok(await server.call_tool(
        "stripe_delete_webhook_endpoint", {"webhook_endpoint_id": "we_1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_webhook_endpoints(server):
    respx.get(f"{BASE}/webhook_endpoints").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False}),
    )
    _ok(await server.call_tool("stripe_list_webhook_endpoints", {}))


# --- Flatten helper ---

def test_flatten_nested():
    from mcp_toolbox.tools.stripe_tool import _flatten
    result = _flatten({"metadata": {"key": "val"}, "active": True})
    assert result == {"metadata[key]": "val", "active": "true"}


def test_flatten_list():
    from mcp_toolbox.tools.stripe_tool import _flatten
    result = _flatten({"items": [{"price": "p_1"}]})
    assert result == {"items[0][price]": "p_1"}


def test_flatten_skips_none():
    from mcp_toolbox.tools.stripe_tool import _flatten
    result = _flatten({"a": "b", "c": None})
    assert result == {"a": "b"}
