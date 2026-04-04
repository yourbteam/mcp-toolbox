"""QuickBooks Online integration — customers, invoices, payments, items, reports."""

import asyncio
import base64
import json
import logging
import time

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import (
    QB_CLIENT_ID,
    QB_CLIENT_SECRET,
    QB_ENVIRONMENT,
    QB_REALM_ID,
    QB_REFRESH_TOKEN,
)

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_access_token: str | None = None
_token_expires_at: float = 0.0
_current_refresh_token: str | None = None
_token_lock: asyncio.Lock | None = None


def _check_config() -> None:
    if not all([QB_CLIENT_ID, QB_CLIENT_SECRET, QB_REFRESH_TOKEN, QB_REALM_ID]):
        raise ToolError(
            "QuickBooks not configured. Set QB_CLIENT_ID, QB_CLIENT_SECRET, "
            "QB_REFRESH_TOKEN, and QB_REALM_ID."
        )


def _get_base_url() -> str:
    if QB_ENVIRONMENT == "sandbox":
        return (
            f"https://sandbox-quickbooks.api.intuit.com"
            f"/v3/company/{QB_REALM_ID}"
        )
    return f"https://quickbooks.api.intuit.com/v3/company/{QB_REALM_ID}"


async def _get_token() -> str:
    global _access_token, _token_expires_at, _current_refresh_token, _token_lock
    _check_config()
    if _token_lock is None:
        _token_lock = asyncio.Lock()
    async with _token_lock:
        if _access_token and time.time() < _token_expires_at - 60:
            return _access_token
        if _current_refresh_token is None:
            _current_refresh_token = QB_REFRESH_TOKEN
        creds = base64.b64encode(
            f"{QB_CLIENT_ID}:{QB_CLIENT_SECRET}".encode()
        ).decode()
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
                headers={
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": _current_refresh_token,
                },
                timeout=30.0,
            )
        if resp.status_code != 200:
            raise ToolError(
                f"QBO token refresh failed ({resp.status_code}): {resp.text}"
            )
        data = resp.json()
        _access_token = data["access_token"]
        _token_expires_at = time.time() + data.get("expires_in", 3600)
        new_rt = data.get("refresh_token")
        if new_rt:
            _current_refresh_token = new_rt
            logger.info("QBO refresh token rotated (in-memory only).")
        return _access_token


def _get_client() -> httpx.AsyncClient:
    global _client
    _check_config()
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=_get_base_url(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    return _client


def _success(sc: int, **kw) -> str:
    return json.dumps({"status": "success", "status_code": sc, **kw})


async def _req(
    method: str, path: str, json_body: dict | None = None,
    params: dict | None = None,
) -> dict:
    token = await _get_token()
    client = _get_client()
    kwargs: dict = {"headers": {"Authorization": f"Bearer {token}"}}
    if json_body is not None:
        kwargs["json"] = json_body
    p = dict(params) if params else {}
    p["minorversion"] = "75"
    kwargs["params"] = p
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"QuickBooks request failed: {e}") from e
    if response.status_code == 429:
        raise ToolError("QuickBooks rate limit exceeded.")
    if response.status_code >= 400:
        try:
            fault = response.json().get("Fault", {})
            errors = fault.get("Error", [])
            msg = "; ".join(
                e.get("Message", "") + (f" — {e.get('Detail', '')}" if e.get("Detail") else "")
                for e in errors
            ) or response.text
        except Exception:
            msg = response.text
        raise ToolError(f"QuickBooks error ({response.status_code}): {msg}")
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


async def _query(
    entity: str, where: str | None, order_by: str | None,
    start_position: int, max_results: int,
) -> str:
    q = f"SELECT * FROM {entity}"
    if where:
        q += f" WHERE {where}"
    if order_by:
        q += f" ORDER BY {order_by}"
    q += f" STARTPOSITION {start_position} MAXRESULTS {max_results}"
    data = await _req("GET", "/query", params={"query": q})
    resp = data.get("QueryResponse", {})
    entities = resp.get(entity, [])
    count = resp.get("totalCount", len(entities))
    return _success(
        200, data=entities, count=count,
        start_position=start_position, max_results=max_results,
    )


def register_tools(mcp: FastMCP) -> None:
    if not all([QB_CLIENT_ID, QB_CLIENT_SECRET, QB_REFRESH_TOKEN, QB_REALM_ID]):
        logger.warning(
            "QuickBooks credentials not set — QB tools will fail."
        )

    # === TIER 1: CUSTOMERS ===

    @mcp.tool()
    async def qb_create_customer(
        display_name: str,
        given_name: str | None = None,
        family_name: str | None = None,
        company_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        bill_address: dict | None = None,
        ship_address: dict | None = None,
        notes: str | None = None,
        taxable: bool | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Create a QuickBooks customer.
        Args:
            display_name: Customer display name (unique)
            given_name: First name
            family_name: Last name
            company_name: Company name
            email: Primary email
            phone: Primary phone
            bill_address: Billing address dict
            ship_address: Shipping address dict
            notes: Free-form notes
            taxable: Whether customer is taxable
            extra_fields: Additional QBO fields
        """
        body: dict = {"DisplayName": display_name}
        if given_name is not None:
            body["GivenName"] = given_name
        if family_name is not None:
            body["FamilyName"] = family_name
        if company_name is not None:
            body["CompanyName"] = company_name
        if email is not None:
            body["PrimaryEmailAddr"] = {"Address": email}
        if phone is not None:
            body["PrimaryPhone"] = {"FreeFormNumber": phone}
        if bill_address is not None:
            body["BillAddr"] = bill_address
        if ship_address is not None:
            body["ShipAddr"] = ship_address
        if notes is not None:
            body["Notes"] = notes
        if taxable is not None:
            body["Taxable"] = taxable
        if extra_fields:
            body.update(extra_fields)
        data = await _req("POST", "/customer", json_body=body)
        return _success(200, data=data.get("Customer", data))

    @mcp.tool()
    async def qb_get_customer(customer_id: str) -> str:
        """Get a QuickBooks customer by ID.
        Args:
            customer_id: Customer ID
        """
        data = await _req("GET", f"/customer/{customer_id}")
        return _success(200, data=data.get("Customer", data))

    @mcp.tool()
    async def qb_update_customer(
        customer_id: str, sync_token: str,
        display_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        company_name: str | None = None,
        bill_address: dict | None = None,
        active: bool | None = None,
        notes: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Update a QuickBooks customer (sparse update).
        Args:
            customer_id: Customer ID
            sync_token: Current SyncToken (from GET)
            display_name: Updated display name
            email: Updated email
            phone: Updated phone
            company_name: Updated company name
            bill_address: Updated billing address
            active: Set false to deactivate
            notes: Updated notes
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "Id": customer_id, "SyncToken": sync_token, "sparse": True,
        }
        if display_name is not None:
            body["DisplayName"] = display_name
        if email is not None:
            body["PrimaryEmailAddr"] = {"Address": email}
        if phone is not None:
            body["PrimaryPhone"] = {"FreeFormNumber": phone}
        if company_name is not None:
            body["CompanyName"] = company_name
        if bill_address is not None:
            body["BillAddr"] = bill_address
        if active is not None:
            body["Active"] = active
        if notes is not None:
            body["Notes"] = notes
        if extra_fields:
            body.update(extra_fields)
        if len(body) <= 3:
            raise ToolError("At least one field to update must be provided.")
        data = await _req("POST", "/customer", json_body=body)
        return _success(200, data=data.get("Customer", data))

    @mcp.tool()
    async def qb_query_customers(
        where: str | None = None, order_by: str | None = None,
        start_position: int = 1, max_results: int = 100,
    ) -> str:
        """Query QuickBooks customers.
        Args:
            where: WHERE clause (e.g., DisplayName LIKE '%Smith%')
            order_by: ORDER BY clause
            start_position: 1-based pagination start
            max_results: Max results (max 1000)
        """
        return await _query("Customer", where, order_by, start_position, max_results)

    @mcp.tool()
    async def qb_delete_customer(customer_id: str, sync_token: str) -> str:
        """Deactivate a QuickBooks customer (soft delete).
        Args:
            customer_id: Customer ID
            sync_token: Current SyncToken
        """
        body = {
            "Id": customer_id, "SyncToken": sync_token,
            "sparse": True, "Active": False,
        }
        data = await _req("POST", "/customer", json_body=body)
        return _success(200, data=data.get("Customer", data))

    # === TIER 2: INVOICES ===

    @mcp.tool()
    async def qb_create_invoice(
        customer_id: str, line_items: list[dict],
        txn_date: str | None = None, due_date: str | None = None,
        doc_number: str | None = None, bill_email: str | None = None,
        customer_memo: str | None = None, private_note: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Create a QuickBooks invoice.
        Args:
            customer_id: Customer ID
            line_items: Line items array with DetailType and amounts
            txn_date: Transaction date (YYYY-MM-DD)
            due_date: Due date (YYYY-MM-DD)
            doc_number: Custom invoice number
            bill_email: Email for sending
            customer_memo: Memo visible to customer
            private_note: Internal note
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "CustomerRef": {"value": customer_id},
            "Line": line_items,
        }
        if txn_date is not None:
            body["TxnDate"] = txn_date
        if due_date is not None:
            body["DueDate"] = due_date
        if doc_number is not None:
            body["DocNumber"] = doc_number
        if bill_email is not None:
            body["BillEmail"] = {"Address": bill_email}
        if customer_memo is not None:
            body["CustomerMemo"] = {"value": customer_memo}
        if private_note is not None:
            body["PrivateNote"] = private_note
        if extra_fields:
            body.update(extra_fields)
        data = await _req("POST", "/invoice", json_body=body)
        return _success(200, data=data.get("Invoice", data))

    @mcp.tool()
    async def qb_get_invoice(invoice_id: str) -> str:
        """Get a QuickBooks invoice by ID.
        Args:
            invoice_id: Invoice ID
        """
        data = await _req("GET", f"/invoice/{invoice_id}")
        return _success(200, data=data.get("Invoice", data))

    @mcp.tool()
    async def qb_update_invoice(
        invoice_id: str, sync_token: str,
        customer_id: str | None = None,
        line_items: list[dict] | None = None,
        txn_date: str | None = None, due_date: str | None = None,
        doc_number: str | None = None,
        customer_memo: str | None = None,
        private_note: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Update a QuickBooks invoice (sparse update).
        Args:
            invoice_id: Invoice ID
            sync_token: Current SyncToken
            customer_id: Updated customer ID
            line_items: Updated line items
            txn_date: Updated transaction date
            due_date: Updated due date
            doc_number: Updated invoice number
            customer_memo: Updated customer memo
            private_note: Updated private note
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "Id": invoice_id, "SyncToken": sync_token, "sparse": True,
        }
        if customer_id is not None:
            body["CustomerRef"] = {"value": customer_id}
        if line_items is not None:
            body["Line"] = line_items
        if txn_date is not None:
            body["TxnDate"] = txn_date
        if due_date is not None:
            body["DueDate"] = due_date
        if doc_number is not None:
            body["DocNumber"] = doc_number
        if customer_memo is not None:
            body["CustomerMemo"] = {"value": customer_memo}
        if private_note is not None:
            body["PrivateNote"] = private_note
        if extra_fields:
            body.update(extra_fields)
        if len(body) <= 3:
            raise ToolError("At least one field to update must be provided.")
        data = await _req("POST", "/invoice", json_body=body)
        return _success(200, data=data.get("Invoice", data))

    @mcp.tool()
    async def qb_query_invoices(
        where: str | None = None, order_by: str | None = None,
        start_position: int = 1, max_results: int = 100,
    ) -> str:
        """Query QuickBooks invoices.
        Args:
            where: WHERE clause
            order_by: ORDER BY clause
            start_position: 1-based pagination start
            max_results: Max results (max 1000)
        """
        return await _query("Invoice", where, order_by, start_position, max_results)

    @mcp.tool()
    async def qb_send_invoice(
        invoice_id: str, email: str | None = None,
    ) -> str:
        """Send a QuickBooks invoice via email.
        Args:
            invoice_id: Invoice ID
            email: Override email address
        """
        p: dict = {}
        if email is not None:
            p["sendTo"] = email
        data = await _req("POST", f"/invoice/{invoice_id}/send", params=p)
        return _success(200, data=data.get("Invoice", data))

    @mcp.tool()
    async def qb_void_invoice(invoice_id: str, sync_token: str) -> str:
        """Void a QuickBooks invoice.
        Args:
            invoice_id: Invoice ID
            sync_token: Current SyncToken
        """
        data = await _req(
            "POST", "/invoice",
            json_body={"Id": invoice_id, "SyncToken": sync_token},
            params={"operation": "void"},
        )
        return _success(200, data=data.get("Invoice", data))

    @mcp.tool()
    async def qb_delete_invoice(invoice_id: str, sync_token: str) -> str:
        """Delete a QuickBooks invoice permanently.
        Args:
            invoice_id: Invoice ID
            sync_token: Current SyncToken
        """
        data = await _req(
            "POST", "/invoice",
            json_body={"Id": invoice_id, "SyncToken": sync_token},
            params={"operation": "delete"},
        )
        return _success(200, data=data.get("Invoice", data))

    # === TIER 3: PAYMENTS ===

    @mcp.tool()
    async def qb_create_payment(
        customer_id: str, total_amt: float,
        txn_date: str | None = None,
        payment_method_ref: str | None = None,
        deposit_to_account_ref: str | None = None,
        invoice_refs: list[dict] | None = None,
        payment_ref_num: str | None = None,
        private_note: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Record a payment received from a customer.
        Args:
            customer_id: Customer ID
            total_amt: Total payment amount
            txn_date: Payment date (YYYY-MM-DD)
            payment_method_ref: Payment method ID
            deposit_to_account_ref: Deposit account ID
            invoice_refs: Invoices to apply: [{TxnId, TxnType, Amount}]
            payment_ref_num: Reference number (e.g., check #)
            private_note: Internal note
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "CustomerRef": {"value": customer_id},
            "TotalAmt": total_amt,
        }
        if txn_date is not None:
            body["TxnDate"] = txn_date
        if payment_method_ref is not None:
            body["PaymentMethodRef"] = {"value": payment_method_ref}
        if deposit_to_account_ref is not None:
            body["DepositToAccountRef"] = {"value": deposit_to_account_ref}
        if invoice_refs is not None:
            body["Line"] = [
                {
                    "Amount": r.get("Amount", total_amt),
                    "LinkedTxn": [{"TxnId": r["TxnId"], "TxnType": r.get("TxnType", "Invoice")}],
                }
                for r in invoice_refs
            ]
        if payment_ref_num is not None:
            body["PaymentRefNum"] = payment_ref_num
        if private_note is not None:
            body["PrivateNote"] = private_note
        if extra_fields:
            body.update(extra_fields)
        data = await _req("POST", "/payment", json_body=body)
        return _success(200, data=data.get("Payment", data))

    @mcp.tool()
    async def qb_get_payment(payment_id: str) -> str:
        """Get a QuickBooks payment by ID.
        Args:
            payment_id: Payment ID
        """
        data = await _req("GET", f"/payment/{payment_id}")
        return _success(200, data=data.get("Payment", data))

    @mcp.tool()
    async def qb_query_payments(
        where: str | None = None, order_by: str | None = None,
        start_position: int = 1, max_results: int = 100,
    ) -> str:
        """Query QuickBooks payments.
        Args:
            where: WHERE clause
            order_by: ORDER BY clause
            start_position: 1-based pagination start
            max_results: Max results (max 1000)
        """
        return await _query("Payment", where, order_by, start_position, max_results)

    @mcp.tool()
    async def qb_void_payment(payment_id: str, sync_token: str) -> str:
        """Void a QuickBooks payment.
        Args:
            payment_id: Payment ID
            sync_token: Current SyncToken
        """
        data = await _req(
            "POST", "/payment",
            json_body={"Id": payment_id, "SyncToken": sync_token},
            params={"operation": "void"},
        )
        return _success(200, data=data.get("Payment", data))

    @mcp.tool()
    async def qb_delete_payment(payment_id: str, sync_token: str) -> str:
        """Delete a QuickBooks payment permanently.
        Args:
            payment_id: Payment ID
            sync_token: Current SyncToken
        """
        data = await _req(
            "POST", "/payment",
            json_body={"Id": payment_id, "SyncToken": sync_token},
            params={"operation": "delete"},
        )
        return _success(200, data=data.get("Payment", data))

    # === TIER 4: ITEMS ===

    @mcp.tool()
    async def qb_create_item(
        name: str, income_account_ref: str,
        type: str = "Service",
        description: str | None = None,
        unit_price: float | None = None,
        expense_account_ref: str | None = None,
        asset_account_ref: str | None = None,
        qty_on_hand: float | None = None,
        inv_start_date: str | None = None,
        sku: str | None = None,
        taxable: bool | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Create a QuickBooks item (product/service).
        Args:
            name: Item name (unique)
            income_account_ref: Income account ID
            type: Service, Inventory, NonInventory
            description: Sales description
            unit_price: Unit price
            expense_account_ref: Expense account ID
            asset_account_ref: Asset account ID (required for Inventory)
            qty_on_hand: Initial quantity (required for Inventory)
            inv_start_date: Inventory start date (required for Inventory)
            sku: SKU/part number
            taxable: Whether item is taxable
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "Name": name,
            "Type": type,
            "IncomeAccountRef": {"value": income_account_ref},
        }
        if description is not None:
            body["Description"] = description
        if unit_price is not None:
            body["UnitPrice"] = unit_price
        if expense_account_ref is not None:
            body["ExpenseAccountRef"] = {"value": expense_account_ref}
        if asset_account_ref is not None:
            body["AssetAccountRef"] = {"value": asset_account_ref}
        if qty_on_hand is not None:
            body["QtyOnHand"] = qty_on_hand
        if inv_start_date is not None:
            body["InvStartDate"] = inv_start_date
        if sku is not None:
            body["Sku"] = sku
        if taxable is not None:
            body["Taxable"] = taxable
        if extra_fields:
            body.update(extra_fields)
        data = await _req("POST", "/item", json_body=body)
        return _success(200, data=data.get("Item", data))

    @mcp.tool()
    async def qb_get_item(item_id: str) -> str:
        """Get a QuickBooks item by ID.
        Args:
            item_id: Item ID
        """
        data = await _req("GET", f"/item/{item_id}")
        return _success(200, data=data.get("Item", data))

    @mcp.tool()
    async def qb_update_item(
        item_id: str, sync_token: str,
        name: str | None = None,
        description: str | None = None,
        unit_price: float | None = None,
        sku: str | None = None,
        taxable: bool | None = None,
        active: bool | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Update a QuickBooks item (sparse update).
        Args:
            item_id: Item ID
            sync_token: Current SyncToken
            name: Updated name
            description: Updated description
            unit_price: Updated unit price
            sku: Updated SKU
            taxable: Updated taxable flag
            active: Set false to deactivate
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "Id": item_id, "SyncToken": sync_token, "sparse": True,
        }
        if name is not None:
            body["Name"] = name
        if description is not None:
            body["Description"] = description
        if unit_price is not None:
            body["UnitPrice"] = unit_price
        if sku is not None:
            body["Sku"] = sku
        if taxable is not None:
            body["Taxable"] = taxable
        if active is not None:
            body["Active"] = active
        if extra_fields:
            body.update(extra_fields)
        if len(body) <= 3:
            raise ToolError("At least one field to update must be provided.")
        data = await _req("POST", "/item", json_body=body)
        return _success(200, data=data.get("Item", data))

    @mcp.tool()
    async def qb_query_items(
        where: str | None = None, order_by: str | None = None,
        start_position: int = 1, max_results: int = 100,
    ) -> str:
        """Query QuickBooks items.
        Args:
            where: WHERE clause
            order_by: ORDER BY clause
            start_position: 1-based pagination start
            max_results: Max results (max 1000)
        """
        return await _query("Item", where, order_by, start_position, max_results)

    # === TIER 5: ACCOUNTS ===

    @mcp.tool()
    async def qb_get_account(account_id: str) -> str:
        """Get a QuickBooks account by ID.
        Args:
            account_id: Account ID
        """
        data = await _req("GET", f"/account/{account_id}")
        return _success(200, data=data.get("Account", data))

    @mcp.tool()
    async def qb_query_accounts(
        where: str | None = None, order_by: str | None = None,
        start_position: int = 1, max_results: int = 100,
    ) -> str:
        """Query QuickBooks accounts (chart of accounts).
        Args:
            where: WHERE clause
            order_by: ORDER BY clause
            start_position: 1-based pagination start
            max_results: Max results (max 1000)
        """
        return await _query("Account", where, order_by, start_position, max_results)

    # === TIER 6: BILLS ===

    @mcp.tool()
    async def qb_create_bill(
        vendor_id: str, line_items: list[dict],
        txn_date: str | None = None, due_date: str | None = None,
        doc_number: str | None = None,
        private_note: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Create a QuickBooks bill (vendor payable).
        Args:
            vendor_id: Vendor ID
            line_items: Line items array
            txn_date: Bill date (YYYY-MM-DD)
            due_date: Due date (YYYY-MM-DD)
            doc_number: Bill reference number
            private_note: Internal memo
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "VendorRef": {"value": vendor_id},
            "Line": line_items,
        }
        if txn_date is not None:
            body["TxnDate"] = txn_date
        if due_date is not None:
            body["DueDate"] = due_date
        if doc_number is not None:
            body["DocNumber"] = doc_number
        if private_note is not None:
            body["PrivateNote"] = private_note
        if extra_fields:
            body.update(extra_fields)
        data = await _req("POST", "/bill", json_body=body)
        return _success(200, data=data.get("Bill", data))

    @mcp.tool()
    async def qb_get_bill(bill_id: str) -> str:
        """Get a QuickBooks bill by ID.
        Args:
            bill_id: Bill ID
        """
        data = await _req("GET", f"/bill/{bill_id}")
        return _success(200, data=data.get("Bill", data))

    @mcp.tool()
    async def qb_update_bill(
        bill_id: str, sync_token: str,
        vendor_id: str | None = None,
        line_items: list[dict] | None = None,
        txn_date: str | None = None, due_date: str | None = None,
        doc_number: str | None = None,
        private_note: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Update a QuickBooks bill (sparse update).
        Args:
            bill_id: Bill ID
            sync_token: Current SyncToken
            vendor_id: Updated vendor ID
            line_items: Updated line items
            txn_date: Updated bill date
            due_date: Updated due date
            doc_number: Updated reference number
            private_note: Updated memo
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "Id": bill_id, "SyncToken": sync_token, "sparse": True,
        }
        if vendor_id is not None:
            body["VendorRef"] = {"value": vendor_id}
        if line_items is not None:
            body["Line"] = line_items
        if txn_date is not None:
            body["TxnDate"] = txn_date
        if due_date is not None:
            body["DueDate"] = due_date
        if doc_number is not None:
            body["DocNumber"] = doc_number
        if private_note is not None:
            body["PrivateNote"] = private_note
        if extra_fields:
            body.update(extra_fields)
        if len(body) <= 3:
            raise ToolError("At least one field to update must be provided.")
        data = await _req("POST", "/bill", json_body=body)
        return _success(200, data=data.get("Bill", data))

    @mcp.tool()
    async def qb_query_bills(
        where: str | None = None, order_by: str | None = None,
        start_position: int = 1, max_results: int = 100,
    ) -> str:
        """Query QuickBooks bills.
        Args:
            where: WHERE clause
            order_by: ORDER BY clause
            start_position: 1-based pagination start
            max_results: Max results (max 1000)
        """
        return await _query("Bill", where, order_by, start_position, max_results)

    # === TIER 7: VENDORS ===

    @mcp.tool()
    async def qb_create_vendor(
        display_name: str,
        given_name: str | None = None,
        family_name: str | None = None,
        company_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        bill_address: dict | None = None,
        tax_identifier: str | None = None,
        vendor_1099: bool | None = None,
        notes: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Create a QuickBooks vendor.
        Args:
            display_name: Vendor display name (unique)
            given_name: First name
            family_name: Last name
            company_name: Company name
            email: Primary email
            phone: Primary phone
            bill_address: Billing address dict
            tax_identifier: Tax ID/EIN
            vendor_1099: Whether vendor receives 1099
            notes: Notes
            extra_fields: Additional QBO fields
        """
        body: dict = {"DisplayName": display_name}
        if given_name is not None:
            body["GivenName"] = given_name
        if family_name is not None:
            body["FamilyName"] = family_name
        if company_name is not None:
            body["CompanyName"] = company_name
        if email is not None:
            body["PrimaryEmailAddr"] = {"Address": email}
        if phone is not None:
            body["PrimaryPhone"] = {"FreeFormNumber": phone}
        if bill_address is not None:
            body["BillAddr"] = bill_address
        if tax_identifier is not None:
            body["TaxIdentifier"] = tax_identifier
        if vendor_1099 is not None:
            body["Vendor1099"] = vendor_1099
        if notes is not None:
            body["Notes"] = notes
        if extra_fields:
            body.update(extra_fields)
        data = await _req("POST", "/vendor", json_body=body)
        return _success(200, data=data.get("Vendor", data))

    @mcp.tool()
    async def qb_get_vendor(vendor_id: str) -> str:
        """Get a QuickBooks vendor by ID.
        Args:
            vendor_id: Vendor ID
        """
        data = await _req("GET", f"/vendor/{vendor_id}")
        return _success(200, data=data.get("Vendor", data))

    @mcp.tool()
    async def qb_update_vendor(
        vendor_id: str, sync_token: str,
        display_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        company_name: str | None = None,
        bill_address: dict | None = None,
        vendor_1099: bool | None = None,
        active: bool | None = None,
        notes: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Update a QuickBooks vendor (sparse update).
        Args:
            vendor_id: Vendor ID
            sync_token: Current SyncToken
            display_name: Updated display name
            email: Updated email
            phone: Updated phone
            company_name: Updated company name
            bill_address: Updated billing address
            vendor_1099: Updated 1099 flag
            active: Set false to deactivate
            notes: Updated notes
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "Id": vendor_id, "SyncToken": sync_token, "sparse": True,
        }
        if display_name is not None:
            body["DisplayName"] = display_name
        if email is not None:
            body["PrimaryEmailAddr"] = {"Address": email}
        if phone is not None:
            body["PrimaryPhone"] = {"FreeFormNumber": phone}
        if company_name is not None:
            body["CompanyName"] = company_name
        if bill_address is not None:
            body["BillAddr"] = bill_address
        if vendor_1099 is not None:
            body["Vendor1099"] = vendor_1099
        if active is not None:
            body["Active"] = active
        if notes is not None:
            body["Notes"] = notes
        if extra_fields:
            body.update(extra_fields)
        if len(body) <= 3:
            raise ToolError("At least one field to update must be provided.")
        data = await _req("POST", "/vendor", json_body=body)
        return _success(200, data=data.get("Vendor", data))

    @mcp.tool()
    async def qb_query_vendors(
        where: str | None = None, order_by: str | None = None,
        start_position: int = 1, max_results: int = 100,
    ) -> str:
        """Query QuickBooks vendors.
        Args:
            where: WHERE clause
            order_by: ORDER BY clause
            start_position: 1-based pagination start
            max_results: Max results (max 1000)
        """
        return await _query("Vendor", where, order_by, start_position, max_results)

    # === TIER 8: ESTIMATES ===

    @mcp.tool()
    async def qb_create_estimate(
        customer_id: str, line_items: list[dict],
        txn_date: str | None = None,
        expiration_date: str | None = None,
        doc_number: str | None = None,
        bill_email: str | None = None,
        customer_memo: str | None = None,
        private_note: str | None = None,
        txn_status: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Create a QuickBooks estimate (quote).
        Args:
            customer_id: Customer ID
            line_items: Line items array
            txn_date: Estimate date (YYYY-MM-DD)
            expiration_date: Expiration date (YYYY-MM-DD)
            doc_number: Custom estimate number
            bill_email: Email for sending
            customer_memo: Memo visible to customer
            private_note: Internal note
            txn_status: Pending, Accepted, Closed, Rejected
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "CustomerRef": {"value": customer_id},
            "Line": line_items,
        }
        if txn_date is not None:
            body["TxnDate"] = txn_date
        if expiration_date is not None:
            body["ExpirationDate"] = expiration_date
        if doc_number is not None:
            body["DocNumber"] = doc_number
        if bill_email is not None:
            body["BillEmail"] = {"Address": bill_email}
        if customer_memo is not None:
            body["CustomerMemo"] = {"value": customer_memo}
        if private_note is not None:
            body["PrivateNote"] = private_note
        if txn_status is not None:
            body["TxnStatus"] = txn_status
        if extra_fields:
            body.update(extra_fields)
        data = await _req("POST", "/estimate", json_body=body)
        return _success(200, data=data.get("Estimate", data))

    @mcp.tool()
    async def qb_get_estimate(estimate_id: str) -> str:
        """Get a QuickBooks estimate by ID.
        Args:
            estimate_id: Estimate ID
        """
        data = await _req("GET", f"/estimate/{estimate_id}")
        return _success(200, data=data.get("Estimate", data))

    @mcp.tool()
    async def qb_update_estimate(
        estimate_id: str, sync_token: str,
        customer_id: str | None = None,
        line_items: list[dict] | None = None,
        txn_date: str | None = None,
        expiration_date: str | None = None,
        doc_number: str | None = None,
        customer_memo: str | None = None,
        private_note: str | None = None,
        txn_status: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Update a QuickBooks estimate (sparse update).
        Args:
            estimate_id: Estimate ID
            sync_token: Current SyncToken
            customer_id: Updated customer ID
            line_items: Updated line items
            txn_date: Updated estimate date
            expiration_date: Updated expiration date
            doc_number: Updated estimate number
            customer_memo: Updated customer memo
            private_note: Updated private note
            txn_status: Updated status
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "Id": estimate_id, "SyncToken": sync_token, "sparse": True,
        }
        if customer_id is not None:
            body["CustomerRef"] = {"value": customer_id}
        if line_items is not None:
            body["Line"] = line_items
        if txn_date is not None:
            body["TxnDate"] = txn_date
        if expiration_date is not None:
            body["ExpirationDate"] = expiration_date
        if doc_number is not None:
            body["DocNumber"] = doc_number
        if customer_memo is not None:
            body["CustomerMemo"] = {"value": customer_memo}
        if private_note is not None:
            body["PrivateNote"] = private_note
        if txn_status is not None:
            body["TxnStatus"] = txn_status
        if extra_fields:
            body.update(extra_fields)
        if len(body) <= 3:
            raise ToolError("At least one field to update must be provided.")
        data = await _req("POST", "/estimate", json_body=body)
        return _success(200, data=data.get("Estimate", data))

    @mcp.tool()
    async def qb_query_estimates(
        where: str | None = None, order_by: str | None = None,
        start_position: int = 1, max_results: int = 100,
    ) -> str:
        """Query QuickBooks estimates.
        Args:
            where: WHERE clause
            order_by: ORDER BY clause
            start_position: 1-based pagination start
            max_results: Max results (max 1000)
        """
        return await _query("Estimate", where, order_by, start_position, max_results)

    @mcp.tool()
    async def qb_send_estimate(
        estimate_id: str, email: str | None = None,
    ) -> str:
        """Send a QuickBooks estimate via email.
        Args:
            estimate_id: Estimate ID
            email: Override email address
        """
        p: dict = {}
        if email is not None:
            p["sendTo"] = email
        data = await _req("POST", f"/estimate/{estimate_id}/send", params=p)
        return _success(200, data=data.get("Estimate", data))

    # === TIER 9: CREDIT MEMOS ===

    @mcp.tool()
    async def qb_create_credit_memo(
        customer_id: str, line_items: list[dict],
        txn_date: str | None = None,
        doc_number: str | None = None,
        customer_memo: str | None = None,
        private_note: str | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Create a QuickBooks credit memo.
        Args:
            customer_id: Customer ID
            line_items: Line items array
            txn_date: Credit memo date (YYYY-MM-DD)
            doc_number: Custom credit memo number
            customer_memo: Memo visible to customer
            private_note: Internal note
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "CustomerRef": {"value": customer_id},
            "Line": line_items,
        }
        if txn_date is not None:
            body["TxnDate"] = txn_date
        if doc_number is not None:
            body["DocNumber"] = doc_number
        if customer_memo is not None:
            body["CustomerMemo"] = {"value": customer_memo}
        if private_note is not None:
            body["PrivateNote"] = private_note
        if extra_fields:
            body.update(extra_fields)
        data = await _req("POST", "/creditmemo", json_body=body)
        return _success(200, data=data.get("CreditMemo", data))

    @mcp.tool()
    async def qb_get_credit_memo(credit_memo_id: str) -> str:
        """Get a QuickBooks credit memo by ID.
        Args:
            credit_memo_id: Credit Memo ID
        """
        data = await _req("GET", f"/creditmemo/{credit_memo_id}")
        return _success(200, data=data.get("CreditMemo", data))

    @mcp.tool()
    async def qb_query_credit_memos(
        where: str | None = None, order_by: str | None = None,
        start_position: int = 1, max_results: int = 100,
    ) -> str:
        """Query QuickBooks credit memos.
        Args:
            where: WHERE clause
            order_by: ORDER BY clause
            start_position: 1-based pagination start
            max_results: Max results (max 1000)
        """
        return await _query(
            "CreditMemo", where, order_by, start_position, max_results,
        )

    # === TIER 10: PURCHASES ===

    @mcp.tool()
    async def qb_create_purchase(
        account_ref: str, payment_type: str,
        line_items: list[dict],
        txn_date: str | None = None,
        entity_ref: dict | None = None,
        doc_number: str | None = None,
        private_note: str | None = None,
        total_amt: float | None = None,
        credit: bool | None = None,
        extra_fields: dict | None = None,
    ) -> str:
        """Create a QuickBooks purchase (expense/check/credit card).
        Args:
            account_ref: Bank/credit card account ID
            payment_type: Cash, Check, or CreditCard
            line_items: Line items array
            txn_date: Purchase date (YYYY-MM-DD)
            entity_ref: Payee {value, type} (Vendor or Customer)
            doc_number: Reference/check number
            private_note: Internal memo
            total_amt: Total amount
            credit: True for refund/credit
            extra_fields: Additional QBO fields
        """
        body: dict = {
            "AccountRef": {"value": account_ref},
            "PaymentType": payment_type,
            "Line": line_items,
        }
        if txn_date is not None:
            body["TxnDate"] = txn_date
        if entity_ref is not None:
            body["EntityRef"] = entity_ref
        if doc_number is not None:
            body["DocNumber"] = doc_number
        if private_note is not None:
            body["PrivateNote"] = private_note
        if total_amt is not None:
            body["TotalAmt"] = total_amt
        if credit is not None:
            body["Credit"] = credit
        if extra_fields:
            body.update(extra_fields)
        data = await _req("POST", "/purchase", json_body=body)
        return _success(200, data=data.get("Purchase", data))

    @mcp.tool()
    async def qb_get_purchase(purchase_id: str) -> str:
        """Get a QuickBooks purchase by ID.
        Args:
            purchase_id: Purchase ID
        """
        data = await _req("GET", f"/purchase/{purchase_id}")
        return _success(200, data=data.get("Purchase", data))

    @mcp.tool()
    async def qb_query_purchases(
        where: str | None = None, order_by: str | None = None,
        start_position: int = 1, max_results: int = 100,
    ) -> str:
        """Query QuickBooks purchases.
        Args:
            where: WHERE clause
            order_by: ORDER BY clause
            start_position: 1-based pagination start
            max_results: Max results (max 1000)
        """
        return await _query(
            "Purchase", where, order_by, start_position, max_results,
        )

    # === TIER 11: REPORTS ===

    @mcp.tool()
    async def qb_report_profit_and_loss(
        start_date: str | None = None,
        end_date: str | None = None,
        accounting_method: str | None = None,
        summarize_column_by: str | None = None,
        customer: str | None = None,
        department: str | None = None,
    ) -> str:
        """Run a Profit and Loss report.
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            accounting_method: Cash or Accrual
            summarize_column_by: Total, Month, Quarter, Year
            customer: Filter by customer ID
            department: Filter by department ID
        """
        p: dict = {}
        if start_date is not None:
            p["start_date"] = start_date
        if end_date is not None:
            p["end_date"] = end_date
        if accounting_method is not None:
            p["accounting_method"] = accounting_method
        if summarize_column_by is not None:
            p["summarize_column_by"] = summarize_column_by
        if customer is not None:
            p["customer"] = customer
        if department is not None:
            p["department"] = department
        data = await _req("GET", "/reports/ProfitAndLoss", params=p)
        return _success(200, data=data)

    @mcp.tool()
    async def qb_report_balance_sheet(
        start_date: str | None = None,
        end_date: str | None = None,
        accounting_method: str | None = None,
        summarize_column_by: str | None = None,
    ) -> str:
        """Run a Balance Sheet report.
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            accounting_method: Cash or Accrual
            summarize_column_by: Total, Month, Quarter, Year
        """
        p: dict = {}
        if start_date is not None:
            p["start_date"] = start_date
        if end_date is not None:
            p["end_date"] = end_date
        if accounting_method is not None:
            p["accounting_method"] = accounting_method
        if summarize_column_by is not None:
            p["summarize_column_by"] = summarize_column_by
        data = await _req("GET", "/reports/BalanceSheet", params=p)
        return _success(200, data=data)

    @mcp.tool()
    async def qb_report_accounts_receivable_aging(
        report_date: str | None = None,
        aging_period: int | None = None,
        num_periods: int | None = None,
        customer: str | None = None,
    ) -> str:
        """Run an Accounts Receivable Aging report.
        Args:
            report_date: As-of date (YYYY-MM-DD)
            aging_period: Days per period (default 30)
            num_periods: Number of periods (default 4)
            customer: Filter by customer ID
        """
        p: dict = {}
        if report_date is not None:
            p["report_date"] = report_date
        if aging_period is not None:
            p["aging_period"] = str(aging_period)
        if num_periods is not None:
            p["num_periods"] = str(num_periods)
        if customer is not None:
            p["customer"] = customer
        data = await _req("GET", "/reports/AgedReceivables", params=p)
        return _success(200, data=data)

    # === TIER 12: COMPANY INFO ===

    @mcp.tool()
    async def qb_get_company_info() -> str:
        """Get QuickBooks company information."""
        data = await _req("GET", f"/companyinfo/{QB_REALM_ID}")
        return _success(200, data=data.get("CompanyInfo", data))
