"""Stripe payment integration — customers, invoices, subscriptions, payments."""

import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import STRIPE_API_KEY

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if not STRIPE_API_KEY:
        raise ToolError("STRIPE_API_KEY not configured.")
    if _client is None:
        _client = httpx.AsyncClient(
            base_url="https://api.stripe.com/v1",
            headers={"Authorization": f"Bearer {STRIPE_API_KEY}"},
            timeout=30.0,
        )
    return _client


def _success(sc: int, **kw) -> str:
    return json.dumps({"status": "success", "status_code": sc, **kw})


def _flatten(d: dict, prefix: str = "") -> dict:
    """Flatten nested dicts/lists into Stripe bracket notation."""
    items: dict = {}
    for k, v in d.items():
        key = f"{prefix}[{k}]" if prefix else k
        if v is None:
            continue
        if isinstance(v, dict):
            items.update(_flatten(v, key))
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    items.update(_flatten(item, f"{key}[{i}]"))
                else:
                    items[f"{key}[{i}]"] = str(item)
        elif isinstance(v, bool):
            items[key] = "true" if v else "false"
        else:
            items[key] = str(v)
    return items


async def _req(
    method: str, path: str, data: dict | None = None, params: dict | None = None
) -> dict | list:
    client = _get_client()
    kwargs: dict = {}
    if data is not None:
        kwargs["data"] = _flatten(data)
    if params:
        kwargs["params"] = params
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"Stripe request failed: {e}") from e
    if response.status_code == 429:
        raise ToolError("Stripe rate limit exceeded.")
    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
            msg = err.get("message", response.text)
            code = err.get("code", "")
        except Exception:
            msg, code = response.text, ""
        raise ToolError(f"Stripe error ({response.status_code}{f' {code}' if code else ''}): {msg}")
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def _list_result(data: dict) -> str:
    items = data.get("data", []) if isinstance(data, dict) else data
    has_more = data.get("has_more", False) if isinstance(data, dict) else False
    return _success(200, data=items, count=len(items), has_more=has_more)


def register_tools(mcp: FastMCP) -> None:
    if not STRIPE_API_KEY:
        logger.warning("STRIPE_API_KEY not set — Stripe tools will fail.")

    # === CUSTOMERS ===

    @mcp.tool()
    async def stripe_create_customer(
        email: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        description: str | None = None,
        metadata: dict | None = None,
        address: dict | None = None,
    ) -> str:
        """Create a Stripe customer.
        Args:
            email: Customer email
            name: Customer name
            phone: Phone number
            description: Description
            metadata: Key-value metadata
            address: Address dict (line1, city, state, postal_code, country)
        """
        d: dict = {}
        if email is not None:
            d["email"] = email
        if name is not None:
            d["name"] = name
        if phone is not None:
            d["phone"] = phone
        if description is not None:
            d["description"] = description
        if metadata is not None:
            d["metadata"] = metadata
        if address is not None:
            d["address"] = address
        return _success(200, data=await _req("POST", "/customers", data=d))

    @mcp.tool()
    async def stripe_get_customer(customer_id: str) -> str:
        """Get a Stripe customer.
        Args:
            customer_id: Customer ID (cus_xxx)
        """
        return _success(200, data=await _req("GET", f"/customers/{customer_id}"))

    @mcp.tool()
    async def stripe_update_customer(
        customer_id: str,
        email: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Update a Stripe customer.
        Args:
            customer_id: Customer ID
            email: New email
            name: New name
            phone: New phone
            metadata: Updated metadata
        """
        d: dict = {}
        if email is not None:
            d["email"] = email
        if name is not None:
            d["name"] = name
        if phone is not None:
            d["phone"] = phone
        if metadata is not None:
            d["metadata"] = metadata
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(200, data=await _req("POST", f"/customers/{customer_id}", data=d))

    @mcp.tool()
    async def stripe_delete_customer(customer_id: str) -> str:
        """Delete a Stripe customer.
        Args:
            customer_id: Customer ID
        """
        return _success(200, data=await _req("DELETE", f"/customers/{customer_id}"))

    @mcp.tool()
    async def stripe_list_customers(
        limit: int = 10,
        starting_after: str | None = None,
        email: str | None = None,
    ) -> str:
        """List Stripe customers.
        Args:
            limit: Max results (default 10, max 100)
            starting_after: Cursor (customer ID)
            email: Filter by email
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        if email is not None:
            p["email"] = email
        return _list_result(await _req("GET", "/customers", params=p))

    @mcp.tool()
    async def stripe_search_customers(query: str, limit: int = 10) -> str:
        """Search Stripe customers.
        Args:
            query: Stripe search query (e.g., email:'john@example.com')
            limit: Max results
        """
        p = {"query": query, "limit": str(limit)}
        return _list_result(await _req("GET", "/customers/search", params=p))

    # === PAYMENT INTENTS ===

    @mcp.tool()
    async def stripe_create_payment_intent(
        amount: int,
        currency: str,
        customer: str | None = None,
        description: str | None = None,
        payment_method: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Create a Stripe payment intent.
        Args:
            amount: Amount in smallest currency unit (e.g., cents)
            currency: Currency code (usd, eur, etc.)
            customer: Customer ID
            description: Description
            payment_method: Payment method ID
            metadata: Metadata
        """
        d: dict = {"amount": amount, "currency": currency}
        if customer is not None:
            d["customer"] = customer
        if description is not None:
            d["description"] = description
        if payment_method is not None:
            d["payment_method"] = payment_method
        if metadata is not None:
            d["metadata"] = metadata
        return _success(200, data=await _req("POST", "/payment_intents", data=d))

    @mcp.tool()
    async def stripe_get_payment_intent(payment_intent_id: str) -> str:
        """Get a Stripe payment intent.
        Args:
            payment_intent_id: Payment intent ID (pi_xxx)
        """
        return _success(200, data=await _req("GET", f"/payment_intents/{payment_intent_id}"))

    @mcp.tool()
    async def stripe_update_payment_intent(
        payment_intent_id: str,
        amount: int | None = None,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Update a Stripe payment intent.
        Args:
            payment_intent_id: Payment intent ID
            amount: New amount
            description: New description
            metadata: Updated metadata
        """
        d: dict = {}
        if amount is not None:
            d["amount"] = amount
        if description is not None:
            d["description"] = description
        if metadata is not None:
            d["metadata"] = metadata
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(
            200, data=await _req("POST", f"/payment_intents/{payment_intent_id}", data=d)
        )

    @mcp.tool()
    async def stripe_confirm_payment_intent(payment_intent_id: str) -> str:
        """Confirm a Stripe payment intent.
        Args:
            payment_intent_id: Payment intent ID
        """
        return _success(
            200, data=await _req("POST", f"/payment_intents/{payment_intent_id}/confirm")
        )

    @mcp.tool()
    async def stripe_cancel_payment_intent(payment_intent_id: str) -> str:
        """Cancel a Stripe payment intent.
        Args:
            payment_intent_id: Payment intent ID
        """
        return _success(
            200, data=await _req("POST", f"/payment_intents/{payment_intent_id}/cancel")
        )

    @mcp.tool()
    async def stripe_list_payment_intents(
        limit: int = 10,
        starting_after: str | None = None,
        customer: str | None = None,
    ) -> str:
        """List Stripe payment intents.
        Args:
            limit: Max results
            starting_after: Cursor
            customer: Filter by customer ID
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        if customer is not None:
            p["customer"] = customer
        return _list_result(await _req("GET", "/payment_intents", params=p))

    # === CHARGES ===

    @mcp.tool()
    async def stripe_create_charge(
        amount: int,
        currency: str,
        source: str | None = None,
        customer: str | None = None,
        description: str | None = None,
    ) -> str:
        """Create a Stripe charge.
        Args:
            amount: Amount in smallest unit
            currency: Currency code
            source: Source token or ID
            customer: Customer ID
            description: Description
        """
        d: dict = {"amount": amount, "currency": currency}
        if source is not None:
            d["source"] = source
        if customer is not None:
            d["customer"] = customer
        if description is not None:
            d["description"] = description
        return _success(200, data=await _req("POST", "/charges", data=d))

    @mcp.tool()
    async def stripe_get_charge(charge_id: str) -> str:
        """Get a Stripe charge.
        Args:
            charge_id: Charge ID (ch_xxx)
        """
        return _success(200, data=await _req("GET", f"/charges/{charge_id}"))

    @mcp.tool()
    async def stripe_update_charge(
        charge_id: str,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Update a Stripe charge.
        Args:
            charge_id: Charge ID
            description: New description
            metadata: Updated metadata
        """
        d: dict = {}
        if description is not None:
            d["description"] = description
        if metadata is not None:
            d["metadata"] = metadata
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(200, data=await _req("POST", f"/charges/{charge_id}", data=d))

    @mcp.tool()
    async def stripe_list_charges(
        limit: int = 10,
        starting_after: str | None = None,
        customer: str | None = None,
    ) -> str:
        """List Stripe charges.
        Args:
            limit: Max results
            starting_after: Cursor
            customer: Filter by customer
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        if customer is not None:
            p["customer"] = customer
        return _list_result(await _req("GET", "/charges", params=p))

    @mcp.tool()
    async def stripe_capture_charge(charge_id: str, amount: int | None = None) -> str:
        """Capture a previously authorized charge.
        Args:
            charge_id: Charge ID
            amount: Amount to capture (partial capture)
        """
        d: dict = {}
        if amount is not None:
            d["amount"] = amount
        return _success(
            200, data=await _req("POST", f"/charges/{charge_id}/capture", data=d or None)
        )

    # === INVOICES ===

    @mcp.tool()
    async def stripe_create_invoice(
        customer: str,
        description: str | None = None,
        metadata: dict | None = None,
        auto_advance: bool | None = None,
        collection_method: str | None = None,
    ) -> str:
        """Create a Stripe invoice.
        Args:
            customer: Customer ID
            description: Description
            metadata: Metadata
            auto_advance: Auto-finalize (default true)
            collection_method: charge_automatically or send_invoice
        """
        d: dict = {"customer": customer}
        if description is not None:
            d["description"] = description
        if metadata is not None:
            d["metadata"] = metadata
        if auto_advance is not None:
            d["auto_advance"] = auto_advance
        if collection_method is not None:
            d["collection_method"] = collection_method
        return _success(200, data=await _req("POST", "/invoices", data=d))

    @mcp.tool()
    async def stripe_get_invoice(invoice_id: str) -> str:
        """Get a Stripe invoice.
        Args:
            invoice_id: Invoice ID (in_xxx)
        """
        return _success(200, data=await _req("GET", f"/invoices/{invoice_id}"))

    @mcp.tool()
    async def stripe_update_invoice(
        invoice_id: str,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Update a Stripe invoice.
        Args:
            invoice_id: Invoice ID
            description: New description
            metadata: Updated metadata
        """
        d: dict = {}
        if description is not None:
            d["description"] = description
        if metadata is not None:
            d["metadata"] = metadata
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(200, data=await _req("POST", f"/invoices/{invoice_id}", data=d))

    @mcp.tool()
    async def stripe_finalize_invoice(invoice_id: str) -> str:
        """Finalize a draft invoice.
        Args:
            invoice_id: Invoice ID
        """
        return _success(200, data=await _req("POST", f"/invoices/{invoice_id}/finalize"))

    @mcp.tool()
    async def stripe_pay_invoice(invoice_id: str) -> str:
        """Pay an open invoice.
        Args:
            invoice_id: Invoice ID
        """
        return _success(200, data=await _req("POST", f"/invoices/{invoice_id}/pay"))

    @mcp.tool()
    async def stripe_void_invoice(invoice_id: str) -> str:
        """Void an invoice.
        Args:
            invoice_id: Invoice ID
        """
        return _success(200, data=await _req("POST", f"/invoices/{invoice_id}/void"))

    @mcp.tool()
    async def stripe_send_invoice(invoice_id: str) -> str:
        """Send an invoice to the customer via email.
        Args:
            invoice_id: Invoice ID
        """
        return _success(200, data=await _req("POST", f"/invoices/{invoice_id}/send"))

    @mcp.tool()
    async def stripe_list_invoices(
        limit: int = 10,
        starting_after: str | None = None,
        customer: str | None = None,
        status: str | None = None,
    ) -> str:
        """List Stripe invoices.
        Args:
            limit: Max results
            starting_after: Cursor
            customer: Filter by customer
            status: Filter (draft, open, paid, uncollectible, void)
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        if customer is not None:
            p["customer"] = customer
        if status:
            p["status"] = status
        return _list_result(await _req("GET", "/invoices", params=p))

    @mcp.tool()
    async def stripe_list_invoice_line_items(
        invoice_id: str,
        limit: int = 10,
    ) -> str:
        """List line items on an invoice.
        Args:
            invoice_id: Invoice ID
            limit: Max results
        """
        p = {"limit": str(limit)}
        return _list_result(await _req("GET", f"/invoices/{invoice_id}/lines", params=p))

    @mcp.tool()
    async def stripe_add_invoice_line_item(
        invoice_id: str,
        price: str | None = None,
        quantity: int | None = None,
        amount: int | None = None,
        description: str | None = None,
    ) -> str:
        """Add a line item to a draft invoice.
        Args:
            invoice_id: Invoice ID
            price: Price ID
            quantity: Quantity
            amount: Amount in cents (for one-off items)
            description: Description
        """
        d: dict = {}
        if price is not None:
            d["lines[0][price]"] = price
        if quantity is not None:
            d["lines[0][quantity]"] = str(quantity)
        if amount is not None:
            d["lines[0][amount]"] = str(amount)
        if description is not None:
            d["lines[0][description]"] = description
        if not d:
            raise ToolError("At least price or amount must be provided.")
        return _success(200, data=await _req("POST", f"/invoices/{invoice_id}/add_lines", data=d))

    # === INVOICE ITEMS ===

    @mcp.tool()
    async def stripe_create_invoice_item(
        customer: str,
        price: str | None = None,
        amount: int | None = None,
        currency: str | None = None,
        description: str | None = None,
        invoice: str | None = None,
    ) -> str:
        """Create an invoice item.
        Args:
            customer: Customer ID
            price: Price ID
            amount: Amount in cents
            currency: Currency (required with amount)
            description: Description
            invoice: Attach to specific invoice
        """
        d: dict = {"customer": customer}
        if price is not None:
            d["price"] = price
        if amount is not None:
            d["amount"] = amount
        if currency is not None:
            d["currency"] = currency
        if description is not None:
            d["description"] = description
        if invoice is not None:
            d["invoice"] = invoice
        return _success(200, data=await _req("POST", "/invoiceitems", data=d))

    @mcp.tool()
    async def stripe_get_invoice_item(invoice_item_id: str) -> str:
        """Get an invoice item.
        Args:
            invoice_item_id: Invoice item ID (ii_xxx)
        """
        return _success(200, data=await _req("GET", f"/invoiceitems/{invoice_item_id}"))

    @mcp.tool()
    async def stripe_update_invoice_item(
        invoice_item_id: str,
        amount: int | None = None,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Update an invoice item.
        Args:
            invoice_item_id: Invoice item ID
            amount: New amount
            description: New description
            metadata: Updated metadata
        """
        d: dict = {}
        if amount is not None:
            d["amount"] = amount
        if description is not None:
            d["description"] = description
        if metadata is not None:
            d["metadata"] = metadata
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(200, data=await _req("POST", f"/invoiceitems/{invoice_item_id}", data=d))

    @mcp.tool()
    async def stripe_delete_invoice_item(invoice_item_id: str) -> str:
        """Delete an invoice item.
        Args:
            invoice_item_id: Invoice item ID
        """
        return _success(200, data=await _req("DELETE", f"/invoiceitems/{invoice_item_id}"))

    @mcp.tool()
    async def stripe_list_invoice_items(
        limit: int = 10,
        starting_after: str | None = None,
        customer: str | None = None,
    ) -> str:
        """List invoice items.
        Args:
            limit: Max results
            starting_after: Cursor
            customer: Filter by customer
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        if customer is not None:
            p["customer"] = customer
        return _list_result(await _req("GET", "/invoiceitems", params=p))

    # === SUBSCRIPTIONS ===

    @mcp.tool()
    async def stripe_create_subscription(
        customer: str,
        items: list[dict],
        metadata: dict | None = None,
    ) -> str:
        """Create a Stripe subscription.
        Args:
            customer: Customer ID
            items: List of {price: "price_xxx", quantity: 1}
            metadata: Metadata
        """
        d: dict = {"customer": customer, "items": items}
        if metadata is not None:
            d["metadata"] = metadata
        return _success(200, data=await _req("POST", "/subscriptions", data=d))

    @mcp.tool()
    async def stripe_get_subscription(subscription_id: str) -> str:
        """Get a Stripe subscription.
        Args:
            subscription_id: Subscription ID (sub_xxx)
        """
        return _success(200, data=await _req("GET", f"/subscriptions/{subscription_id}"))

    @mcp.tool()
    async def stripe_update_subscription(
        subscription_id: str,
        metadata: dict | None = None,
        cancel_at_period_end: bool | None = None,
    ) -> str:
        """Update a Stripe subscription.
        Args:
            subscription_id: Subscription ID
            metadata: Updated metadata
            cancel_at_period_end: Cancel at end of period
        """
        d: dict = {}
        if metadata is not None:
            d["metadata"] = metadata
        if cancel_at_period_end is not None:
            d["cancel_at_period_end"] = cancel_at_period_end
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(200, data=await _req("POST", f"/subscriptions/{subscription_id}", data=d))

    @mcp.tool()
    async def stripe_cancel_subscription(subscription_id: str) -> str:
        """Cancel a Stripe subscription immediately.
        Args:
            subscription_id: Subscription ID
        """
        return _success(200, data=await _req("DELETE", f"/subscriptions/{subscription_id}"))

    @mcp.tool()
    async def stripe_list_subscriptions(
        limit: int = 10,
        starting_after: str | None = None,
        customer: str | None = None,
        status: str | None = None,
    ) -> str:
        """List Stripe subscriptions.
        Args:
            limit: Max results
            starting_after: Cursor
            customer: Filter by customer
            status: Filter (active, past_due, canceled, etc.)
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        if customer is not None:
            p["customer"] = customer
        if status:
            p["status"] = status
        return _list_result(await _req("GET", "/subscriptions", params=p))

    @mcp.tool()
    async def stripe_resume_subscription(subscription_id: str) -> str:
        """Resume a paused subscription.
        Args:
            subscription_id: Subscription ID
        """
        return _success(200, data=await _req("POST", f"/subscriptions/{subscription_id}/resume"))

    # === PRODUCTS ===

    @mcp.tool()
    async def stripe_create_product(
        name: str,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Create a Stripe product.
        Args:
            name: Product name
            description: Description
            metadata: Metadata
        """
        d: dict = {"name": name}
        if description is not None:
            d["description"] = description
        if metadata is not None:
            d["metadata"] = metadata
        return _success(200, data=await _req("POST", "/products", data=d))

    @mcp.tool()
    async def stripe_get_product(product_id: str) -> str:
        """Get a Stripe product.
        Args:
            product_id: Product ID (prod_xxx)
        """
        return _success(200, data=await _req("GET", f"/products/{product_id}"))

    @mcp.tool()
    async def stripe_update_product(
        product_id: str,
        name: str | None = None,
        description: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Update a Stripe product.
        Args:
            product_id: Product ID
            name: New name
            description: New description
            metadata: Updated metadata
        """
        d: dict = {}
        if name is not None:
            d["name"] = name
        if description is not None:
            d["description"] = description
        if metadata is not None:
            d["metadata"] = metadata
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(200, data=await _req("POST", f"/products/{product_id}", data=d))

    @mcp.tool()
    async def stripe_delete_product(product_id: str) -> str:
        """Delete a Stripe product.
        Args:
            product_id: Product ID
        """
        return _success(200, data=await _req("DELETE", f"/products/{product_id}"))

    @mcp.tool()
    async def stripe_list_products(
        limit: int = 10,
        starting_after: str | None = None,
    ) -> str:
        """List Stripe products.
        Args:
            limit: Max results
            starting_after: Cursor
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        return _list_result(await _req("GET", "/products", params=p))

    # === PRICES ===

    @mcp.tool()
    async def stripe_create_price(
        unit_amount: int,
        currency: str,
        product: str,
        recurring_interval: str | None = None,
    ) -> str:
        """Create a Stripe price.
        Args:
            unit_amount: Price in smallest unit (cents)
            currency: Currency code
            product: Product ID
            recurring_interval: month, year, week, day (for subscriptions)
        """
        d: dict = {"unit_amount": unit_amount, "currency": currency, "product": product}
        if recurring_interval is not None:
            d["recurring"] = {"interval": recurring_interval}
        return _success(200, data=await _req("POST", "/prices", data=d))

    @mcp.tool()
    async def stripe_get_price(price_id: str) -> str:
        """Get a Stripe price.
        Args:
            price_id: Price ID (price_xxx)
        """
        return _success(200, data=await _req("GET", f"/prices/{price_id}"))

    @mcp.tool()
    async def stripe_update_price(
        price_id: str,
        metadata: dict | None = None,
        active: bool | None = None,
    ) -> str:
        """Update a Stripe price.
        Args:
            price_id: Price ID
            metadata: Updated metadata
            active: Activate/deactivate
        """
        d: dict = {}
        if metadata is not None:
            d["metadata"] = metadata
        if active is not None:
            d["active"] = active
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(200, data=await _req("POST", f"/prices/{price_id}", data=d))

    @mcp.tool()
    async def stripe_list_prices(
        limit: int = 10,
        starting_after: str | None = None,
        product: str | None = None,
    ) -> str:
        """List Stripe prices.
        Args:
            limit: Max results
            starting_after: Cursor
            product: Filter by product
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        if product is not None:
            p["product"] = product
        return _list_result(await _req("GET", "/prices", params=p))

    # === PAYMENT METHODS ===

    @mcp.tool()
    async def stripe_create_payment_method(
        type: str,
        card: dict | None = None,
    ) -> str:
        """Create a Stripe payment method.
        Args:
            type: Type (card, us_bank_account, etc.)
            card: Card details (number, exp_month, exp_year, cvc)
        """
        d: dict = {"type": type}
        if card is not None:
            d["card"] = card
        return _success(200, data=await _req("POST", "/payment_methods", data=d))

    @mcp.tool()
    async def stripe_get_payment_method(payment_method_id: str) -> str:
        """Get a Stripe payment method.
        Args:
            payment_method_id: Payment method ID (pm_xxx)
        """
        return _success(200, data=await _req("GET", f"/payment_methods/{payment_method_id}"))

    @mcp.tool()
    async def stripe_list_payment_methods(
        customer: str,
        type: str = "card",
        limit: int = 10,
    ) -> str:
        """List payment methods for a customer.
        Args:
            customer: Customer ID
            type: Payment method type (default card)
            limit: Max results
        """
        p = {"customer": customer, "type": type, "limit": str(limit)}
        return _list_result(await _req("GET", "/payment_methods", params=p))

    @mcp.tool()
    async def stripe_attach_payment_method(
        payment_method_id: str,
        customer: str,
    ) -> str:
        """Attach a payment method to a customer.
        Args:
            payment_method_id: Payment method ID
            customer: Customer ID
        """
        return _success(
            200,
            data=await _req(
                "POST",
                f"/payment_methods/{payment_method_id}/attach",
                data={"customer": customer},
            ),
        )

    @mcp.tool()
    async def stripe_detach_payment_method(payment_method_id: str) -> str:
        """Detach a payment method from a customer.
        Args:
            payment_method_id: Payment method ID
        """
        return _success(
            200,
            data=await _req(
                "POST",
                f"/payment_methods/{payment_method_id}/detach",
            ),
        )

    # === REFUNDS ===

    @mcp.tool()
    async def stripe_create_refund(
        charge: str | None = None,
        payment_intent: str | None = None,
        amount: int | None = None,
        reason: str | None = None,
    ) -> str:
        """Create a refund.
        Args:
            charge: Charge ID (or use payment_intent)
            payment_intent: Payment intent ID (or use charge)
            amount: Partial refund amount (omit for full)
            reason: duplicate, fraudulent, requested_by_customer
        """
        if not charge and not payment_intent:
            raise ToolError("Either charge or payment_intent must be provided.")
        d: dict = {}
        if charge is not None:
            d["charge"] = charge
        if payment_intent is not None:
            d["payment_intent"] = payment_intent
        if amount is not None:
            d["amount"] = amount
        if reason is not None:
            d["reason"] = reason
        return _success(200, data=await _req("POST", "/refunds", data=d))

    @mcp.tool()
    async def stripe_get_refund(refund_id: str) -> str:
        """Get a refund.
        Args:
            refund_id: Refund ID (re_xxx)
        """
        return _success(200, data=await _req("GET", f"/refunds/{refund_id}"))

    @mcp.tool()
    async def stripe_update_refund(
        refund_id: str,
        metadata: dict | None = None,
    ) -> str:
        """Update a refund.
        Args:
            refund_id: Refund ID
            metadata: Updated metadata
        """
        d: dict = {}
        if metadata is not None:
            d["metadata"] = metadata
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(200, data=await _req("POST", f"/refunds/{refund_id}", data=d))

    @mcp.tool()
    async def stripe_list_refunds(
        limit: int = 10,
        starting_after: str | None = None,
        charge: str | None = None,
    ) -> str:
        """List refunds.
        Args:
            limit: Max results
            starting_after: Cursor
            charge: Filter by charge
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        if charge is not None:
            p["charge"] = charge
        return _list_result(await _req("GET", "/refunds", params=p))

    # === BALANCE ===

    @mcp.tool()
    async def stripe_get_balance() -> str:
        """Get Stripe account balance."""
        return _success(200, data=await _req("GET", "/balance"))

    @mcp.tool()
    async def stripe_list_balance_transactions(
        limit: int = 10,
        starting_after: str | None = None,
    ) -> str:
        """List balance transactions.
        Args:
            limit: Max results
            starting_after: Cursor
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        return _list_result(await _req("GET", "/balance_transactions", params=p))

    # === PAYOUTS ===

    @mcp.tool()
    async def stripe_create_payout(amount: int, currency: str) -> str:
        """Create a payout.
        Args:
            amount: Amount in smallest unit
            currency: Currency code
        """
        return _success(
            200, data=await _req("POST", "/payouts", data={"amount": amount, "currency": currency})
        )

    @mcp.tool()
    async def stripe_get_payout(payout_id: str) -> str:
        """Get a payout.
        Args:
            payout_id: Payout ID (po_xxx)
        """
        return _success(200, data=await _req("GET", f"/payouts/{payout_id}"))

    @mcp.tool()
    async def stripe_list_payouts(
        limit: int = 10,
        starting_after: str | None = None,
    ) -> str:
        """List payouts.
        Args:
            limit: Max results
            starting_after: Cursor
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        return _list_result(await _req("GET", "/payouts", params=p))

    # === COUPONS ===

    @mcp.tool()
    async def stripe_create_coupon(
        percent_off: float | None = None,
        amount_off: int | None = None,
        currency: str | None = None,
        duration: str = "once",
        duration_in_months: int | None = None,
        name: str | None = None,
    ) -> str:
        """Create a coupon.
        Args:
            percent_off: Percentage discount
            amount_off: Fixed amount discount (cents)
            currency: Currency (required with amount_off)
            duration: once, repeating, forever
            duration_in_months: Months (for repeating)
            name: Coupon name
        """
        d: dict = {"duration": duration}
        if percent_off is not None:
            d["percent_off"] = percent_off
        if amount_off is not None:
            d["amount_off"] = amount_off
        if currency is not None:
            d["currency"] = currency
        if duration_in_months is not None:
            d["duration_in_months"] = duration_in_months
        if name is not None:
            d["name"] = name
        return _success(200, data=await _req("POST", "/coupons", data=d))

    @mcp.tool()
    async def stripe_get_coupon(coupon_id: str) -> str:
        """Get a coupon.
        Args:
            coupon_id: Coupon ID
        """
        return _success(200, data=await _req("GET", f"/coupons/{coupon_id}"))

    @mcp.tool()
    async def stripe_update_coupon(
        coupon_id: str,
        name: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Update a coupon.
        Args:
            coupon_id: Coupon ID
            name: New name
            metadata: Updated metadata
        """
        d: dict = {}
        if name is not None:
            d["name"] = name
        if metadata is not None:
            d["metadata"] = metadata
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(200, data=await _req("POST", f"/coupons/{coupon_id}", data=d))

    @mcp.tool()
    async def stripe_delete_coupon(coupon_id: str) -> str:
        """Delete a coupon.
        Args:
            coupon_id: Coupon ID
        """
        return _success(200, data=await _req("DELETE", f"/coupons/{coupon_id}"))

    @mcp.tool()
    async def stripe_list_coupons(
        limit: int = 10,
        starting_after: str | None = None,
    ) -> str:
        """List coupons.
        Args:
            limit: Max results
            starting_after: Cursor
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        return _list_result(await _req("GET", "/coupons", params=p))

    # === PROMOTION CODES ===

    @mcp.tool()
    async def stripe_create_promotion_code(
        coupon: str,
        code: str | None = None,
        max_redemptions: int | None = None,
    ) -> str:
        """Create a promotion code.
        Args:
            coupon: Coupon ID
            code: Custom code string
            max_redemptions: Max uses
        """
        d: dict = {"coupon": coupon}
        if code is not None:
            d["code"] = code
        if max_redemptions is not None:
            d["max_redemptions"] = max_redemptions
        return _success(200, data=await _req("POST", "/promotion_codes", data=d))

    @mcp.tool()
    async def stripe_get_promotion_code(promo_code_id: str) -> str:
        """Get a promotion code.
        Args:
            promo_code_id: Promotion code ID (promo_xxx)
        """
        return _success(200, data=await _req("GET", f"/promotion_codes/{promo_code_id}"))

    @mcp.tool()
    async def stripe_update_promotion_code(
        promo_code_id: str,
        active: bool | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Update a promotion code.
        Args:
            promo_code_id: Promotion code ID
            active: Activate/deactivate
            metadata: Updated metadata
        """
        d: dict = {}
        if active is not None:
            d["active"] = active
        if metadata is not None:
            d["metadata"] = metadata
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(200, data=await _req("POST", f"/promotion_codes/{promo_code_id}", data=d))

    @mcp.tool()
    async def stripe_list_promotion_codes(
        limit: int = 10,
        starting_after: str | None = None,
        coupon: str | None = None,
    ) -> str:
        """List promotion codes.
        Args:
            limit: Max results
            starting_after: Cursor
            coupon: Filter by coupon
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        if coupon is not None:
            p["coupon"] = coupon
        return _list_result(await _req("GET", "/promotion_codes", params=p))

    # === EVENTS ===

    @mcp.tool()
    async def stripe_get_event(event_id: str) -> str:
        """Get a Stripe event.
        Args:
            event_id: Event ID (evt_xxx)
        """
        return _success(200, data=await _req("GET", f"/events/{event_id}"))

    @mcp.tool()
    async def stripe_list_events(
        limit: int = 10,
        starting_after: str | None = None,
        type: str | None = None,
    ) -> str:
        """List Stripe events.
        Args:
            limit: Max results
            starting_after: Cursor
            type: Filter by event type (e.g., invoice.paid)
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        if type is not None:
            p["type"] = type
        return _list_result(await _req("GET", "/events", params=p))

    # === WEBHOOK ENDPOINTS ===

    @mcp.tool()
    async def stripe_create_webhook_endpoint(
        url: str,
        enabled_events: list[str],
        description: str | None = None,
    ) -> str:
        """Create a webhook endpoint.
        Args:
            url: Webhook URL
            enabled_events: Event types to listen for
            description: Description
        """
        d: dict = {"url": url, "enabled_events": enabled_events}
        if description is not None:
            d["description"] = description
        return _success(200, data=await _req("POST", "/webhook_endpoints", data=d))

    @mcp.tool()
    async def stripe_get_webhook_endpoint(webhook_endpoint_id: str) -> str:
        """Get a webhook endpoint.
        Args:
            webhook_endpoint_id: Webhook endpoint ID (we_xxx)
        """
        return _success(200, data=await _req("GET", f"/webhook_endpoints/{webhook_endpoint_id}"))

    @mcp.tool()
    async def stripe_update_webhook_endpoint(
        webhook_endpoint_id: str,
        url: str | None = None,
        enabled_events: list[str] | None = None,
        description: str | None = None,
        disabled: bool | None = None,
    ) -> str:
        """Update a webhook endpoint.
        Args:
            webhook_endpoint_id: Webhook endpoint ID
            url: New URL
            enabled_events: New event types
            description: New description
            disabled: Disable the endpoint
        """
        d: dict = {}
        if url is not None:
            d["url"] = url
        if enabled_events is not None:
            d["enabled_events"] = enabled_events
        if description is not None:
            d["description"] = description
        if disabled is not None:
            d["disabled"] = disabled
        if not d:
            raise ToolError("At least one field to update must be provided.")
        return _success(
            200, data=await _req("POST", f"/webhook_endpoints/{webhook_endpoint_id}", data=d)
        )

    @mcp.tool()
    async def stripe_delete_webhook_endpoint(webhook_endpoint_id: str) -> str:
        """Delete a webhook endpoint.
        Args:
            webhook_endpoint_id: Webhook endpoint ID
        """
        return _success(200, data=await _req("DELETE", f"/webhook_endpoints/{webhook_endpoint_id}"))

    @mcp.tool()
    async def stripe_list_webhook_endpoints(
        limit: int = 10,
        starting_after: str | None = None,
    ) -> str:
        """List webhook endpoints.
        Args:
            limit: Max results
            starting_after: Cursor
        """
        p: dict = {"limit": str(limit)}
        if starting_after:
            p["starting_after"] = starting_after
        return _list_result(await _req("GET", "/webhook_endpoints", params=p))
