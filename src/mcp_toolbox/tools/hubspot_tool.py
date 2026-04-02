"""HubSpot CRM integration — contacts, companies, deals, tickets, notes, associations."""

import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import HUBSPOT_API_TOKEN

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if not HUBSPOT_API_TOKEN:
        raise ToolError("HUBSPOT_API_TOKEN not configured.")
    if _client is None:
        _client = httpx.AsyncClient(
            base_url="https://api.hubapi.com",
            headers={"Authorization": f"Bearer {HUBSPOT_API_TOKEN}"},
            timeout=30.0,
        )
    return _client


def _success(sc: int, **kw) -> str:
    return json.dumps({"status": "success", "status_code": sc, **kw})


async def _request(method: str, path: str, **kwargs) -> dict | list:
    client = _get_client()
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"HubSpot request failed: {e}") from e
    if response.status_code == 429:
        raise ToolError("HubSpot rate limit exceeded.")
    if response.status_code >= 400:
        try:
            err = response.json()
            msg = err.get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(f"HubSpot error ({response.status_code}): {msg}")
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def _props(**kwargs) -> dict:
    """Build properties dict, filtering out None values."""
    return {k: v for k, v in kwargs.items() if v is not None}


async def _search(object_type: str, query: str | None, filter_groups: list | None,
                  sorts: list | None, properties: list | None,
                  limit: int, after: str | None) -> str:
    body: dict = {"limit": limit}
    if query:
        body["query"] = query
    if filter_groups:
        body["filterGroups"] = filter_groups
    if sorts:
        body["sorts"] = sorts
    if properties:
        body["properties"] = properties
    if after:
        body["after"] = after
    data = await _request("POST", f"/crm/v3/objects/{object_type}/search", json=body)
    results = data.get("results", []) if isinstance(data, dict) else data
    paging = data.get("paging", {}).get("next", {}) if isinstance(data, dict) else {}
    return _success(200, data=results, count=len(results),
                    after=paging.get("after"))


def register_tools(mcp: FastMCP) -> None:
    if not HUBSPOT_API_TOKEN:
        logger.warning("HUBSPOT_API_TOKEN not set — HubSpot tools will fail.")

    # === CONTACTS ===

    @mcp.tool()
    async def hubspot_create_contact(
        email: str, firstname: str | None = None, lastname: str | None = None,
        phone: str | None = None, company: str | None = None,
        extra_properties: dict | None = None,
    ) -> str:
        """Create a HubSpot contact.
        Args:
            email: Contact email
            firstname: First name
            lastname: Last name
            phone: Phone number
            company: Company name
            extra_properties: Additional properties
        """
        props = _props(email=email, firstname=firstname, lastname=lastname,
                       phone=phone, company=company)
        if extra_properties:
            props.update(extra_properties)
        data = await _request("POST", "/crm/v3/objects/contacts",
                              json={"properties": props})
        return _success(201, data=data)

    @mcp.tool()
    async def hubspot_get_contact(contact_id: str, properties: str | None = None) -> str:
        """Get a HubSpot contact.
        Args:
            contact_id: Contact ID
            properties: Comma-separated property names to return
        """
        params = {}
        if properties:
            params["properties"] = properties
        data = await _request("GET", f"/crm/v3/objects/contacts/{contact_id}",
                              params=params)
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_update_contact(
        contact_id: str, email: str | None = None,
        firstname: str | None = None, lastname: str | None = None,
        phone: str | None = None, extra_properties: dict | None = None,
    ) -> str:
        """Update a HubSpot contact.
        Args:
            contact_id: Contact ID
            email: New email
            firstname: New first name
            lastname: New last name
            phone: New phone
            extra_properties: Additional properties
        """
        props = _props(email=email, firstname=firstname, lastname=lastname, phone=phone)
        if extra_properties:
            props.update(extra_properties)
        if not props:
            raise ToolError("At least one property to update must be provided.")
        data = await _request("PATCH", f"/crm/v3/objects/contacts/{contact_id}",
                              json={"properties": props})
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_delete_contact(contact_id: str) -> str:
        """Archive a HubSpot contact.
        Args:
            contact_id: Contact ID
        """
        await _request("DELETE", f"/crm/v3/objects/contacts/{contact_id}")
        return _success(204, archived_id=contact_id)

    @mcp.tool()
    async def hubspot_list_contacts(
        limit: int = 10, after: str | None = None, properties: str | None = None,
    ) -> str:
        """List HubSpot contacts.
        Args:
            limit: Max results (default 10)
            after: Pagination cursor
            properties: Comma-separated properties to return
        """
        params: dict = {"limit": limit}
        if after:
            params["after"] = after
        if properties:
            params["properties"] = properties
        data = await _request("GET", "/crm/v3/objects/contacts", params=params)
        results = data.get("results", []) if isinstance(data, dict) else data
        paging = data.get("paging", {}).get("next", {}) if isinstance(data, dict) else {}
        return _success(200, data=results, count=len(results),
                        after=paging.get("after"))

    @mcp.tool()
    async def hubspot_search_contacts(
        query: str | None = None, filter_groups: list | None = None,
        sorts: list | None = None, properties: list | None = None,
        limit: int = 10, after: str | None = None,
    ) -> str:
        """Search HubSpot contacts.
        Args:
            query: Text search query
            filter_groups: Filter groups array
            sorts: Sort array
            properties: Properties to return
            limit: Max results (default 10)
            after: Pagination cursor
        """
        return await _search("contacts", query, filter_groups, sorts,
                             properties, limit, after)

    # === COMPANIES (same pattern) ===

    @mcp.tool()
    async def hubspot_create_company(
        name: str, domain: str | None = None, industry: str | None = None,
        phone: str | None = None, extra_properties: dict | None = None,
    ) -> str:
        """Create a HubSpot company.
        Args:
            name: Company name
            domain: Company domain
            industry: Industry
            phone: Phone
            extra_properties: Additional properties
        """
        props = _props(name=name, domain=domain, industry=industry, phone=phone)
        if extra_properties:
            props.update(extra_properties)
        data = await _request("POST", "/crm/v3/objects/companies",
                              json={"properties": props})
        return _success(201, data=data)

    @mcp.tool()
    async def hubspot_get_company(company_id: str, properties: str | None = None) -> str:
        """Get a HubSpot company.
        Args:
            company_id: Company ID
            properties: Comma-separated properties
        """
        params = {}
        if properties:
            params["properties"] = properties
        data = await _request("GET", f"/crm/v3/objects/companies/{company_id}",
                              params=params)
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_update_company(
        company_id: str, name: str | None = None, domain: str | None = None,
        industry: str | None = None, extra_properties: dict | None = None,
    ) -> str:
        """Update a HubSpot company.
        Args:
            company_id: Company ID
            name: New name
            domain: New domain
            industry: New industry
            extra_properties: Additional properties
        """
        props = _props(name=name, domain=domain, industry=industry)
        if extra_properties:
            props.update(extra_properties)
        if not props:
            raise ToolError("At least one property to update must be provided.")
        data = await _request("PATCH", f"/crm/v3/objects/companies/{company_id}",
                              json={"properties": props})
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_delete_company(company_id: str) -> str:
        """Archive a HubSpot company.
        Args:
            company_id: Company ID
        """
        await _request("DELETE", f"/crm/v3/objects/companies/{company_id}")
        return _success(204, archived_id=company_id)

    @mcp.tool()
    async def hubspot_list_companies(
        limit: int = 10, after: str | None = None, properties: str | None = None,
    ) -> str:
        """List HubSpot companies.
        Args:
            limit: Max results
            after: Pagination cursor
            properties: Comma-separated properties
        """
        params: dict = {"limit": limit}
        if after:
            params["after"] = after
        if properties:
            params["properties"] = properties
        data = await _request("GET", "/crm/v3/objects/companies", params=params)
        results = data.get("results", []) if isinstance(data, dict) else data
        paging = data.get("paging", {}).get("next", {}) if isinstance(data, dict) else {}
        return _success(200, data=results, count=len(results),
                        after=paging.get("after"))

    @mcp.tool()
    async def hubspot_search_companies(
        query: str | None = None, filter_groups: list | None = None,
        sorts: list | None = None, properties: list | None = None,
        limit: int = 10, after: str | None = None,
    ) -> str:
        """Search HubSpot companies.
        Args:
            query: Text search
            filter_groups: Filters
            sorts: Sort
            properties: Properties to return
            limit: Max results
            after: Cursor
        """
        return await _search("companies", query, filter_groups, sorts,
                             properties, limit, after)

    # === DEALS ===

    @mcp.tool()
    async def hubspot_create_deal(
        dealname: str, pipeline: str | None = None, dealstage: str | None = None,
        amount: str | None = None, closedate: str | None = None,
        extra_properties: dict | None = None,
    ) -> str:
        """Create a HubSpot deal.
        Args:
            dealname: Deal name
            pipeline: Pipeline ID
            dealstage: Stage ID
            amount: Deal amount
            closedate: Expected close date (YYYY-MM-DD)
            extra_properties: Additional properties
        """
        props = _props(dealname=dealname, pipeline=pipeline, dealstage=dealstage,
                       amount=amount, closedate=closedate)
        if extra_properties:
            props.update(extra_properties)
        data = await _request("POST", "/crm/v3/objects/deals",
                              json={"properties": props})
        return _success(201, data=data)

    @mcp.tool()
    async def hubspot_get_deal(deal_id: str, properties: str | None = None) -> str:
        """Get a HubSpot deal.
        Args:
            deal_id: Deal ID
            properties: Comma-separated properties
        """
        params = {}
        if properties:
            params["properties"] = properties
        data = await _request("GET", f"/crm/v3/objects/deals/{deal_id}", params=params)
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_update_deal(
        deal_id: str, dealname: str | None = None, dealstage: str | None = None,
        amount: str | None = None, extra_properties: dict | None = None,
    ) -> str:
        """Update a HubSpot deal.
        Args:
            deal_id: Deal ID
            dealname: New name
            dealstage: New stage
            amount: New amount
            extra_properties: Additional properties
        """
        props = _props(dealname=dealname, dealstage=dealstage, amount=amount)
        if extra_properties:
            props.update(extra_properties)
        if not props:
            raise ToolError("At least one property to update must be provided.")
        data = await _request("PATCH", f"/crm/v3/objects/deals/{deal_id}",
                              json={"properties": props})
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_delete_deal(deal_id: str) -> str:
        """Archive a HubSpot deal.
        Args:
            deal_id: Deal ID
        """
        await _request("DELETE", f"/crm/v3/objects/deals/{deal_id}")
        return _success(204, archived_id=deal_id)

    @mcp.tool()
    async def hubspot_list_deals(
        limit: int = 10, after: str | None = None, properties: str | None = None,
    ) -> str:
        """List HubSpot deals.
        Args:
            limit: Max results
            after: Pagination cursor
            properties: Comma-separated properties
        """
        params: dict = {"limit": limit}
        if after:
            params["after"] = after
        if properties:
            params["properties"] = properties
        data = await _request("GET", "/crm/v3/objects/deals", params=params)
        results = data.get("results", []) if isinstance(data, dict) else data
        paging = data.get("paging", {}).get("next", {}) if isinstance(data, dict) else {}
        return _success(200, data=results, count=len(results),
                        after=paging.get("after"))

    @mcp.tool()
    async def hubspot_search_deals(
        query: str | None = None, filter_groups: list | None = None,
        sorts: list | None = None, properties: list | None = None,
        limit: int = 10, after: str | None = None,
    ) -> str:
        """Search HubSpot deals.
        Args:
            query: Text search
            filter_groups: Filters
            sorts: Sort
            properties: Properties
            limit: Max results
            after: Cursor
        """
        return await _search("deals", query, filter_groups, sorts,
                             properties, limit, after)

    # === TICKETS ===

    @mcp.tool()
    async def hubspot_create_ticket(
        subject: str, content: str | None = None,
        hs_pipeline: str | None = None, hs_pipeline_stage: str | None = None,
        hs_ticket_priority: str | None = None,
        extra_properties: dict | None = None,
    ) -> str:
        """Create a HubSpot ticket.
        Args:
            subject: Ticket subject
            content: Ticket description
            hs_pipeline: Pipeline ID
            hs_pipeline_stage: Stage ID
            hs_ticket_priority: Priority (LOW, MEDIUM, HIGH)
            extra_properties: Additional properties
        """
        props = _props(subject=subject, content=content, hs_pipeline=hs_pipeline,
                       hs_pipeline_stage=hs_pipeline_stage,
                       hs_ticket_priority=hs_ticket_priority)
        if extra_properties:
            props.update(extra_properties)
        data = await _request("POST", "/crm/v3/objects/tickets",
                              json={"properties": props})
        return _success(201, data=data)

    @mcp.tool()
    async def hubspot_get_ticket(ticket_id: str, properties: str | None = None) -> str:
        """Get a HubSpot ticket.
        Args:
            ticket_id: Ticket ID
            properties: Comma-separated properties
        """
        params = {}
        if properties:
            params["properties"] = properties
        data = await _request("GET", f"/crm/v3/objects/tickets/{ticket_id}",
                              params=params)
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_update_ticket(
        ticket_id: str, subject: str | None = None, content: str | None = None,
        hs_pipeline_stage: str | None = None,
        extra_properties: dict | None = None,
    ) -> str:
        """Update a HubSpot ticket.
        Args:
            ticket_id: Ticket ID
            subject: New subject
            content: New content
            hs_pipeline_stage: New stage
            extra_properties: Additional properties
        """
        props = _props(subject=subject, content=content,
                       hs_pipeline_stage=hs_pipeline_stage)
        if extra_properties:
            props.update(extra_properties)
        if not props:
            raise ToolError("At least one property to update must be provided.")
        data = await _request("PATCH", f"/crm/v3/objects/tickets/{ticket_id}",
                              json={"properties": props})
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_delete_ticket(ticket_id: str) -> str:
        """Archive a HubSpot ticket.
        Args:
            ticket_id: Ticket ID
        """
        await _request("DELETE", f"/crm/v3/objects/tickets/{ticket_id}")
        return _success(204, archived_id=ticket_id)

    @mcp.tool()
    async def hubspot_list_tickets(
        limit: int = 10, after: str | None = None, properties: str | None = None,
    ) -> str:
        """List HubSpot tickets.
        Args:
            limit: Max results
            after: Cursor
            properties: Comma-separated properties
        """
        params: dict = {"limit": limit}
        if after:
            params["after"] = after
        if properties:
            params["properties"] = properties
        data = await _request("GET", "/crm/v3/objects/tickets", params=params)
        results = data.get("results", []) if isinstance(data, dict) else data
        paging = data.get("paging", {}).get("next", {}) if isinstance(data, dict) else {}
        return _success(200, data=results, count=len(results),
                        after=paging.get("after"))

    @mcp.tool()
    async def hubspot_search_tickets(
        query: str | None = None, filter_groups: list | None = None,
        sorts: list | None = None, properties: list | None = None,
        limit: int = 10, after: str | None = None,
    ) -> str:
        """Search HubSpot tickets.
        Args:
            query: Text search
            filter_groups: Filters
            sorts: Sort
            properties: Properties
            limit: Max results
            after: Cursor
        """
        return await _search("tickets", query, filter_groups, sorts,
                             properties, limit, after)

    # === NOTES ===

    @mcp.tool()
    async def hubspot_create_note(
        body: str, contact_id: str | None = None, deal_id: str | None = None,
        company_id: str | None = None, ticket_id: str | None = None,
        extra_properties: dict | None = None,
    ) -> str:
        """Create a note and optionally associate it.
        Args:
            body: Note content (HTML)
            contact_id: Associate with contact
            deal_id: Associate with deal
            company_id: Associate with company
            ticket_id: Associate with ticket
            extra_properties: Additional properties
        """
        import time

        props: dict = {
            "hs_note_body": body,
            "hs_timestamp": str(int(time.time() * 1000)),
        }
        if extra_properties:
            props.update(extra_properties)
        req: dict = {"properties": props}
        associations = []
        assoc_map = [
            (contact_id, "contacts", 202),
            (deal_id, "deals", 214),
            (company_id, "companies", 190),
            (ticket_id, "tickets", 226),
        ]
        for obj_id, obj_type, type_id in assoc_map:
            if obj_id:
                associations.append({
                    "to": {"id": obj_id},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED",
                               "associationTypeId": type_id}],
                })
        if associations:
            req["associations"] = associations
        data = await _request("POST", "/crm/v3/objects/notes", json=req)
        return _success(201, data=data)

    @mcp.tool()
    async def hubspot_get_note(note_id: str, properties: str | None = None) -> str:
        """Get a HubSpot note.
        Args:
            note_id: Note ID
            properties: Comma-separated properties
        """
        params = {}
        if properties:
            params["properties"] = properties
        data = await _request("GET", f"/crm/v3/objects/notes/{note_id}", params=params)
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_list_notes(
        limit: int = 10, after: str | None = None, properties: str | None = None,
    ) -> str:
        """List HubSpot notes.
        Args:
            limit: Max results
            after: Cursor
            properties: Comma-separated properties
        """
        params: dict = {"limit": limit}
        if after:
            params["after"] = after
        if properties:
            params["properties"] = properties
        data = await _request("GET", "/crm/v3/objects/notes", params=params)
        results = data.get("results", []) if isinstance(data, dict) else data
        paging = data.get("paging", {}).get("next", {}) if isinstance(data, dict) else {}
        return _success(200, data=results, count=len(results),
                        after=paging.get("after"))

    @mcp.tool()
    async def hubspot_update_note(
        note_id: str, body: str | None = None,
        extra_properties: dict | None = None,
    ) -> str:
        """Update a HubSpot note.
        Args:
            note_id: Note ID
            body: New note content
            extra_properties: Additional properties
        """
        props: dict = {}
        if body is not None:
            props["hs_note_body"] = body
        if extra_properties:
            props.update(extra_properties)
        if not props:
            raise ToolError("At least one property to update must be provided.")
        data = await _request("PATCH", f"/crm/v3/objects/notes/{note_id}",
                              json={"properties": props})
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_delete_note(note_id: str) -> str:
        """Archive a HubSpot note.
        Args:
            note_id: Note ID
        """
        await _request("DELETE", f"/crm/v3/objects/notes/{note_id}")
        return _success(204, archived_id=note_id)

    @mcp.tool()
    async def hubspot_search_notes(
        query: str | None = None, filter_groups: list | None = None,
        sorts: list | None = None, properties: list | None = None,
        limit: int = 10, after: str | None = None,
    ) -> str:
        """Search HubSpot notes.
        Args:
            query: Text search
            filter_groups: Filters
            sorts: Sort
            properties: Properties
            limit: Max results
            after: Cursor
        """
        return await _search("notes", query, filter_groups, sorts,
                             properties, limit, after)

    # === ASSOCIATIONS ===

    @mcp.tool()
    async def hubspot_create_association(
        from_object_type: str, from_object_id: str,
        to_object_type: str, to_object_id: str,
        association_type_id: int,
    ) -> str:
        """Create an association between two CRM objects.
        Args:
            from_object_type: Source type (contacts, companies, deals, tickets)
            from_object_id: Source object ID
            to_object_type: Target type
            to_object_id: Target object ID
            association_type_id: Association type ID
        """
        body = [{"associationCategory": "HUBSPOT_DEFINED",
                 "associationTypeId": association_type_id}]
        data = await _request(
            "PUT",
            f"/crm/v4/objects/{from_object_type}/{from_object_id}"
            f"/associations/{to_object_type}/{to_object_id}",
            json=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_remove_association(
        from_object_type: str, from_object_id: str,
        to_object_type: str, to_object_id: str,
    ) -> str:
        """Remove an association between two CRM objects.
        Args:
            from_object_type: Source type
            from_object_id: Source ID
            to_object_type: Target type
            to_object_id: Target ID
        """
        await _request(
            "DELETE",
            f"/crm/v4/objects/{from_object_type}/{from_object_id}"
            f"/associations/{to_object_type}/{to_object_id}",
        )
        return _success(204, message="Association removed")

    @mcp.tool()
    async def hubspot_get_associations(
        from_object_type: str, from_object_id: str, to_object_type: str,
    ) -> str:
        """Get associations for an object.
        Args:
            from_object_type: Source type
            from_object_id: Source ID
            to_object_type: Target type to list
        """
        data = await _request(
            "GET",
            f"/crm/v4/objects/{from_object_type}/{from_object_id}"
            f"/associations/{to_object_type}",
        )
        results = data.get("results", []) if isinstance(data, dict) else data
        return _success(200, data=results, count=len(results))

    @mcp.tool()
    async def hubspot_list_association_types(
        from_object_type: str, to_object_type: str,
    ) -> str:
        """List valid association types between two object types.
        Args:
            from_object_type: Source type
            to_object_type: Target type
        """
        data = await _request(
            "GET",
            f"/crm/v4/associations/{from_object_type}/{to_object_type}/labels",
        )
        results = data.get("results", []) if isinstance(data, dict) else data
        return _success(200, data=results, count=len(results))

    # === PIPELINES ===

    @mcp.tool()
    async def hubspot_list_pipelines(object_type: str = "deals") -> str:
        """List CRM pipelines.
        Args:
            object_type: Object type (deals or tickets)
        """
        data = await _request("GET", f"/crm/v3/pipelines/{object_type}")
        results = data.get("results", []) if isinstance(data, dict) else data
        return _success(200, data=results, count=len(results))

    @mcp.tool()
    async def hubspot_list_pipeline_stages(
        pipeline_id: str, object_type: str = "deals",
    ) -> str:
        """List stages in a pipeline.
        Args:
            pipeline_id: Pipeline ID
            object_type: Object type (deals or tickets)
        """
        data = await _request(
            "GET", f"/crm/v3/pipelines/{object_type}/{pipeline_id}/stages",
        )
        results = data.get("results", []) if isinstance(data, dict) else data
        return _success(200, data=results, count=len(results))

    # === OWNERS ===

    @mcp.tool()
    async def hubspot_list_owners(
        limit: int = 100, after: str | None = None, email: str | None = None,
    ) -> str:
        """List CRM owners (users).
        Args:
            limit: Max results (default 100)
            after: Pagination cursor
            email: Filter by email
        """
        params: dict = {"limit": limit}
        if after:
            params["after"] = after
        if email:
            params["email"] = email
        data = await _request("GET", "/crm/v3/owners", params=params)
        results = data.get("results", []) if isinstance(data, dict) else data
        paging = data.get("paging", {}).get("next", {}) if isinstance(data, dict) else {}
        return _success(200, data=results, count=len(results),
                        after=paging.get("after"))

    @mcp.tool()
    async def hubspot_get_owner(owner_id: str) -> str:
        """Get a CRM owner.
        Args:
            owner_id: Owner ID
        """
        data = await _request("GET", f"/crm/v3/owners/{owner_id}")
        return _success(200, data=data)

    # === PROPERTIES ===

    @mcp.tool()
    async def hubspot_list_properties(object_type: str) -> str:
        """List properties for a CRM object type.
        Args:
            object_type: contacts, companies, deals, tickets, or notes
        """
        data = await _request("GET", f"/crm/v3/properties/{object_type}")
        results = data.get("results", []) if isinstance(data, dict) else data
        return _success(200, data=results, count=len(results))

    @mcp.tool()
    async def hubspot_get_property(object_type: str, property_name: str) -> str:
        """Get a specific property definition.
        Args:
            object_type: Object type
            property_name: Property name
        """
        data = await _request(
            "GET", f"/crm/v3/properties/{object_type}/{property_name}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_create_property(
        object_type: str, name: str, label: str,
        type: str, field_type: str,
        group_name: str = "contactinformation",
        description: str | None = None,
        options: list[dict] | None = None,
    ) -> str:
        """Create a custom CRM property.
        Args:
            object_type: Object type
            name: Internal property name
            label: Display label
            type: string, number, date, datetime, enumeration, bool
            field_type: text, textarea, number, select, checkbox, etc.
            group_name: Property group (default contactinformation)
            description: Description
            options: Options for enumeration type
        """
        body: dict = {
            "name": name, "label": label, "type": type,
            "fieldType": field_type, "groupName": group_name,
        }
        if description:
            body["description"] = description
        if options:
            body["options"] = options
        data = await _request(
            "POST", f"/crm/v3/properties/{object_type}", json=body,
        )
        return _success(201, data=data)

    # === BATCH OPERATIONS ===

    @mcp.tool()
    async def hubspot_batch_create(object_type: str, inputs: list[dict]) -> str:
        """Batch create CRM objects.
        Args:
            object_type: contacts, companies, deals, tickets
            inputs: List of {properties: {...}} objects
        """
        data = await _request(
            "POST", f"/crm/v3/objects/{object_type}/batch/create",
            json={"inputs": inputs},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def hubspot_batch_update(object_type: str, inputs: list[dict]) -> str:
        """Batch update CRM objects.
        Args:
            object_type: contacts, companies, deals, tickets
            inputs: List of {id: "...", properties: {...}} objects
        """
        data = await _request(
            "POST", f"/crm/v3/objects/{object_type}/batch/update",
            json={"inputs": inputs},
        )
        return _success(200, data=data)
