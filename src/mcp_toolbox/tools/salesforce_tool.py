"""Salesforce REST API integration — SObject CRUD, SOQL, SOSL,
describe, bulk, composite, reports, and admin tools (66 tools)."""

import asyncio
import json
import logging
import time

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import (
    SF_API_VERSION,
    SF_CLIENT_ID,
    SF_CLIENT_SECRET,
    SF_INSTANCE_URL,
    SF_REFRESH_TOKEN,
)

logger = logging.getLogger(__name__)

# --------------- auth state ---------------
_access_token: str | None = None
_token_expires_at: float = 0.0
_instance_url: str | None = None
_id_url: str | None = None
_token_lock: asyncio.Lock | None = None
_client: httpx.AsyncClient | None = None


def _check_config() -> None:
    if not all([SF_CLIENT_ID, SF_CLIENT_SECRET, SF_REFRESH_TOKEN]):
        raise ToolError(
            "Salesforce not configured. Set SF_CLIENT_ID, "
            "SF_CLIENT_SECRET, and SF_REFRESH_TOKEN."
        )


async def _get_token() -> tuple[str, str]:
    """Return (access_token, instance_url)."""
    global _access_token, _token_expires_at
    global _instance_url, _id_url, _token_lock
    _check_config()
    if _token_lock is None:
        _token_lock = asyncio.Lock()
    async with _token_lock:
        if (
            _access_token
            and _instance_url
            and time.time() < _token_expires_at - 60
        ):
            return _access_token, _instance_url
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                "https://login.salesforce.com"
                "/services/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": SF_CLIENT_ID,
                    "client_secret": SF_CLIENT_SECRET,
                    "refresh_token": SF_REFRESH_TOKEN,
                },
                timeout=30.0,
            )
        if resp.status_code != 200:
            raise ToolError(
                "SF token refresh failed "
                f"({resp.status_code}): {resp.text}"
            )
        data = resp.json()
        _access_token = data["access_token"]
        _instance_url = SF_INSTANCE_URL or data["instance_url"]
        _id_url = data.get("id")
        _token_expires_at = time.time() + 7200
        return _access_token, _instance_url


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=60.0)
    return _client


def _success(sc: int, **kw: object) -> str:
    return json.dumps(
        {"status": "success", "status_code": sc, **kw}
    )


async def _req(
    method: str,
    path: str,
    *,
    json_body: dict | list | None = None,
    params: dict | None = None,
    content: str | None = None,
    content_type: str | None = None,
    raw_url: str | None = None,
) -> dict | list | None:
    """Authenticated Salesforce REST request.

    Returns parsed JSON, or None for 204 responses.
    *raw_url* bypasses base-url building (for queryMore).
    """
    token, inst = await _get_token()
    if raw_url:
        url = f"{inst}{raw_url}"
    else:
        url = f"{inst}/services/data/{SF_API_VERSION}/{path}"
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
    }
    if content_type is not None:
        headers["Content-Type"] = content_type
    elif content is None:
        headers["Content-Type"] = "application/json"
    client = _get_client()
    kwargs: dict[str, object] = {"headers": headers}
    if json_body is not None:
        kwargs["json"] = json_body
    if params is not None:
        kwargs["params"] = params
    if content is not None:
        kwargs["content"] = content
        if content_type is not None:
            headers["Content-Type"] = content_type
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(
            f"Salesforce request failed: {e}"
        ) from e
    if response.status_code == 204:
        return None
    if response.status_code >= 400:
        try:
            err = response.json()
            if isinstance(err, list):
                msg = "; ".join(
                    e.get("message", "")
                    for e in err
                )
            else:
                msg = err.get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(
            f"Salesforce error ({response.status_code}): {msg}"
        )
    if response.status_code == 201:
        try:
            return response.json()
        except Exception:
            return {"status_code": 201}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


# --------------- SOQL builder ---------------

def _escape(val: str) -> str:
    return val.replace("\\", "\\\\").replace("'", "\\'")


def _build_soql(
    sobject: str,
    fields: list[str],
    filters: dict[str, object],
    order_by: str,
    order_dir: str,
    limit: int,
    offset: int,
    *,
    like_filters: dict[str, str] | None = None,
    gte_filters: dict[str, object] | None = None,
    lte_filters: dict[str, object] | None = None,
) -> str:
    """Build a safe SOQL query string."""
    clauses: list[str] = []
    for field, value in filters.items():
        if isinstance(value, bool):
            clauses.append(
                f"{field} = {str(value).lower()}"
            )
        elif isinstance(value, str):
            clauses.append(
                f"{field} = '{_escape(value)}'"
            )
        elif isinstance(value, (int, float)):
            clauses.append(f"{field} = {value}")
    if like_filters:
        for field, value in like_filters.items():
            clauses.append(
                f"{field} LIKE '%{_escape(value)}%'"
            )
    if gte_filters:
        for field, value in gte_filters.items():
            if isinstance(value, str):
                clauses.append(f"{field} >= {value}")
            else:
                clauses.append(f"{field} >= {value}")
    if lte_filters:
        for field, value in lte_filters.items():
            if isinstance(value, str):
                clauses.append(f"{field} <= {value}")
            else:
                clauses.append(f"{field} <= {value}")
    q = f"SELECT {', '.join(fields)} FROM {sobject}"
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += f" ORDER BY {order_by} {order_dir}"
    q += f" LIMIT {limit}"
    if offset > 0:
        q += f" OFFSET {offset}"
    return q


# --------------- shared SObject helpers ---------------

async def _sobject_create(
    sobject: str, body: dict,
) -> str:
    data = await _req(
        "POST", f"sobjects/{sobject}/", json_body=body,
    )
    return _success(201, data=data)


async def _sobject_get(
    sobject: str,
    record_id: str,
    fields: list[str] | None = None,
) -> str:
    params: dict[str, str] | None = None
    if fields:
        params = {"fields": ",".join(fields)}
    data = await _req(
        "GET",
        f"sobjects/{sobject}/{record_id}",
        params=params,
    )
    return _success(200, data=data)


async def _sobject_update(
    sobject: str, record_id: str, body: dict,
) -> str:
    if not body:
        raise ToolError(
            "At least one field to update must be provided."
        )
    await _req(
        "PATCH",
        f"sobjects/{sobject}/{record_id}",
        json_body=body,
    )
    return _success(204)


async def _sobject_delete(
    sobject: str, record_id: str,
) -> str:
    await _req(
        "DELETE", f"sobjects/{sobject}/{record_id}",
    )
    return _success(204)


async def _sobject_list(
    sobject: str,
    fields: list[str],
    default_fields: list[str],
    filters: dict[str, object],
    order_by: str,
    order_dir: str,
    limit: int,
    offset: int,
    *,
    like_filters: dict[str, str] | None = None,
    gte_filters: dict[str, object] | None = None,
    lte_filters: dict[str, object] | None = None,
) -> str:
    sel = fields if fields else default_fields
    q = _build_soql(
        sobject, sel, filters, order_by, order_dir,
        min(limit, 2000), offset,
        like_filters=like_filters,
        gte_filters=gte_filters,
        lte_filters=lte_filters,
    )
    data = await _req("GET", "query/", params={"q": q})
    return _success(200, data=data)


async def _sobject_upsert(
    sobject: str,
    external_id_field: str,
    external_id_value: str,
    body: dict,
) -> str:
    data = await _req(
        "PATCH",
        f"sobjects/{sobject}/{external_id_field}"
        f"/{external_id_value}",
        json_body=body,
    )
    if data is None:
        return _success(204)
    return _success(201, data=data)


# --------------- body builders ---------------

def _add(body: dict, key: str, val: object) -> None:
    if val is not None:
        body[key] = val


def register_tools(mcp: FastMCP) -> None:  # noqa: C901
    if not all([SF_CLIENT_ID, SF_CLIENT_SECRET, SF_REFRESH_TOKEN]):
        logger.warning(
            "Salesforce credentials not set — SF tools will fail."
        )

    # ===================================================
    # TIER 1: ACCOUNT SOBJECT (6 tools)
    # ===================================================

    @mcp.tool()
    async def sf_create_account(
        name: str,
        industry: str | None = None,
        type: str | None = None,
        phone: str | None = None,
        website: str | None = None,
        description: str | None = None,
        billing_street: str | None = None,
        billing_city: str | None = None,
        billing_state: str | None = None,
        billing_postal_code: str | None = None,
        billing_country: str | None = None,
        owner_id: str | None = None,
        parent_id: str | None = None,
        annual_revenue: float | None = None,
        number_of_employees: int | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Create a Salesforce Account.
        Args:
            name: Account name
            industry: Industry picklist value
            type: Account type (Customer, Partner, etc.)
            phone: Phone number
            website: Website URL
            description: Account description
            billing_street: Billing street address
            billing_city: Billing city
            billing_state: Billing state/province
            billing_postal_code: Billing postal/ZIP code
            billing_country: Billing country
            owner_id: Owner user ID
            parent_id: Parent account ID
            annual_revenue: Annual revenue
            number_of_employees: Number of employees
            custom_fields: Additional fields as key-value pairs
        """
        body: dict = {"Name": name}
        _add(body, "Industry", industry)
        _add(body, "Type", type)
        _add(body, "Phone", phone)
        _add(body, "Website", website)
        _add(body, "Description", description)
        _add(body, "BillingStreet", billing_street)
        _add(body, "BillingCity", billing_city)
        _add(body, "BillingState", billing_state)
        _add(body, "BillingPostalCode", billing_postal_code)
        _add(body, "BillingCountry", billing_country)
        _add(body, "OwnerId", owner_id)
        _add(body, "ParentId", parent_id)
        _add(body, "AnnualRevenue", annual_revenue)
        _add(body, "NumberOfEmployees", number_of_employees)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_create("Account", body)

    @mcp.tool()
    async def sf_get_account(
        account_id: str,
        fields: list[str] | None = None,
    ) -> str:
        """Get a Salesforce Account by ID.
        Args:
            account_id: Account ID (e.g. 001xx...)
            fields: Specific fields to retrieve
        """
        return await _sobject_get(
            "Account", account_id, fields,
        )

    @mcp.tool()
    async def sf_update_account(
        account_id: str,
        name: str | None = None,
        industry: str | None = None,
        type: str | None = None,
        phone: str | None = None,
        website: str | None = None,
        description: str | None = None,
        billing_street: str | None = None,
        billing_city: str | None = None,
        billing_state: str | None = None,
        billing_postal_code: str | None = None,
        billing_country: str | None = None,
        owner_id: str | None = None,
        parent_id: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Update a Salesforce Account.
        Args:
            account_id: Account ID
            name: Updated name
            industry: Updated industry
            type: Updated type
            phone: Updated phone
            website: Updated website
            description: Updated description
            billing_street: Updated billing street
            billing_city: Updated billing city
            billing_state: Updated billing state
            billing_postal_code: Updated billing postal code
            billing_country: Updated billing country
            owner_id: Updated owner
            parent_id: Updated parent account
            custom_fields: Additional fields to update
        """
        body: dict = {}
        _add(body, "Name", name)
        _add(body, "Industry", industry)
        _add(body, "Type", type)
        _add(body, "Phone", phone)
        _add(body, "Website", website)
        _add(body, "Description", description)
        _add(body, "BillingStreet", billing_street)
        _add(body, "BillingCity", billing_city)
        _add(body, "BillingState", billing_state)
        _add(body, "BillingPostalCode", billing_postal_code)
        _add(body, "BillingCountry", billing_country)
        _add(body, "OwnerId", owner_id)
        _add(body, "ParentId", parent_id)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_update(
            "Account", account_id, body,
        )

    @mcp.tool()
    async def sf_delete_account(account_id: str) -> str:
        """Delete a Salesforce Account (moves to Recycle Bin).
        Args:
            account_id: Account ID to delete
        """
        return await _sobject_delete("Account", account_id)

    @mcp.tool()
    async def sf_list_accounts(
        limit: int = 20,
        offset: int = 0,
        order_by: str = "Name",
        order_dir: str = "ASC",
        name_like: str | None = None,
        industry: str | None = None,
        type: str | None = None,
        owner_id: str | None = None,
        fields: list[str] | None = None,
    ) -> str:
        """List Salesforce Accounts with filters.
        Args:
            limit: Max records (default 20, max 2000)
            offset: Records to skip
            order_by: Sort field (default Name)
            order_dir: ASC or DESC
            name_like: Filter: Name contains string
            industry: Filter: exact Industry match
            type: Filter: exact Type match
            owner_id: Filter: exact Owner ID
            fields: Fields to return
        """
        default = [
            "Id", "Name", "Industry", "Type",
            "Phone", "Website",
        ]
        filt: dict[str, object] = {}
        if industry is not None:
            filt["Industry"] = industry
        if type is not None:
            filt["Type"] = type
        if owner_id is not None:
            filt["OwnerId"] = owner_id
        like: dict[str, str] = {}
        if name_like is not None:
            like["Name"] = name_like
        return await _sobject_list(
            "Account", fields or [], default, filt,
            order_by, order_dir, limit, offset,
            like_filters=like or None,
        )

    @mcp.tool()
    async def sf_upsert_account(
        external_id_field: str,
        external_id_value: str,
        name: str | None = None,
        industry: str | None = None,
        type: str | None = None,
        phone: str | None = None,
        website: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Upsert a Salesforce Account by external ID.
        Args:
            external_id_field: External ID field API name
            external_id_value: External ID value
            name: Account name
            industry: Industry
            type: Account type
            phone: Phone
            website: Website
            custom_fields: Additional fields
        """
        body: dict = {}
        _add(body, "Name", name)
        _add(body, "Industry", industry)
        _add(body, "Type", type)
        _add(body, "Phone", phone)
        _add(body, "Website", website)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_upsert(
            "Account", external_id_field,
            external_id_value, body,
        )

    # ===================================================
    # TIER 2: CONTACT SOBJECT (6 tools)
    # ===================================================

    @mcp.tool()
    async def sf_create_contact(
        last_name: str,
        first_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        mobile_phone: str | None = None,
        title: str | None = None,
        department: str | None = None,
        account_id: str | None = None,
        mailing_street: str | None = None,
        mailing_city: str | None = None,
        mailing_state: str | None = None,
        mailing_postal_code: str | None = None,
        mailing_country: str | None = None,
        owner_id: str | None = None,
        description: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Create a Salesforce Contact.
        Args:
            last_name: Last name (required)
            first_name: First name
            email: Email address
            phone: Phone number
            mobile_phone: Mobile phone
            title: Job title
            department: Department
            account_id: Associated Account ID
            mailing_street: Mailing street
            mailing_city: Mailing city
            mailing_state: Mailing state
            mailing_postal_code: Mailing postal code
            mailing_country: Mailing country
            owner_id: Owner user ID
            description: Description
            custom_fields: Additional fields
        """
        body: dict = {"LastName": last_name}
        _add(body, "FirstName", first_name)
        _add(body, "Email", email)
        _add(body, "Phone", phone)
        _add(body, "MobilePhone", mobile_phone)
        _add(body, "Title", title)
        _add(body, "Department", department)
        _add(body, "AccountId", account_id)
        _add(body, "MailingStreet", mailing_street)
        _add(body, "MailingCity", mailing_city)
        _add(body, "MailingState", mailing_state)
        _add(body, "MailingPostalCode", mailing_postal_code)
        _add(body, "MailingCountry", mailing_country)
        _add(body, "OwnerId", owner_id)
        _add(body, "Description", description)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_create("Contact", body)

    @mcp.tool()
    async def sf_get_contact(
        contact_id: str,
        fields: list[str] | None = None,
    ) -> str:
        """Get a Salesforce Contact by ID.
        Args:
            contact_id: Contact ID
            fields: Specific fields to retrieve
        """
        return await _sobject_get(
            "Contact", contact_id, fields,
        )

    @mcp.tool()
    async def sf_update_contact(
        contact_id: str,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        mobile_phone: str | None = None,
        title: str | None = None,
        department: str | None = None,
        account_id: str | None = None,
        owner_id: str | None = None,
        description: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Update a Salesforce Contact.
        Args:
            contact_id: Contact ID
            first_name: Updated first name
            last_name: Updated last name
            email: Updated email
            phone: Updated phone
            mobile_phone: Updated mobile
            title: Updated title
            department: Updated department
            account_id: Updated account association
            owner_id: Updated owner
            description: Updated description
            custom_fields: Additional fields
        """
        body: dict = {}
        _add(body, "FirstName", first_name)
        _add(body, "LastName", last_name)
        _add(body, "Email", email)
        _add(body, "Phone", phone)
        _add(body, "MobilePhone", mobile_phone)
        _add(body, "Title", title)
        _add(body, "Department", department)
        _add(body, "AccountId", account_id)
        _add(body, "OwnerId", owner_id)
        _add(body, "Description", description)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_update(
            "Contact", contact_id, body,
        )

    @mcp.tool()
    async def sf_delete_contact(contact_id: str) -> str:
        """Delete a Salesforce Contact.
        Args:
            contact_id: Contact ID to delete
        """
        return await _sobject_delete(
            "Contact", contact_id,
        )

    @mcp.tool()
    async def sf_list_contacts(
        limit: int = 20,
        offset: int = 0,
        order_by: str = "LastName",
        order_dir: str = "ASC",
        account_id: str | None = None,
        email: str | None = None,
        name_like: str | None = None,
        owner_id: str | None = None,
        fields: list[str] | None = None,
    ) -> str:
        """List Salesforce Contacts with filters.
        Args:
            limit: Max records (default 20, max 2000)
            offset: Records to skip
            order_by: Sort field (default LastName)
            order_dir: ASC or DESC
            account_id: Filter by Account ID
            email: Filter by exact email
            name_like: Filter: Name contains string
            owner_id: Filter by owner
            fields: Fields to return
        """
        default = [
            "Id", "FirstName", "LastName", "Email",
            "Phone", "AccountId", "Title",
        ]
        filt: dict[str, object] = {}
        if account_id is not None:
            filt["AccountId"] = account_id
        if email is not None:
            filt["Email"] = email
        if owner_id is not None:
            filt["OwnerId"] = owner_id
        like: dict[str, str] = {}
        if name_like is not None:
            like["Name"] = name_like
        return await _sobject_list(
            "Contact", fields or [], default, filt,
            order_by, order_dir, limit, offset,
            like_filters=like or None,
        )

    @mcp.tool()
    async def sf_upsert_contact(
        external_id_field: str,
        external_id_value: str,
        last_name: str | None = None,
        first_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        account_id: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Upsert a Salesforce Contact by external ID.
        Args:
            external_id_field: External ID field API name
            external_id_value: External ID value
            last_name: Last name
            first_name: First name
            email: Email
            phone: Phone
            account_id: Account ID
            custom_fields: Additional fields
        """
        body: dict = {}
        _add(body, "LastName", last_name)
        _add(body, "FirstName", first_name)
        _add(body, "Email", email)
        _add(body, "Phone", phone)
        _add(body, "AccountId", account_id)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_upsert(
            "Contact", external_id_field,
            external_id_value, body,
        )

    # ===================================================
    # TIER 3: OPPORTUNITY SOBJECT (6 tools)
    # ===================================================

    @mcp.tool()
    async def sf_create_opportunity(
        name: str,
        stage_name: str,
        close_date: str,
        account_id: str | None = None,
        amount: float | None = None,
        probability: float | None = None,
        type: str | None = None,
        lead_source: str | None = None,
        description: str | None = None,
        owner_id: str | None = None,
        next_step: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Create a Salesforce Opportunity.
        Args:
            name: Opportunity name
            stage_name: Current stage (must match org values)
            close_date: Expected close date (YYYY-MM-DD)
            account_id: Associated Account ID
            amount: Deal amount
            probability: Win probability (0-100)
            type: Opportunity type
            lead_source: Lead source
            description: Description
            owner_id: Owner user ID
            next_step: Next step description
            custom_fields: Additional fields
        """
        body: dict = {
            "Name": name,
            "StageName": stage_name,
            "CloseDate": close_date,
        }
        _add(body, "AccountId", account_id)
        _add(body, "Amount", amount)
        _add(body, "Probability", probability)
        _add(body, "Type", type)
        _add(body, "LeadSource", lead_source)
        _add(body, "Description", description)
        _add(body, "OwnerId", owner_id)
        _add(body, "NextStep", next_step)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_create("Opportunity", body)

    @mcp.tool()
    async def sf_get_opportunity(
        opportunity_id: str,
        fields: list[str] | None = None,
    ) -> str:
        """Get a Salesforce Opportunity by ID.
        Args:
            opportunity_id: Opportunity ID
            fields: Specific fields to retrieve
        """
        return await _sobject_get(
            "Opportunity", opportunity_id, fields,
        )

    @mcp.tool()
    async def sf_update_opportunity(
        opportunity_id: str,
        name: str | None = None,
        stage_name: str | None = None,
        close_date: str | None = None,
        amount: float | None = None,
        probability: float | None = None,
        type: str | None = None,
        description: str | None = None,
        owner_id: str | None = None,
        next_step: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Update a Salesforce Opportunity.
        Args:
            opportunity_id: Opportunity ID
            name: Updated name
            stage_name: Updated stage
            close_date: Updated close date
            amount: Updated amount
            probability: Updated probability
            type: Updated type
            description: Updated description
            owner_id: Updated owner
            next_step: Updated next step
            custom_fields: Additional fields
        """
        body: dict = {}
        _add(body, "Name", name)
        _add(body, "StageName", stage_name)
        _add(body, "CloseDate", close_date)
        _add(body, "Amount", amount)
        _add(body, "Probability", probability)
        _add(body, "Type", type)
        _add(body, "Description", description)
        _add(body, "OwnerId", owner_id)
        _add(body, "NextStep", next_step)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_update(
            "Opportunity", opportunity_id, body,
        )

    @mcp.tool()
    async def sf_delete_opportunity(
        opportunity_id: str,
    ) -> str:
        """Delete a Salesforce Opportunity.
        Args:
            opportunity_id: Opportunity ID
        """
        return await _sobject_delete(
            "Opportunity", opportunity_id,
        )

    @mcp.tool()
    async def sf_list_opportunities(
        limit: int = 20,
        offset: int = 0,
        order_by: str = "CloseDate",
        order_dir: str = "ASC",
        account_id: str | None = None,
        stage_name: str | None = None,
        owner_id: str | None = None,
        close_date_gte: str | None = None,
        close_date_lte: str | None = None,
        amount_gte: float | None = None,
        amount_lte: float | None = None,
        fields: list[str] | None = None,
    ) -> str:
        """List Salesforce Opportunities with filters.
        Args:
            limit: Max records (default 20, max 2000)
            offset: Records to skip
            order_by: Sort field (default CloseDate)
            order_dir: ASC or DESC
            account_id: Filter by Account ID
            stage_name: Filter by exact stage
            owner_id: Filter by owner
            close_date_gte: Filter: close date >= (YYYY-MM-DD)
            close_date_lte: Filter: close date <= (YYYY-MM-DD)
            amount_gte: Filter: amount >=
            amount_lte: Filter: amount <=
            fields: Fields to return
        """
        default = [
            "Id", "Name", "StageName", "Amount",
            "CloseDate", "AccountId", "Probability",
        ]
        filt: dict[str, object] = {}
        if account_id is not None:
            filt["AccountId"] = account_id
        if stage_name is not None:
            filt["StageName"] = stage_name
        if owner_id is not None:
            filt["OwnerId"] = owner_id
        gte: dict[str, object] = {}
        lte: dict[str, object] = {}
        if close_date_gte is not None:
            gte["CloseDate"] = close_date_gte
        if close_date_lte is not None:
            lte["CloseDate"] = close_date_lte
        if amount_gte is not None:
            gte["Amount"] = amount_gte
        if amount_lte is not None:
            lte["Amount"] = amount_lte
        return await _sobject_list(
            "Opportunity", fields or [], default, filt,
            order_by, order_dir, limit, offset,
            gte_filters=gte or None,
            lte_filters=lte or None,
        )

    @mcp.tool()
    async def sf_upsert_opportunity(
        external_id_field: str,
        external_id_value: str,
        name: str | None = None,
        stage_name: str | None = None,
        close_date: str | None = None,
        amount: float | None = None,
        account_id: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Upsert a Salesforce Opportunity by external ID.
        Args:
            external_id_field: External ID field API name
            external_id_value: External ID value
            name: Opportunity name
            stage_name: Stage
            close_date: Close date
            amount: Amount
            account_id: Account ID
            custom_fields: Additional fields
        """
        body: dict = {}
        _add(body, "Name", name)
        _add(body, "StageName", stage_name)
        _add(body, "CloseDate", close_date)
        _add(body, "Amount", amount)
        _add(body, "AccountId", account_id)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_upsert(
            "Opportunity", external_id_field,
            external_id_value, body,
        )

    # ===================================================
    # TIER 4: LEAD SOBJECT (6 tools)
    # ===================================================

    @mcp.tool()
    async def sf_create_lead(
        last_name: str,
        company: str,
        first_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        title: str | None = None,
        status: str | None = None,
        lead_source: str | None = None,
        industry: str | None = None,
        annual_revenue: float | None = None,
        number_of_employees: int | None = None,
        street: str | None = None,
        city: str | None = None,
        state: str | None = None,
        postal_code: str | None = None,
        country: str | None = None,
        description: str | None = None,
        owner_id: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Create a Salesforce Lead.
        Args:
            last_name: Last name (required)
            company: Company name (required)
            first_name: First name
            email: Email
            phone: Phone
            title: Job title
            status: Lead status picklist value
            lead_source: Lead source
            industry: Industry
            annual_revenue: Annual revenue
            number_of_employees: Employee count
            street: Street address
            city: City
            state: State
            postal_code: Postal code
            country: Country
            description: Description
            owner_id: Owner user ID
            custom_fields: Additional fields
        """
        body: dict = {
            "LastName": last_name,
            "Company": company,
        }
        _add(body, "FirstName", first_name)
        _add(body, "Email", email)
        _add(body, "Phone", phone)
        _add(body, "Title", title)
        _add(body, "Status", status)
        _add(body, "LeadSource", lead_source)
        _add(body, "Industry", industry)
        _add(body, "AnnualRevenue", annual_revenue)
        _add(body, "NumberOfEmployees", number_of_employees)
        _add(body, "Street", street)
        _add(body, "City", city)
        _add(body, "State", state)
        _add(body, "PostalCode", postal_code)
        _add(body, "Country", country)
        _add(body, "Description", description)
        _add(body, "OwnerId", owner_id)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_create("Lead", body)

    @mcp.tool()
    async def sf_get_lead(
        lead_id: str,
        fields: list[str] | None = None,
    ) -> str:
        """Get a Salesforce Lead by ID.
        Args:
            lead_id: Lead ID
            fields: Specific fields to retrieve
        """
        return await _sobject_get("Lead", lead_id, fields)

    @mcp.tool()
    async def sf_update_lead(
        lead_id: str,
        first_name: str | None = None,
        last_name: str | None = None,
        company: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        title: str | None = None,
        status: str | None = None,
        lead_source: str | None = None,
        description: str | None = None,
        owner_id: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Update a Salesforce Lead.
        Args:
            lead_id: Lead ID
            first_name: Updated first name
            last_name: Updated last name
            company: Updated company
            email: Updated email
            phone: Updated phone
            title: Updated title
            status: Updated status
            lead_source: Updated lead source
            description: Updated description
            owner_id: Updated owner
            custom_fields: Additional fields
        """
        body: dict = {}
        _add(body, "FirstName", first_name)
        _add(body, "LastName", last_name)
        _add(body, "Company", company)
        _add(body, "Email", email)
        _add(body, "Phone", phone)
        _add(body, "Title", title)
        _add(body, "Status", status)
        _add(body, "LeadSource", lead_source)
        _add(body, "Description", description)
        _add(body, "OwnerId", owner_id)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_update("Lead", lead_id, body)

    @mcp.tool()
    async def sf_delete_lead(lead_id: str) -> str:
        """Delete a Salesforce Lead.
        Args:
            lead_id: Lead ID to delete
        """
        return await _sobject_delete("Lead", lead_id)

    @mcp.tool()
    async def sf_list_leads(
        limit: int = 20,
        offset: int = 0,
        order_by: str = "CreatedDate",
        order_dir: str = "ASC",
        status: str | None = None,
        owner_id: str | None = None,
        company: str | None = None,
        is_converted: bool | None = None,
        lead_source: str | None = None,
        fields: list[str] | None = None,
    ) -> str:
        """List Salesforce Leads with filters.
        Args:
            limit: Max records (default 20, max 2000)
            offset: Records to skip
            order_by: Sort field (default CreatedDate)
            order_dir: ASC or DESC
            status: Filter by status
            owner_id: Filter by owner
            company: Filter by exact company
            is_converted: Filter by conversion status
            lead_source: Filter by lead source
            fields: Fields to return
        """
        default = [
            "Id", "FirstName", "LastName", "Email",
            "Company", "Status", "LeadSource",
        ]
        filt: dict[str, object] = {}
        if status is not None:
            filt["Status"] = status
        if owner_id is not None:
            filt["OwnerId"] = owner_id
        if company is not None:
            filt["Company"] = company
        if is_converted is not None:
            filt["IsConverted"] = is_converted
        if lead_source is not None:
            filt["LeadSource"] = lead_source
        return await _sobject_list(
            "Lead", fields or [], default, filt,
            order_by, order_dir, limit, offset,
        )

    @mcp.tool()
    async def sf_convert_lead(
        lead_id: str,
        converted_status: str,
        account_id: str | None = None,
        contact_id: str | None = None,
        opportunity_name: str | None = None,
        do_not_create_opportunity: bool | None = None,
        owner_id: str | None = None,
    ) -> str:
        """Convert a Lead to Account, Contact, and Opportunity.
        Args:
            lead_id: Lead ID to convert
            converted_status: Status representing converted
            account_id: Existing Account to merge into
            contact_id: Existing Contact to merge into
            opportunity_name: Name for new Opportunity
            do_not_create_opportunity: Skip Opportunity creation
            owner_id: Owner for new records
        """
        inp: dict = {
            "leadId": lead_id,
            "convertedStatus": converted_status,
        }
        _add(inp, "accountId", account_id)
        _add(inp, "contactId", contact_id)
        _add(inp, "opportunityName", opportunity_name)
        if do_not_create_opportunity is not None:
            inp["createOpportunity"] = (
                not do_not_create_opportunity
            )
        _add(inp, "ownerId", owner_id)
        data = await _req(
            "POST",
            "actions/standard/convertLead",
            json_body={"inputs": [inp]},
        )
        return _success(200, data=data)

    # ===================================================
    # TIER 5: CASE SOBJECT (6 tools)
    # ===================================================

    @mcp.tool()
    async def sf_create_case(
        subject: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        origin: str | None = None,
        type: str | None = None,
        account_id: str | None = None,
        contact_id: str | None = None,
        owner_id: str | None = None,
        reason: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Create a Salesforce Case.
        Args:
            subject: Case subject
            description: Case description
            status: Case status (New, Working, Closed)
            priority: Priority (High, Medium, Low)
            origin: Case origin (Phone, Email, Web)
            type: Case type
            account_id: Associated Account ID
            contact_id: Associated Contact ID
            owner_id: Owner user ID
            reason: Case reason
            custom_fields: Additional fields
        """
        body: dict = {}
        _add(body, "Subject", subject)
        _add(body, "Description", description)
        _add(body, "Status", status)
        _add(body, "Priority", priority)
        _add(body, "Origin", origin)
        _add(body, "Type", type)
        _add(body, "AccountId", account_id)
        _add(body, "ContactId", contact_id)
        _add(body, "OwnerId", owner_id)
        _add(body, "Reason", reason)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_create("Case", body)

    @mcp.tool()
    async def sf_get_case(
        case_id: str,
        fields: list[str] | None = None,
    ) -> str:
        """Get a Salesforce Case by ID.
        Args:
            case_id: Case ID
            fields: Specific fields to retrieve
        """
        return await _sobject_get("Case", case_id, fields)

    @mcp.tool()
    async def sf_update_case(
        case_id: str,
        subject: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        origin: str | None = None,
        type: str | None = None,
        owner_id: str | None = None,
        reason: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Update a Salesforce Case.
        Args:
            case_id: Case ID
            subject: Updated subject
            description: Updated description
            status: Updated status
            priority: Updated priority
            origin: Updated origin
            type: Updated type
            owner_id: Updated owner
            reason: Updated reason
            custom_fields: Additional fields
        """
        body: dict = {}
        _add(body, "Subject", subject)
        _add(body, "Description", description)
        _add(body, "Status", status)
        _add(body, "Priority", priority)
        _add(body, "Origin", origin)
        _add(body, "Type", type)
        _add(body, "OwnerId", owner_id)
        _add(body, "Reason", reason)
        if custom_fields:
            body.update(custom_fields)
        return await _sobject_update("Case", case_id, body)

    @mcp.tool()
    async def sf_delete_case(case_id: str) -> str:
        """Delete a Salesforce Case.
        Args:
            case_id: Case ID to delete
        """
        return await _sobject_delete("Case", case_id)

    @mcp.tool()
    async def sf_list_cases(
        limit: int = 20,
        offset: int = 0,
        order_by: str = "CreatedDate",
        order_dir: str = "DESC",
        status: str | None = None,
        priority: str | None = None,
        account_id: str | None = None,
        contact_id: str | None = None,
        owner_id: str | None = None,
        fields: list[str] | None = None,
    ) -> str:
        """List Salesforce Cases with filters.
        Args:
            limit: Max records (default 20, max 2000)
            offset: Records to skip
            order_by: Sort field (default CreatedDate)
            order_dir: ASC or DESC (default DESC)
            status: Filter by status
            priority: Filter by priority
            account_id: Filter by Account
            contact_id: Filter by Contact
            owner_id: Filter by owner
            fields: Fields to return
        """
        default = [
            "Id", "Subject", "Status", "Priority",
            "AccountId", "ContactId", "CreatedDate",
        ]
        filt: dict[str, object] = {}
        if status is not None:
            filt["Status"] = status
        if priority is not None:
            filt["Priority"] = priority
        if account_id is not None:
            filt["AccountId"] = account_id
        if contact_id is not None:
            filt["ContactId"] = contact_id
        if owner_id is not None:
            filt["OwnerId"] = owner_id
        return await _sobject_list(
            "Case", fields or [], default, filt,
            order_by, order_dir, limit, offset,
        )

    @mcp.tool()
    async def sf_add_case_comment(
        case_id: str,
        body: str,
        is_published: bool = False,
    ) -> str:
        """Add a comment to a Salesforce Case.
        Args:
            case_id: Parent Case ID
            body: Comment text
            is_published: Visible to customer in portal
        """
        payload: dict = {
            "ParentId": case_id,
            "CommentBody": body,
            "IsPublished": is_published,
        }
        data = await _req(
            "POST", "sobjects/CaseComment/",
            json_body=payload,
        )
        return _success(201, data=data)

    # ===================================================
    # TIER 6: TASK SOBJECT (5 tools)
    # ===================================================

    @mcp.tool()
    async def sf_create_task(
        subject: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        activity_date: str | None = None,
        who_id: str | None = None,
        what_id: str | None = None,
        description: str | None = None,
        owner_id: str | None = None,
        is_reminder_set: bool | None = None,
        reminder_date_time: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Create a Salesforce Task.
        Args:
            subject: Task subject
            status: Status (Not Started, In Progress, Completed)
            priority: Priority (High, Normal, Low)
            activity_date: Due date (YYYY-MM-DD)
            who_id: Related Contact or Lead ID
            what_id: Related Account/Opportunity ID
            description: Task description
            owner_id: Owner user ID
            is_reminder_set: Enable reminder
            reminder_date_time: Reminder datetime (ISO 8601)
            custom_fields: Additional fields
        """
        b: dict = {}
        _add(b, "Subject", subject)
        _add(b, "Status", status)
        _add(b, "Priority", priority)
        _add(b, "ActivityDate", activity_date)
        _add(b, "WhoId", who_id)
        _add(b, "WhatId", what_id)
        _add(b, "Description", description)
        _add(b, "OwnerId", owner_id)
        _add(b, "IsReminderSet", is_reminder_set)
        _add(b, "ReminderDateTime", reminder_date_time)
        if custom_fields:
            b.update(custom_fields)
        return await _sobject_create("Task", b)

    @mcp.tool()
    async def sf_get_task(
        task_id: str,
        fields: list[str] | None = None,
    ) -> str:
        """Get a Salesforce Task by ID.
        Args:
            task_id: Task ID
            fields: Specific fields to retrieve
        """
        return await _sobject_get("Task", task_id, fields)

    @mcp.tool()
    async def sf_update_task(
        task_id: str,
        subject: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        activity_date: str | None = None,
        description: str | None = None,
        owner_id: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Update a Salesforce Task.
        Args:
            task_id: Task ID
            subject: Updated subject
            status: Updated status
            priority: Updated priority
            activity_date: Updated due date
            description: Updated description
            owner_id: Updated owner
            custom_fields: Additional fields
        """
        b: dict = {}
        _add(b, "Subject", subject)
        _add(b, "Status", status)
        _add(b, "Priority", priority)
        _add(b, "ActivityDate", activity_date)
        _add(b, "Description", description)
        _add(b, "OwnerId", owner_id)
        if custom_fields:
            b.update(custom_fields)
        return await _sobject_update("Task", task_id, b)

    @mcp.tool()
    async def sf_delete_task(task_id: str) -> str:
        """Delete a Salesforce Task.
        Args:
            task_id: Task ID to delete
        """
        return await _sobject_delete("Task", task_id)

    @mcp.tool()
    async def sf_list_tasks(
        limit: int = 20,
        offset: int = 0,
        order_by: str = "ActivityDate",
        order_dir: str = "ASC",
        status: str | None = None,
        priority: str | None = None,
        who_id: str | None = None,
        what_id: str | None = None,
        owner_id: str | None = None,
        fields: list[str] | None = None,
    ) -> str:
        """List Salesforce Tasks with filters.
        Args:
            limit: Max records (default 20, max 2000)
            offset: Records to skip
            order_by: Sort field (default ActivityDate)
            order_dir: ASC or DESC
            status: Filter by status
            priority: Filter by priority
            who_id: Filter by related Contact/Lead
            what_id: Filter by related object
            owner_id: Filter by owner
            fields: Fields to return
        """
        default = [
            "Id", "Subject", "Status", "Priority",
            "ActivityDate", "WhoId", "WhatId",
        ]
        filt: dict[str, object] = {}
        if status is not None:
            filt["Status"] = status
        if priority is not None:
            filt["Priority"] = priority
        if who_id is not None:
            filt["WhoId"] = who_id
        if what_id is not None:
            filt["WhatId"] = what_id
        if owner_id is not None:
            filt["OwnerId"] = owner_id
        return await _sobject_list(
            "Task", fields or [], default, filt,
            order_by, order_dir, limit, offset,
        )

    # ===================================================
    # TIER 7: EVENT SOBJECT (5 tools)
    # ===================================================

    @mcp.tool()
    async def sf_create_event(
        start_date_time: str,
        end_date_time: str,
        subject: str | None = None,
        is_all_day_event: bool | None = None,
        activity_date: str | None = None,
        location: str | None = None,
        who_id: str | None = None,
        what_id: str | None = None,
        description: str | None = None,
        owner_id: str | None = None,
        show_as: str | None = None,
        is_private: bool | None = None,
        is_reminder_set: bool | None = None,
        reminder_date_time: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Create a Salesforce Event.
        Args:
            start_date_time: Start datetime (ISO 8601)
            end_date_time: End datetime (ISO 8601)
            subject: Event subject
            is_all_day_event: All-day event flag
            activity_date: Date for all-day events (YYYY-MM-DD)
            location: Event location
            who_id: Related Contact or Lead ID
            what_id: Related Account/Opportunity ID
            description: Event description
            owner_id: Owner user ID
            show_as: Calendar display (Busy, Free, OutOfOffice)
            is_private: Private event
            is_reminder_set: Enable reminder
            reminder_date_time: Reminder datetime
            custom_fields: Additional fields
        """
        b: dict = {
            "StartDateTime": start_date_time,
            "EndDateTime": end_date_time,
        }
        _add(b, "Subject", subject)
        _add(b, "IsAllDayEvent", is_all_day_event)
        _add(b, "ActivityDate", activity_date)
        _add(b, "Location", location)
        _add(b, "WhoId", who_id)
        _add(b, "WhatId", what_id)
        _add(b, "Description", description)
        _add(b, "OwnerId", owner_id)
        _add(b, "ShowAs", show_as)
        _add(b, "IsPrivate", is_private)
        _add(b, "IsReminderSet", is_reminder_set)
        _add(b, "ReminderDateTime", reminder_date_time)
        if custom_fields:
            b.update(custom_fields)
        return await _sobject_create("Event", b)

    @mcp.tool()
    async def sf_get_event(
        event_id: str,
        fields: list[str] | None = None,
    ) -> str:
        """Get a Salesforce Event by ID.
        Args:
            event_id: Event ID
            fields: Specific fields to retrieve
        """
        return await _sobject_get(
            "Event", event_id, fields,
        )

    @mcp.tool()
    async def sf_update_event(
        event_id: str,
        subject: str | None = None,
        start_date_time: str | None = None,
        end_date_time: str | None = None,
        location: str | None = None,
        description: str | None = None,
        owner_id: str | None = None,
        show_as: str | None = None,
        custom_fields: dict | None = None,
    ) -> str:
        """Update a Salesforce Event.
        Args:
            event_id: Event ID
            subject: Updated subject
            start_date_time: Updated start
            end_date_time: Updated end
            location: Updated location
            description: Updated description
            owner_id: Updated owner
            show_as: Updated calendar display
            custom_fields: Additional fields
        """
        b: dict = {}
        _add(b, "Subject", subject)
        _add(b, "StartDateTime", start_date_time)
        _add(b, "EndDateTime", end_date_time)
        _add(b, "Location", location)
        _add(b, "Description", description)
        _add(b, "OwnerId", owner_id)
        _add(b, "ShowAs", show_as)
        if custom_fields:
            b.update(custom_fields)
        return await _sobject_update(
            "Event", event_id, b,
        )

    @mcp.tool()
    async def sf_delete_event(event_id: str) -> str:
        """Delete a Salesforce Event.
        Args:
            event_id: Event ID to delete
        """
        return await _sobject_delete("Event", event_id)

    @mcp.tool()
    async def sf_list_events(
        limit: int = 20,
        offset: int = 0,
        order_by: str = "StartDateTime",
        order_dir: str = "ASC",
        who_id: str | None = None,
        what_id: str | None = None,
        owner_id: str | None = None,
        start_date_gte: str | None = None,
        start_date_lte: str | None = None,
        fields: list[str] | None = None,
    ) -> str:
        """List Salesforce Events with filters.
        Args:
            limit: Max records (default 20, max 2000)
            offset: Records to skip
            order_by: Sort field (default StartDateTime)
            order_dir: ASC or DESC
            who_id: Filter by related Contact/Lead
            what_id: Filter by related object
            owner_id: Filter by owner
            start_date_gte: Filter: start >= (ISO datetime)
            start_date_lte: Filter: start <= (ISO datetime)
            fields: Fields to return
        """
        default = [
            "Id", "Subject", "StartDateTime",
            "EndDateTime", "Location", "WhoId", "WhatId",
        ]
        filt: dict[str, object] = {}
        if who_id is not None:
            filt["WhoId"] = who_id
        if what_id is not None:
            filt["WhatId"] = what_id
        if owner_id is not None:
            filt["OwnerId"] = owner_id
        gte: dict[str, object] = {}
        lte: dict[str, object] = {}
        if start_date_gte is not None:
            gte["StartDateTime"] = start_date_gte
        if start_date_lte is not None:
            lte["StartDateTime"] = start_date_lte
        return await _sobject_list(
            "Event", fields or [], default, filt,
            order_by, order_dir, limit, offset,
            gte_filters=gte or None,
            lte_filters=lte or None,
        )

    # ===================================================
    # TIER 8: SOQL QUERIES (3 tools)
    # ===================================================

    @mcp.tool()
    async def sf_query(query: str) -> str:
        """Execute an arbitrary SOQL query.
        Args:
            query: Full SOQL query string
        """
        data = await _req(
            "GET", "query/", params={"q": query},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sf_query_more(
        next_records_url: str,
    ) -> str:
        """Retrieve the next page of a SOQL query result.
        Args:
            next_records_url: nextRecordsUrl from previous response
        """
        data = await _req(
            "GET", "", raw_url=next_records_url,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sf_query_all(query: str) -> str:
        """Execute SOQL query including deleted/archived records.
        Args:
            query: SOQL query string
        """
        data = await _req(
            "GET", "queryAll/", params={"q": query},
        )
        return _success(200, data=data)

    # ===================================================
    # TIER 9: SOSL SEARCH (1 tool)
    # ===================================================

    @mcp.tool()
    async def sf_search(search: str) -> str:
        """Execute a SOSL full-text search across objects.
        Args:
            search: SOSL search string (e.g. FIND {john} ...)
        """
        data = await _req(
            "GET", "search/", params={"q": search},
        )
        return _success(200, data=data)

    # ===================================================
    # TIER 10: DESCRIBE / METADATA (4 tools)
    # ===================================================

    @mcp.tool()
    async def sf_describe_sobject(
        sobject_name: str,
    ) -> str:
        """Get full metadata for an SObject (fields, picklists,
        record types, relationships).
        Args:
            sobject_name: SObject API name (e.g. Account)
        """
        data = await _req(
            "GET", f"sobjects/{sobject_name}/describe/",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sf_describe_global() -> str:
        """List all SObjects available in the org."""
        data = await _req("GET", "sobjects/")
        return _success(200, data=data)

    @mcp.tool()
    async def sf_get_record_types(
        sobject_name: str,
    ) -> str:
        """Get record types for an SObject.
        Args:
            sobject_name: SObject API name
        """
        data = await _req(
            "GET", f"sobjects/{sobject_name}/describe/",
        )
        rts = []
        if isinstance(data, dict):
            rts = data.get("recordTypeInfos", [])
        return _success(200, data=rts)

    @mcp.tool()
    async def sf_get_picklist_values(
        sobject_name: str,
        field_name: str,
    ) -> str:
        """Get valid picklist values for a field.
        Args:
            sobject_name: SObject API name
            field_name: Field API name (e.g. Industry)
        """
        data = await _req(
            "GET", f"sobjects/{sobject_name}/describe/",
        )
        if isinstance(data, dict):
            for f in data.get("fields", []):
                if f.get("name") == field_name:
                    return _success(
                        200,
                        data=f.get("picklistValues", []),
                    )
        raise ToolError(
            f"Field '{field_name}' not found on "
            f"'{sobject_name}'."
        )

    # ===================================================
    # TIER 11: GENERIC SOBJECT CRUD (5 tools)
    # ===================================================

    @mcp.tool()
    async def sf_create_record(
        sobject_name: str,
        fields: dict,
    ) -> str:
        """Create a record of any SObject type.
        Args:
            sobject_name: SObject API name
            fields: Field name-value pairs
        """
        return await _sobject_create(sobject_name, fields)

    @mcp.tool()
    async def sf_get_record(
        sobject_name: str,
        record_id: str,
        fields: list[str] | None = None,
    ) -> str:
        """Get a record of any SObject type by ID.
        Args:
            sobject_name: SObject API name
            record_id: Record ID
            fields: Specific fields to retrieve
        """
        return await _sobject_get(
            sobject_name, record_id, fields,
        )

    @mcp.tool()
    async def sf_update_record(
        sobject_name: str,
        record_id: str,
        fields: dict,
    ) -> str:
        """Update a record of any SObject type.
        Args:
            sobject_name: SObject API name
            record_id: Record ID
            fields: Field name-value pairs to update
        """
        return await _sobject_update(
            sobject_name, record_id, fields,
        )

    @mcp.tool()
    async def sf_delete_record(
        sobject_name: str,
        record_id: str,
    ) -> str:
        """Delete a record of any SObject type.
        Args:
            sobject_name: SObject API name
            record_id: Record ID
        """
        return await _sobject_delete(
            sobject_name, record_id,
        )

    @mcp.tool()
    async def sf_upsert_record(
        sobject_name: str,
        external_id_field: str,
        external_id_value: str,
        fields: dict,
    ) -> str:
        """Upsert any SObject using an external ID.
        Args:
            sobject_name: SObject API name
            external_id_field: External ID field API name
            external_id_value: External ID value
            fields: Field name-value pairs
        """
        return await _sobject_upsert(
            sobject_name, external_id_field,
            external_id_value, fields,
        )

    # ===================================================
    # TIER 12: BULK OPERATIONS (4 tools)
    # ===================================================

    @mcp.tool()
    async def sf_bulk_create_job(
        sobject_name: str,
        operation: str,
        external_id_field: str | None = None,
        line_ending: str = "LF",
        column_delimiter: str = "COMMA",
    ) -> str:
        """Create a Bulk API 2.0 ingest job.
        Args:
            sobject_name: SObject API name
            operation: insert, update, upsert, delete, hardDelete
            external_id_field: Required for upsert
            line_ending: CRLF or LF (default LF)
            column_delimiter: COMMA, TAB, PIPE, etc.
        """
        body: dict = {
            "object": sobject_name,
            "operation": operation,
            "contentType": "CSV",
            "lineEnding": line_ending,
            "columnDelimiter": column_delimiter,
        }
        if external_id_field is not None:
            body["externalIdFieldName"] = external_id_field
        data = await _req(
            "POST", "jobs/ingest/", json_body=body,
        )
        return _success(201, data=data)

    @mcp.tool()
    async def sf_bulk_upload_data(
        job_id: str,
        csv_data: str,
    ) -> str:
        """Upload CSV data to an open Bulk API 2.0 job.
        Args:
            job_id: Bulk job ID
            csv_data: CSV content with header row
        """
        await _req(
            "PUT",
            f"jobs/ingest/{job_id}/batches",
            content=csv_data,
            content_type="text/csv",
        )
        return _success(201)

    @mcp.tool()
    async def sf_bulk_close_job(
        job_id: str,
        state: str = "UploadComplete",
    ) -> str:
        """Close or abort a Bulk API 2.0 job.
        Args:
            job_id: Bulk job ID
            state: UploadComplete (process) or Aborted (cancel)
        """
        data = await _req(
            "PATCH",
            f"jobs/ingest/{job_id}",
            json_body={"state": state},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sf_bulk_get_job_status(
        job_id: str,
        result_type: str | None = None,
    ) -> str:
        """Get status/results of a Bulk API 2.0 job.
        Args:
            job_id: Bulk job ID
            result_type: successfulResults, failedResults,
                or unprocessedrecords (omit for status only)
        """
        if result_type is not None:
            path = f"jobs/ingest/{job_id}/{result_type}"
        else:
            path = f"jobs/ingest/{job_id}"
        data = await _req("GET", path)
        return _success(200, data=data)

    # ===================================================
    # TIER 13: COMPOSITE REQUESTS (2 tools)
    # ===================================================

    @mcp.tool()
    async def sf_composite(
        composite_request: list[dict],
        all_or_none: bool = False,
    ) -> str:
        """Execute multiple API requests in one call (max 25).
        Subrequests can reference each other via @{refId.field}.
        Args:
            composite_request: Array of subrequests, each with
                method, url, referenceId, and optional body
            all_or_none: Rollback all on any failure
        """
        data = await _req(
            "POST",
            "composite/",
            json_body={
                "allOrNone": all_or_none,
                "compositeRequest": composite_request,
            },
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sf_composite_batch(
        batch_requests: list[dict],
        halt_on_error: bool = False,
    ) -> str:
        """Execute multiple independent requests in one call
        (max 25, no cross-referencing).
        Args:
            batch_requests: Array of requests, each with
                method and url
            halt_on_error: Stop on first error
        """
        data = await _req(
            "POST",
            "composite/batch",
            json_body={
                "haltOnError": halt_on_error,
                "batchRequests": batch_requests,
            },
        )
        return _success(200, data=data)

    # ===================================================
    # TIER 14: REPORTS (3 tools)
    # ===================================================

    @mcp.tool()
    async def sf_list_reports(
        limit: int = 20,
        offset: int = 0,
        folder_id: str | None = None,
    ) -> str:
        """List available Salesforce reports.
        Args:
            limit: Max results (default 20)
            offset: Records to skip
            folder_id: Filter by report folder ID
        """
        fields = [
            "Id", "Name", "DeveloperName", "FolderName",
        ]
        filt: dict[str, object] = {}
        if folder_id is not None:
            filt["OwnerId"] = folder_id
        q = _build_soql(
            "Report", fields, filt,
            "Name", "ASC", limit, offset,
        )
        data = await _req(
            "GET", "query/", params={"q": q},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sf_run_report(
        report_id: str,
        include_details: bool = True,
        filters: list[dict] | None = None,
    ) -> str:
        """Execute a report and get results.
        Args:
            report_id: Report ID
            include_details: Include detail rows
            filters: Runtime filter overrides
        """
        body: dict | None = None
        if filters is not None:
            body = {
                "reportMetadata": {
                    "reportFilters": filters,
                },
            }
        params: dict[str, str] = {}
        if not include_details:
            params["includeDetails"] = "false"
        data = await _req(
            "POST",
            f"analytics/reports/{report_id}",
            json_body=body,
            params=params or None,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sf_describe_report(
        report_id: str,
    ) -> str:
        """Get report metadata without running it.
        Args:
            report_id: Report ID
        """
        data = await _req(
            "GET",
            f"analytics/reports/{report_id}/describe",
        )
        return _success(200, data=data)

    # ===================================================
    # TIER 15: MISCELLANEOUS (4 tools)
    # ===================================================

    @mcp.tool()
    async def sf_get_limits() -> str:
        """Get current org API usage limits."""
        data = await _req("GET", "limits/")
        return _success(200, data=data)

    @mcp.tool()
    async def sf_get_user(
        user_id: str,
        fields: list[str] | None = None,
    ) -> str:
        """Get details about a Salesforce user.
        Args:
            user_id: User ID (e.g. 005xx...)
            fields: Specific fields to retrieve
        """
        return await _sobject_get(
            "User", user_id, fields,
        )

    @mcp.tool()
    async def sf_get_current_user() -> str:
        """Get details about the authenticated user."""
        token, inst = await _get_token()
        if not _id_url:
            raise ToolError(
                "No identity URL available from token."
            )
        client = _get_client()
        resp = await client.get(
            _id_url,
            headers={
                "Authorization": f"Bearer {token}",
            },
            timeout=30.0,
        )
        if resp.status_code >= 400:
            raise ToolError(
                "Failed to get current user "
                f"({resp.status_code}): {resp.text}"
            )
        return _success(200, data=resp.json())

    @mcp.tool()
    async def sf_get_api_versions() -> str:
        """List available API versions on the instance."""
        token, inst = await _get_token()
        client = _get_client()
        resp = await client.get(
            f"{inst}/services/data/",
            headers={
                "Authorization": f"Bearer {token}",
            },
            timeout=30.0,
        )
        if resp.status_code >= 400:
            raise ToolError(
                "Failed to get API versions "
                f"({resp.status_code}): {resp.text}"
            )
        return _success(200, data=resp.json())
