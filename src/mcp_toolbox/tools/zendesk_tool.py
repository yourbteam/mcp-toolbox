"""Zendesk Support API v2 — tickets, users, orgs, groups, search."""

import base64
import json
import logging
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import (
    ZENDESK_API_TOKEN,
    ZENDESK_EMAIL,
    ZENDESK_SUBDOMAIN,
)

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if (
        not ZENDESK_SUBDOMAIN
        or not ZENDESK_EMAIL
        or not ZENDESK_API_TOKEN
    ):
        raise ToolError(
            "Zendesk credentials not configured. Set "
            "ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, and "
            "ZENDESK_API_TOKEN."
        )
    if _client is None:
        creds = base64.b64encode(
            f"{ZENDESK_EMAIL}/token:{ZENDESK_API_TOKEN}".encode()
        ).decode()
        _client = httpx.AsyncClient(
            base_url=(
                f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2"
            ),
            headers={"Authorization": f"Basic {creds}"},
            timeout=30.0,
        )
    return _client


def _success(sc: int, **kw: object) -> str:
    return json.dumps(
        {"status": "success", "status_code": sc, **kw}
    )


async def _req(
    method: str, path: str, **kwargs: object
) -> dict | list:
    """Send a request to Zendesk Support API v2."""
    client = _get_client()
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(
            f"Zendesk request failed: {e}"
        ) from e
    if response.status_code == 429:
        ra = response.headers.get("Retry-After", "unknown")
        raise ToolError(
            f"Zendesk rate limit exceeded. "
            f"Retry after {ra}s."
        )
    if response.status_code >= 400:
        try:
            err = response.json()
            msg = err.get("description") or err.get(
                "error", response.text
            )
            details = err.get("details")
            if details:
                msg = f"{msg} — {json.dumps(details)}"
        except Exception:
            msg = response.text
        raise ToolError(
            f"Zendesk error ({response.status_code}): {msg}"
        )
    if response.status_code == 204:
        return {}
    try:
        return response.json()  # type: ignore[no-any-return]
    except Exception:
        return {"raw": response.text}


def _cursor_params(
    params: dict,
    page_size: int | None,
    page_after: str | None,
) -> None:
    """Add cursor pagination params in-place."""
    if page_size is not None:
        params["page[size]"] = str(page_size)
    if page_after is not None:
        params["page[after]"] = page_after


def _page_meta(data: dict) -> dict:
    """Extract pagination metadata from response."""
    meta = data.get("meta", {})
    return {
        "has_more": meta.get("has_more", False),
        "after_cursor": meta.get("after_cursor"),
    }


def register_tools(mcp: FastMCP) -> None:  # noqa: C901
    if not ZENDESK_SUBDOMAIN:
        logger.warning(
            "ZENDESK_SUBDOMAIN not set — "
            "Zendesk tools will fail."
        )

    # =========================================================
    # TIER 1: TICKET MANAGEMENT (16 tools)
    # =========================================================

    @mcp.tool()
    async def zendesk_create_ticket(
        subject: str,
        description: str,
        requester_email: str | None = None,
        requester_id: int | None = None,
        assignee_id: int | None = None,
        group_id: int | None = None,
        priority: str | None = None,
        type: str | None = None,
        status: str | None = None,
        tags: list[str] | None = None,
        custom_fields: list[dict] | None = None,
        external_id: str | None = None,
        due_at: str | None = None,
    ) -> str:
        """Create a Zendesk support ticket.
        Args:
            subject: Ticket subject line
            description: Initial comment body
            requester_email: Requester email
            requester_id: Requester user ID
            assignee_id: Assignee agent user ID
            group_id: Assigned group ID
            priority: urgent, high, normal, low
            type: problem, incident, question, task
            status: new, open, pending, hold, solved
            tags: Tags to apply
            custom_fields: [{id: 123, value: x}]
            external_id: External system ID
            due_at: Due date (ISO 8601)
        """
        ticket: dict = {
            "subject": subject,
            "comment": {"body": description},
        }
        if requester_email is not None:
            ticket["requester"] = {"email": requester_email}
        if requester_id is not None:
            ticket["requester_id"] = requester_id
        if assignee_id is not None:
            ticket["assignee_id"] = assignee_id
        if group_id is not None:
            ticket["group_id"] = group_id
        if priority is not None:
            ticket["priority"] = priority
        if type is not None:
            ticket["type"] = type
        if status is not None:
            ticket["status"] = status
        if tags is not None:
            ticket["tags"] = tags
        if custom_fields is not None:
            ticket["custom_fields"] = custom_fields
        if external_id is not None:
            ticket["external_id"] = external_id
        if due_at is not None:
            ticket["due_at"] = due_at
        data = await _req(
            "POST", "/tickets.json",
            json={"ticket": ticket},
        )
        t = data.get("ticket", data) if isinstance(
            data, dict
        ) else data
        return _success(201, data=t)

    @mcp.tool()
    async def zendesk_get_ticket(
        ticket_id: int,
        include: str | None = None,
    ) -> str:
        """Get a Zendesk ticket by ID.
        Args:
            ticket_id: Ticket ID
            include: Sideload (comma-sep: users,groups)
        """
        params: dict = {}
        if include is not None:
            params["include"] = include
        data = await _req(
            "GET", f"/tickets/{ticket_id}.json",
            params=params,
        )
        t = data.get("ticket", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=t)

    @mcp.tool()
    async def zendesk_update_ticket(
        ticket_id: int,
        subject: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        type: str | None = None,
        assignee_id: int | None = None,
        group_id: int | None = None,
        tags: list[str] | None = None,
        custom_fields: list[dict] | None = None,
        due_at: str | None = None,
        external_id: str | None = None,
        comment: dict | None = None,
    ) -> str:
        """Update a Zendesk ticket.
        Args:
            ticket_id: Ticket ID
            subject: New subject
            status: New status
            priority: New priority
            type: New type
            assignee_id: New assignee user ID
            group_id: New group ID
            tags: Replace all tags
            custom_fields: Custom fields to update
            due_at: Due date (ISO 8601)
            external_id: External ID
            comment: Comment dict {body, public}
        """
        ticket: dict = {}
        if subject is not None:
            ticket["subject"] = subject
        if status is not None:
            ticket["status"] = status
        if priority is not None:
            ticket["priority"] = priority
        if type is not None:
            ticket["type"] = type
        if assignee_id is not None:
            ticket["assignee_id"] = assignee_id
        if group_id is not None:
            ticket["group_id"] = group_id
        if tags is not None:
            ticket["tags"] = tags
        if custom_fields is not None:
            ticket["custom_fields"] = custom_fields
        if due_at is not None:
            ticket["due_at"] = due_at
        if external_id is not None:
            ticket["external_id"] = external_id
        if comment is not None:
            ticket["comment"] = comment
        if not ticket:
            raise ToolError(
                "At least one field to update "
                "must be provided."
            )
        data = await _req(
            "PUT", f"/tickets/{ticket_id}.json",
            json={"ticket": ticket},
        )
        t = data.get("ticket", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=t)

    @mcp.tool()
    async def zendesk_delete_ticket(
        ticket_id: int,
    ) -> str:
        """Soft-delete a Zendesk ticket (recoverable 30d).
        Args:
            ticket_id: Ticket ID
        """
        await _req("DELETE", f"/tickets/{ticket_id}.json")
        return _success(204, deleted=ticket_id)

    @mcp.tool()
    async def zendesk_list_tickets(
        requester_id: int | None = None,
        assignee_id: int | None = None,
        organization_id: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        page_size: int | None = None,
        page_after: str | None = None,
    ) -> str:
        """List Zendesk tickets with optional filter.
        Args:
            requester_id: Filter by requester
            assignee_id: Filter by assignee
            organization_id: Filter by organization
            sort_by: Sort field
            sort_order: asc or desc
            page_size: Results per page (max 100)
            page_after: Cursor for next page
        """
        if requester_id is not None:
            path = (
                f"/users/{requester_id}"
                f"/tickets/requested.json"
            )
        elif assignee_id is not None:
            path = (
                f"/users/{assignee_id}"
                f"/tickets/assigned.json"
            )
        elif organization_id is not None:
            path = (
                f"/organizations/{organization_id}"
                f"/tickets.json"
            )
        else:
            path = "/tickets.json"
        params: dict = {}
        if sort_by is not None:
            params["sort_by"] = sort_by
        if sort_order is not None:
            params["sort_order"] = sort_order
        _cursor_params(params, page_size, page_after)
        data = await _req("GET", path, params=params)
        tickets = data.get("tickets", []) if isinstance(
            data, dict
        ) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=tickets,
            count=len(tickets), **pm,
        )

    @mcp.tool()
    async def zendesk_add_ticket_comment(
        ticket_id: int,
        body: str,
        public: bool = True,
        author_id: int | None = None,
        html_body: str | None = None,
        upload_tokens: list[str] | None = None,
    ) -> str:
        """Add a comment or internal note to a ticket.
        Args:
            ticket_id: Ticket ID
            body: Comment body (plain text)
            public: True=public reply, False=internal
            author_id: Comment author user ID
            html_body: HTML body (overrides body)
            upload_tokens: Attachment upload tokens
        """
        comment: dict = {"body": body, "public": public}
        if author_id is not None:
            comment["author_id"] = author_id
        if html_body is not None:
            comment["html_body"] = html_body
        if upload_tokens is not None:
            comment["uploads"] = upload_tokens
        data = await _req(
            "PUT", f"/tickets/{ticket_id}.json",
            json={"ticket": {"comment": comment}},
        )
        t = data.get("ticket", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=t)

    @mcp.tool()
    async def zendesk_list_ticket_comments(
        ticket_id: int,
        sort_order: str | None = None,
        include_inline_images: bool = False,
        page_size: int | None = None,
        page_after: str | None = None,
    ) -> str:
        """List comments on a Zendesk ticket.
        Args:
            ticket_id: Ticket ID
            sort_order: asc or desc
            include_inline_images: Include inline images
            page_size: Results per page (max 100)
            page_after: Cursor for next page
        """
        params: dict = {}
        if sort_order is not None:
            params["sort_order"] = sort_order
        if include_inline_images:
            params["include_inline_images"] = "true"
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET",
            f"/tickets/{ticket_id}/comments.json",
            params=params,
        )
        comments = data.get("comments", []) if isinstance(
            data, dict
        ) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=comments,
            count=len(comments), **pm,
        )

    @mcp.tool()
    async def zendesk_add_ticket_tags(
        ticket_id: int,
        tags: list[str],
    ) -> str:
        """Add tags to a ticket (keeps existing).
        Args:
            ticket_id: Ticket ID
            tags: Tags to add
        """
        data = await _req(
            "PUT",
            f"/tickets/{ticket_id}/tags.json",
            json={"tags": tags},
        )
        t = data.get("tags", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=t)

    @mcp.tool()
    async def zendesk_remove_ticket_tags(
        ticket_id: int,
        tags: list[str],
    ) -> str:
        """Remove specific tags from a ticket.
        Args:
            ticket_id: Ticket ID
            tags: Tags to remove
        """
        data = await _req(
            "DELETE",
            f"/tickets/{ticket_id}/tags.json",
            json={"tags": tags},
        )
        t = data.get("tags", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=t)

    @mcp.tool()
    async def zendesk_set_ticket_tags(
        ticket_id: int,
        tags: list[str],
    ) -> str:
        """Replace all tags on a ticket.
        Args:
            ticket_id: Ticket ID
            tags: Complete replacement tag list
        """
        data = await _req(
            "POST",
            f"/tickets/{ticket_id}/tags.json",
            json={"tags": tags},
        )
        t = data.get("tags", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=t)

    @mcp.tool()
    async def zendesk_merge_tickets(
        target_ticket_id: int,
        source_ticket_ids: list[int],
        target_comment: str | None = None,
        source_comment: str | None = None,
        target_comment_is_public: bool = True,
        source_comment_is_public: bool = True,
    ) -> str:
        """Merge source tickets into a target (irreversible).
        Args:
            target_ticket_id: Target ticket ID (survives)
            source_ticket_ids: Source ticket IDs (max 5)
            target_comment: Comment on target
            source_comment: Comment on sources
            target_comment_is_public: Target public
            source_comment_is_public: Source public
        """
        body: dict = {"ids": source_ticket_ids}
        if target_comment is not None:
            body["target_comment"] = target_comment
            body[
                "target_comment_is_public"
            ] = target_comment_is_public
        if source_comment is not None:
            body["source_comment"] = source_comment
            body[
                "source_comment_is_public"
            ] = source_comment_is_public
        data = await _req(
            "POST",
            f"/tickets/{target_ticket_id}/merge.json",
            json=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def zendesk_bulk_update_tickets(
        ticket_ids: list[int],
        status: str | None = None,
        priority: str | None = None,
        assignee_id: int | None = None,
        group_id: int | None = None,
        tags: list[str] | None = None,
        comment: dict | None = None,
    ) -> str:
        """Update multiple tickets at once.
        Args:
            ticket_ids: Ticket IDs (max 100)
            status: New status for all
            priority: New priority for all
            assignee_id: New assignee for all
            group_id: New group for all
            tags: Tags to set on all
            comment: Comment to add to all
        """
        ticket: dict = {}
        if status is not None:
            ticket["status"] = status
        if priority is not None:
            ticket["priority"] = priority
        if assignee_id is not None:
            ticket["assignee_id"] = assignee_id
        if group_id is not None:
            ticket["group_id"] = group_id
        if tags is not None:
            ticket["tags"] = tags
        if comment is not None:
            ticket["comment"] = comment
        ids_str = ",".join(str(i) for i in ticket_ids)
        data = await _req(
            "PUT",
            f"/tickets/update_many.json?ids={ids_str}",
            json={"ticket": ticket},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def zendesk_apply_macro(
        ticket_id: int,
        macro_id: int,
    ) -> str:
        """Apply a macro to a ticket (preview changes).
        Args:
            ticket_id: Ticket ID
            macro_id: Macro ID
        """
        data = await _req(
            "GET",
            f"/tickets/{ticket_id}"
            f"/macros/{macro_id}/apply.json",
        )
        result = data.get("result", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=result)

    @mcp.tool()
    async def zendesk_list_ticket_audits(
        ticket_id: int,
        page_after: str | None = None,
    ) -> str:
        """List audit trail for a ticket.
        Args:
            ticket_id: Ticket ID
            page_after: Cursor for next page
        """
        params: dict = {}
        _cursor_params(params, None, page_after)
        data = await _req(
            "GET",
            f"/tickets/{ticket_id}/audits.json",
            params=params,
        )
        audits = data.get("audits", []) if isinstance(
            data, dict
        ) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=audits,
            count=len(audits), **pm,
        )

    @mcp.tool()
    async def zendesk_list_ticket_collaborators(
        ticket_id: int,
    ) -> str:
        """List CCs/followers on a ticket.
        Args:
            ticket_id: Ticket ID
        """
        data = await _req(
            "GET",
            f"/tickets/{ticket_id}/collaborators.json",
        )
        users = data.get("users", []) if isinstance(
            data, dict
        ) else data
        return _success(200, data=users, count=len(users))

    @mcp.tool()
    async def zendesk_list_ticket_incidents(
        ticket_id: int,
    ) -> str:
        """List incidents linked to a problem ticket.
        Args:
            ticket_id: Problem ticket ID
        """
        data = await _req(
            "GET",
            f"/tickets/{ticket_id}/incidents.json",
        )
        tickets = data.get("tickets", []) if isinstance(
            data, dict
        ) else data
        return _success(
            200, data=tickets, count=len(tickets),
        )

    # =========================================================
    # TIER 2: USER MANAGEMENT (10 tools)
    # =========================================================

    @mcp.tool()
    async def zendesk_create_user(
        name: str,
        email: str,
        role: str | None = None,
        organization_id: int | None = None,
        phone: str | None = None,
        tags: list[str] | None = None,
        user_fields: dict | None = None,
        external_id: str | None = None,
        verified: bool | None = None,
    ) -> str:
        """Create a Zendesk user.
        Args:
            name: Full name
            email: Email address
            role: end-user, agent, admin
            organization_id: Organization ID
            phone: Phone number
            tags: Tags
            user_fields: Custom user fields
            external_id: External system ID
            verified: Email verified
        """
        user: dict = {"name": name, "email": email}
        if role is not None:
            user["role"] = role
        if organization_id is not None:
            user["organization_id"] = organization_id
        if phone is not None:
            user["phone"] = phone
        if tags is not None:
            user["tags"] = tags
        if user_fields is not None:
            user["user_fields"] = user_fields
        if external_id is not None:
            user["external_id"] = external_id
        if verified is not None:
            user["verified"] = verified
        data = await _req(
            "POST", "/users.json",
            json={"user": user},
        )
        u = data.get("user", data) if isinstance(
            data, dict
        ) else data
        return _success(201, data=u)

    @mcp.tool()
    async def zendesk_get_user(user_id: int) -> str:
        """Get a Zendesk user by ID.
        Args:
            user_id: User ID
        """
        data = await _req(
            "GET", f"/users/{user_id}.json",
        )
        u = data.get("user", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=u)

    @mcp.tool()
    async def zendesk_update_user(
        user_id: int,
        name: str | None = None,
        email: str | None = None,
        role: str | None = None,
        organization_id: int | None = None,
        phone: str | None = None,
        tags: list[str] | None = None,
        user_fields: dict | None = None,
        suspended: bool | None = None,
    ) -> str:
        """Update a Zendesk user.
        Args:
            user_id: User ID
            name: New name
            email: New email
            role: New role
            organization_id: New organization ID
            phone: New phone
            tags: Replace tags
            user_fields: Custom user fields
            suspended: Suspend/unsuspend user
        """
        user: dict = {}
        if name is not None:
            user["name"] = name
        if email is not None:
            user["email"] = email
        if role is not None:
            user["role"] = role
        if organization_id is not None:
            user["organization_id"] = organization_id
        if phone is not None:
            user["phone"] = phone
        if tags is not None:
            user["tags"] = tags
        if user_fields is not None:
            user["user_fields"] = user_fields
        if suspended is not None:
            user["suspended"] = suspended
        if not user:
            raise ToolError(
                "At least one field to update "
                "must be provided."
            )
        data = await _req(
            "PUT", f"/users/{user_id}.json",
            json={"user": user},
        )
        u = data.get("user", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=u)

    @mcp.tool()
    async def zendesk_delete_user(
        user_id: int,
    ) -> str:
        """Soft-delete a Zendesk user.
        Args:
            user_id: User ID
        """
        data = await _req(
            "DELETE", f"/users/{user_id}.json",
        )
        u = data.get("user", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=u)

    @mcp.tool()
    async def zendesk_list_users(
        role: str | None = None,
        role_ids: str | None = None,
        permission_set: str | None = None,
        page_size: int | None = None,
        page_after: str | None = None,
    ) -> str:
        """List Zendesk users.
        Args:
            role: Filter by role
            role_ids: Comma-sep custom role IDs
            permission_set: Permission set ID
            page_size: Results per page (max 100)
            page_after: Cursor for next page
        """
        params: dict = {}
        if role is not None:
            params["role"] = role
        if role_ids is not None:
            params["role[]"] = role_ids
        if permission_set is not None:
            params["permission_set"] = permission_set
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET", "/users.json", params=params,
        )
        users = data.get("users", []) if isinstance(
            data, dict
        ) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=users,
            count=len(users), **pm,
        )

    @mcp.tool()
    async def zendesk_search_users(
        query: str,
    ) -> str:
        """Search Zendesk users by name or email.
        Args:
            query: Search query
        """
        data = await _req(
            "GET", "/users/search.json",
            params={"query": query},
        )
        users = data.get("users", []) if isinstance(
            data, dict
        ) else data
        return _success(200, data=users, count=len(users))

    @mcp.tool()
    async def zendesk_merge_users(
        user_id: int,
        target_user_id: int,
    ) -> str:
        """Merge a user into another (irreversible).
        Args:
            user_id: Source user ID (will be deleted)
            target_user_id: Target user ID (survives)
        """
        data = await _req(
            "PUT", f"/users/{user_id}/merge.json",
            json={"user": {"id": target_user_id}},
        )
        u = data.get("user", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=u)

    @mcp.tool()
    async def zendesk_list_user_identities(
        user_id: int,
    ) -> str:
        """List identities for a user.
        Args:
            user_id: User ID
        """
        data = await _req(
            "GET",
            f"/users/{user_id}/identities.json",
        )
        ids = data.get("identities", []) if isinstance(
            data, dict
        ) else data
        return _success(200, data=ids, count=len(ids))

    @mcp.tool()
    async def zendesk_create_or_update_user(
        name: str,
        email: str,
        role: str | None = None,
        organization_id: int | None = None,
        user_fields: dict | None = None,
        external_id: str | None = None,
    ) -> str:
        """Create or update a user (upsert by email).
        Args:
            name: Full name
            email: Email (match key)
            role: Role
            organization_id: Organization ID
            user_fields: Custom user fields
            external_id: External system ID
        """
        user: dict = {"name": name, "email": email}
        if role is not None:
            user["role"] = role
        if organization_id is not None:
            user["organization_id"] = organization_id
        if user_fields is not None:
            user["user_fields"] = user_fields
        if external_id is not None:
            user["external_id"] = external_id
        data = await _req(
            "POST", "/users/create_or_update.json",
            json={"user": user},
        )
        u = data.get("user", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=u)

    @mcp.tool()
    async def zendesk_list_user_tickets(
        user_id: int,
        sort_by: str | None = None,
        sort_order: str | None = None,
        page_size: int | None = None,
        page_after: str | None = None,
    ) -> str:
        """List tickets where a user is the requester.
        Args:
            user_id: User ID
            sort_by: Sort field
            sort_order: asc or desc
            page_size: Results per page (max 100)
            page_after: Cursor for next page
        """
        params: dict = {}
        if sort_by is not None:
            params["sort_by"] = sort_by
        if sort_order is not None:
            params["sort_order"] = sort_order
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET",
            f"/users/{user_id}/tickets/requested.json",
            params=params,
        )
        tickets = data.get("tickets", []) if isinstance(
            data, dict
        ) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=tickets,
            count=len(tickets), **pm,
        )

    # =========================================================
    # TIER 3: ORGANIZATION MANAGEMENT (6 tools)
    # =========================================================

    @mcp.tool()
    async def zendesk_create_organization(
        name: str,
        details: str | None = None,
        notes: str | None = None,
        domain_names: list[str] | None = None,
        tags: list[str] | None = None,
        organization_fields: dict | None = None,
        external_id: str | None = None,
        group_id: int | None = None,
    ) -> str:
        """Create a Zendesk organization.
        Args:
            name: Organization name (unique)
            details: Details/notes
            notes: Additional notes
            domain_names: Associated domains
            tags: Tags
            organization_fields: Custom org fields
            external_id: External system ID
            group_id: Default group ID
        """
        org: dict = {"name": name}
        if details is not None:
            org["details"] = details
        if notes is not None:
            org["notes"] = notes
        if domain_names is not None:
            org["domain_names"] = domain_names
        if tags is not None:
            org["tags"] = tags
        if organization_fields is not None:
            org["organization_fields"] = organization_fields
        if external_id is not None:
            org["external_id"] = external_id
        if group_id is not None:
            org["group_id"] = group_id
        data = await _req(
            "POST", "/organizations.json",
            json={"organization": org},
        )
        o = data.get("organization", data) if isinstance(
            data, dict
        ) else data
        return _success(201, data=o)

    @mcp.tool()
    async def zendesk_get_organization(
        organization_id: int,
    ) -> str:
        """Get a Zendesk organization by ID.
        Args:
            organization_id: Organization ID
        """
        data = await _req(
            "GET",
            f"/organizations/{organization_id}.json",
        )
        o = data.get("organization", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=o)

    @mcp.tool()
    async def zendesk_update_organization(
        organization_id: int,
        name: str | None = None,
        details: str | None = None,
        notes: str | None = None,
        domain_names: list[str] | None = None,
        tags: list[str] | None = None,
        organization_fields: dict | None = None,
        group_id: int | None = None,
    ) -> str:
        """Update a Zendesk organization.
        Args:
            organization_id: Organization ID
            name: New name
            details: New details
            notes: New notes
            domain_names: Replace domain names
            tags: Replace tags
            organization_fields: Custom org fields
            group_id: New default group ID
        """
        org: dict = {}
        if name is not None:
            org["name"] = name
        if details is not None:
            org["details"] = details
        if notes is not None:
            org["notes"] = notes
        if domain_names is not None:
            org["domain_names"] = domain_names
        if tags is not None:
            org["tags"] = tags
        if organization_fields is not None:
            org["organization_fields"] = organization_fields
        if group_id is not None:
            org["group_id"] = group_id
        if not org:
            raise ToolError(
                "At least one field to update "
                "must be provided."
            )
        data = await _req(
            "PUT",
            f"/organizations/{organization_id}.json",
            json={"organization": org},
        )
        o = data.get("organization", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=o)

    @mcp.tool()
    async def zendesk_delete_organization(
        organization_id: int,
    ) -> str:
        """Delete a Zendesk organization (hard delete).
        Args:
            organization_id: Organization ID
        """
        await _req(
            "DELETE",
            f"/organizations/{organization_id}.json",
        )
        return _success(204, deleted=organization_id)

    @mcp.tool()
    async def zendesk_list_organizations(
        page_size: int | None = None,
        page_after: str | None = None,
    ) -> str:
        """List Zendesk organizations.
        Args:
            page_size: Results per page (max 100)
            page_after: Cursor for next page
        """
        params: dict = {}
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET", "/organizations.json",
            params=params,
        )
        orgs = data.get(
            "organizations", []
        ) if isinstance(data, dict) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=orgs, count=len(orgs), **pm,
        )

    @mcp.tool()
    async def zendesk_search_organizations(
        name: str,
    ) -> str:
        """Search organizations by name.
        Args:
            name: Organization name (exact or partial)
        """
        data = await _req(
            "GET", "/organizations/search.json",
            params={"name": name},
        )
        orgs = data.get(
            "organizations", []
        ) if isinstance(data, dict) else data
        return _success(
            200, data=orgs, count=len(orgs),
        )

    # =========================================================
    # TIER 4: GROUP MANAGEMENT (7 tools)
    # =========================================================

    @mcp.tool()
    async def zendesk_create_group(
        name: str,
        description: str | None = None,
    ) -> str:
        """Create a Zendesk group.
        Args:
            name: Group name
            description: Group description
        """
        group: dict = {"name": name}
        if description is not None:
            group["description"] = description
        data = await _req(
            "POST", "/groups.json",
            json={"group": group},
        )
        g = data.get("group", data) if isinstance(
            data, dict
        ) else data
        return _success(201, data=g)

    @mcp.tool()
    async def zendesk_get_group(
        group_id: int,
    ) -> str:
        """Get a Zendesk group by ID.
        Args:
            group_id: Group ID
        """
        data = await _req(
            "GET", f"/groups/{group_id}.json",
        )
        g = data.get("group", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=g)

    @mcp.tool()
    async def zendesk_update_group(
        group_id: int,
        name: str | None = None,
        description: str | None = None,
    ) -> str:
        """Update a Zendesk group.
        Args:
            group_id: Group ID
            name: New name
            description: New description
        """
        group: dict = {}
        if name is not None:
            group["name"] = name
        if description is not None:
            group["description"] = description
        if not group:
            raise ToolError(
                "At least one field to update "
                "must be provided."
            )
        data = await _req(
            "PUT", f"/groups/{group_id}.json",
            json={"group": group},
        )
        g = data.get("group", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=g)

    @mcp.tool()
    async def zendesk_delete_group(
        group_id: int,
    ) -> str:
        """Delete a Zendesk group.
        Args:
            group_id: Group ID
        """
        await _req(
            "DELETE", f"/groups/{group_id}.json",
        )
        return _success(204, deleted=group_id)

    @mcp.tool()
    async def zendesk_list_groups(
        page_size: int | None = None,
        page_after: str | None = None,
        exclude_deleted: bool = True,
    ) -> str:
        """List Zendesk groups.
        Args:
            page_size: Results per page (max 100)
            page_after: Cursor for next page
            exclude_deleted: Exclude deleted groups
        """
        params: dict = {}
        if not exclude_deleted:
            params["exclude_deleted"] = "false"
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET", "/groups.json", params=params,
        )
        groups = data.get("groups", []) if isinstance(
            data, dict
        ) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=groups,
            count=len(groups), **pm,
        )

    @mcp.tool()
    async def zendesk_list_group_memberships(
        group_id: int,
        page_size: int | None = None,
        page_after: str | None = None,
    ) -> str:
        """List memberships for a group.
        Args:
            group_id: Group ID
            page_size: Results per page (max 100)
            page_after: Cursor for next page
        """
        params: dict = {}
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET",
            f"/groups/{group_id}/memberships.json",
            params=params,
        )
        memberships = data.get(
            "group_memberships", []
        ) if isinstance(data, dict) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=memberships,
            count=len(memberships), **pm,
        )

    @mcp.tool()
    async def zendesk_create_group_membership(
        group_id: int,
        user_id: int,
    ) -> str:
        """Add an agent to a group.
        Args:
            group_id: Group ID
            user_id: Agent user ID
        """
        data = await _req(
            "POST", "/group_memberships.json",
            json={
                "group_membership": {
                    "user_id": user_id,
                    "group_id": group_id,
                }
            },
        )
        m = data.get(
            "group_membership", data
        ) if isinstance(data, dict) else data
        return _success(201, data=m)

    # =========================================================
    # TIER 5: TICKET FIELDS & FORMS (7 tools)
    # =========================================================

    @mcp.tool()
    async def zendesk_list_ticket_fields(
        page_size: int | None = None,
        page_after: str | None = None,
    ) -> str:
        """List all ticket fields (system and custom).
        Args:
            page_size: Results per page (max 100)
            page_after: Cursor for next page
        """
        params: dict = {}
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET", "/ticket_fields.json",
            params=params,
        )
        fields = data.get(
            "ticket_fields", []
        ) if isinstance(data, dict) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=fields,
            count=len(fields), **pm,
        )

    @mcp.tool()
    async def zendesk_get_ticket_field(
        ticket_field_id: int,
    ) -> str:
        """Get a single ticket field.
        Args:
            ticket_field_id: Ticket field ID
        """
        data = await _req(
            "GET",
            f"/ticket_fields/{ticket_field_id}.json",
        )
        f = data.get("ticket_field", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=f)

    @mcp.tool()
    async def zendesk_create_ticket_field(
        type: str,
        title: str,
        description: str | None = None,
        required: bool | None = None,
        active: bool | None = None,
        visible_in_portal: bool | None = None,
        editable_in_portal: bool | None = None,
        tag: str | None = None,
        custom_field_options: list[dict] | None = None,
    ) -> str:
        """Create a custom ticket field.
        Args:
            type: text, textarea, checkbox, date, etc.
            title: Display title
            description: Description
            required: Whether required
            active: Whether active
            visible_in_portal: Visible to end-users
            editable_in_portal: Editable by end-users
            tag: Associated tag (checkbox fields)
            custom_field_options: Options for dropdown
        """
        field: dict = {"type": type, "title": title}
        if description is not None:
            field["description"] = description
        if required is not None:
            field["required"] = required
        if active is not None:
            field["active"] = active
        if visible_in_portal is not None:
            field["visible_in_portal"] = visible_in_portal
        if editable_in_portal is not None:
            field["editable_in_portal"] = editable_in_portal
        if tag is not None:
            field["tag"] = tag
        if custom_field_options is not None:
            field[
                "custom_field_options"
            ] = custom_field_options
        data = await _req(
            "POST", "/ticket_fields.json",
            json={"ticket_field": field},
        )
        f = data.get("ticket_field", data) if isinstance(
            data, dict
        ) else data
        return _success(201, data=f)

    @mcp.tool()
    async def zendesk_update_ticket_field(
        ticket_field_id: int,
        title: str | None = None,
        description: str | None = None,
        required: bool | None = None,
        active: bool | None = None,
        custom_field_options: list[dict] | None = None,
    ) -> str:
        """Update a ticket field.
        Args:
            ticket_field_id: Ticket field ID
            title: New title
            description: New description
            required: New required status
            active: New active status
            custom_field_options: Updated options
        """
        field: dict = {}
        if title is not None:
            field["title"] = title
        if description is not None:
            field["description"] = description
        if required is not None:
            field["required"] = required
        if active is not None:
            field["active"] = active
        if custom_field_options is not None:
            field[
                "custom_field_options"
            ] = custom_field_options
        if not field:
            raise ToolError(
                "At least one field to update "
                "must be provided."
            )
        data = await _req(
            "PUT",
            f"/ticket_fields/{ticket_field_id}.json",
            json={"ticket_field": field},
        )
        f = data.get("ticket_field", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=f)

    @mcp.tool()
    async def zendesk_delete_ticket_field(
        ticket_field_id: int,
    ) -> str:
        """Delete a custom ticket field.
        Args:
            ticket_field_id: Ticket field ID
        """
        await _req(
            "DELETE",
            f"/ticket_fields/{ticket_field_id}.json",
        )
        return _success(204, deleted=ticket_field_id)

    @mcp.tool()
    async def zendesk_list_ticket_forms(
        active: bool | None = None,
    ) -> str:
        """List all ticket forms.
        Args:
            active: Filter by active status
        """
        params: dict = {}
        if active is not None:
            params["active"] = str(active).lower()
        data = await _req(
            "GET", "/ticket_forms.json",
            params=params,
        )
        forms = data.get(
            "ticket_forms", []
        ) if isinstance(data, dict) else data
        return _success(
            200, data=forms, count=len(forms),
        )

    @mcp.tool()
    async def zendesk_get_ticket_form(
        ticket_form_id: int,
    ) -> str:
        """Get a single ticket form.
        Args:
            ticket_form_id: Ticket form ID
        """
        data = await _req(
            "GET",
            f"/ticket_forms/{ticket_form_id}.json",
        )
        f = data.get("ticket_form", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=f)

    # =========================================================
    # TIER 6: VIEWS (4 tools)
    # =========================================================

    @mcp.tool()
    async def zendesk_list_views(
        active: bool | None = None,
        group_id: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        page_size: int | None = None,
        page_after: str | None = None,
    ) -> str:
        """List all shared and personal views.
        Args:
            active: Filter by active status
            group_id: Filter by group ID
            sort_by: alphabetical, created_at, updated_at
            sort_order: asc or desc
            page_size: Results per page (max 100)
            page_after: Cursor for next page
        """
        params: dict = {}
        if active is not None:
            params["active"] = str(active).lower()
        if group_id is not None:
            params["group_id"] = str(group_id)
        if sort_by is not None:
            params["sort_by"] = sort_by
        if sort_order is not None:
            params["sort_order"] = sort_order
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET", "/views.json", params=params,
        )
        views = data.get("views", []) if isinstance(
            data, dict
        ) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=views,
            count=len(views), **pm,
        )

    @mcp.tool()
    async def zendesk_get_view(view_id: int) -> str:
        """Get a single view.
        Args:
            view_id: View ID
        """
        data = await _req(
            "GET", f"/views/{view_id}.json",
        )
        v = data.get("view", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=v)

    @mcp.tool()
    async def zendesk_execute_view(
        view_id: int,
        sort_by: str | None = None,
        sort_order: str | None = None,
        page_size: int | None = None,
        page_after: str | None = None,
    ) -> str:
        """Execute a view and return matching tickets.
        Args:
            view_id: View ID
            sort_by: Sort column
            sort_order: asc or desc
            page_size: Results per page (max 100)
            page_after: Cursor for next page
        """
        params: dict = {}
        if sort_by is not None:
            params["sort_by"] = sort_by
        if sort_order is not None:
            params["sort_order"] = sort_order
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET",
            f"/views/{view_id}/execute.json",
            params=params,
        )
        rows = data.get("rows", []) if isinstance(
            data, dict
        ) else data
        return _success(
            200, data=rows, count=len(rows),
        )

    @mcp.tool()
    async def zendesk_get_view_count(
        view_id: int,
    ) -> str:
        """Get ticket count for a view.
        Args:
            view_id: View ID
        """
        data = await _req(
            "GET", f"/views/{view_id}/count.json",
        )
        vc = data.get("view_count", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=vc)

    # =========================================================
    # TIER 7: SEARCH (2 tools)
    # =========================================================

    @mcp.tool()
    async def zendesk_search(
        query: str,
        sort_by: str | None = None,
        sort_order: str | None = None,
        per_page: int | None = None,
        page: int | None = None,
    ) -> str:
        """Unified search (tickets, users, orgs) via ZQL.
        Args:
            query: ZQL query string
            sort_by: relevance, created_at, etc.
            sort_order: asc or desc
            per_page: Results per page (max 100)
            page: Page number (1-based)
        """
        params: dict = {"query": query}
        if sort_by is not None:
            params["sort_by"] = sort_by
        if sort_order is not None:
            params["sort_order"] = sort_order
        if per_page is not None:
            params["per_page"] = str(per_page)
        if page is not None:
            params["page"] = str(page)
        data = await _req(
            "GET", "/search.json", params=params,
        )
        results = data.get("results", []) if isinstance(
            data, dict
        ) else data
        count = data.get("count", len(results)) if isinstance(
            data, dict
        ) else len(results)
        return _success(
            200, data=results,
            count=count,
        )

    @mcp.tool()
    async def zendesk_search_count(
        query: str,
    ) -> str:
        """Get count of search results without fetching.
        Args:
            query: ZQL query string
        """
        data = await _req(
            "GET", "/search/count.json",
            params={"query": query},
        )
        count = data.get("count", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=count)

    # =========================================================
    # TIER 8: SATISFACTION RATINGS (3 tools)
    # =========================================================

    @mcp.tool()
    async def zendesk_list_satisfaction_ratings(
        score: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        page_size: int | None = None,
        page_after: str | None = None,
    ) -> str:
        """List satisfaction ratings (CSAT).
        Args:
            score: good, bad, offered, unoffered
            start_time: Filter start (Unix epoch)
            end_time: Filter end (Unix epoch)
            page_size: Results per page (max 100)
            page_after: Cursor for next page
        """
        params: dict = {}
        if score is not None:
            params["score"] = score
        if start_time is not None:
            params["start_time"] = str(start_time)
        if end_time is not None:
            params["end_time"] = str(end_time)
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET", "/satisfaction_ratings.json",
            params=params,
        )
        ratings = data.get(
            "satisfaction_ratings", []
        ) if isinstance(data, dict) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=ratings,
            count=len(ratings), **pm,
        )

    @mcp.tool()
    async def zendesk_get_satisfaction_rating(
        rating_id: int,
    ) -> str:
        """Get a single satisfaction rating.
        Args:
            rating_id: Satisfaction rating ID
        """
        data = await _req(
            "GET",
            f"/satisfaction_ratings/{rating_id}.json",
        )
        r = data.get(
            "satisfaction_rating", data
        ) if isinstance(data, dict) else data
        return _success(200, data=r)

    @mcp.tool()
    async def zendesk_create_satisfaction_rating(
        ticket_id: int,
        score: str,
        comment: str | None = None,
    ) -> str:
        """Create a satisfaction rating on a solved ticket.
        Args:
            ticket_id: Solved ticket ID
            score: good or bad
            comment: Requester feedback text
        """
        rating: dict = {"score": score}
        if comment is not None:
            rating["comment"] = comment
        data = await _req(
            "POST",
            f"/tickets/{ticket_id}"
            f"/satisfaction_rating.json",
            json={"satisfaction_rating": rating},
        )
        r = data.get(
            "satisfaction_rating", data
        ) if isinstance(data, dict) else data
        return _success(201, data=r)

    # =========================================================
    # TIER 9: ATTACHMENTS (2 tools)
    # =========================================================

    @mcp.tool()
    async def zendesk_upload_attachment(
        file_path: str,
        filename: str | None = None,
        token: str | None = None,
    ) -> str:
        """Upload a file to get an upload token.
        Args:
            file_path: Local file path
            filename: Override filename
            token: Existing token (multi-file upload)
        """
        fp = Path(file_path)
        if not fp.is_file():
            raise ToolError(f"File not found: {file_path}")
        fname = filename or fp.name
        params: dict = {"filename": fname}
        if token is not None:
            params["token"] = token
        client = _get_client()
        try:
            with open(fp, "rb") as f:
                response = await client.post(
                    "/uploads.json",
                    params=params,
                    content=f.read(),
                    headers={
                        "Content-Type":
                            "application/binary",
                    },
                )
        except httpx.HTTPError as e:
            raise ToolError(
                f"Upload failed: {e}"
            ) from e
        if response.status_code >= 400:
            raise ToolError(
                f"Upload error ({response.status_code}): "
                f"{response.text}"
            )
        data = response.json()
        upload = data.get("upload", data) if isinstance(
            data, dict
        ) else data
        return _success(201, data=upload)

    @mcp.tool()
    async def zendesk_delete_upload(
        token: str,
    ) -> str:
        """Delete an uploaded file by token.
        Args:
            token: Upload token
        """
        await _req(
            "DELETE", f"/uploads/{token}.json",
        )
        return _success(204, message="Upload deleted")

    # =========================================================
    # TIER 10: SUSPENDED TICKETS (4 tools)
    # =========================================================

    @mcp.tool()
    async def zendesk_list_suspended_tickets(
        sort_by: str | None = None,
        sort_order: str | None = None,
        page_size: int | None = None,
        page_after: str | None = None,
    ) -> str:
        """List suspended (spam-filtered) tickets.
        Args:
            sort_by: author, cause, created_at, subject
            sort_order: asc or desc
            page_size: Results per page (max 100)
            page_after: Cursor for next page
        """
        params: dict = {}
        if sort_by is not None:
            params["sort_by"] = sort_by
        if sort_order is not None:
            params["sort_order"] = sort_order
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET", "/suspended_tickets.json",
            params=params,
        )
        tickets = data.get(
            "suspended_tickets", []
        ) if isinstance(data, dict) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=tickets,
            count=len(tickets), **pm,
        )

    @mcp.tool()
    async def zendesk_get_suspended_ticket(
        suspended_ticket_id: int,
    ) -> str:
        """Get a single suspended ticket.
        Args:
            suspended_ticket_id: Suspended ticket ID
        """
        data = await _req(
            "GET",
            f"/suspended_tickets"
            f"/{suspended_ticket_id}.json",
        )
        t = data.get(
            "suspended_ticket", data
        ) if isinstance(data, dict) else data
        return _success(200, data=t)

    @mcp.tool()
    async def zendesk_recover_suspended_ticket(
        suspended_ticket_id: int,
    ) -> str:
        """Recover a suspended ticket to active queue.
        Args:
            suspended_ticket_id: Suspended ticket ID
        """
        data = await _req(
            "PUT",
            f"/suspended_tickets"
            f"/{suspended_ticket_id}/recover.json",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def zendesk_delete_suspended_ticket(
        suspended_ticket_id: int,
    ) -> str:
        """Permanently delete a suspended ticket.
        Args:
            suspended_ticket_id: Suspended ticket ID
        """
        await _req(
            "DELETE",
            f"/suspended_tickets"
            f"/{suspended_ticket_id}.json",
        )
        return _success(
            204, deleted=suspended_ticket_id,
        )

    # =========================================================
    # TIER 11: MACROS (5 tools)
    # =========================================================

    @mcp.tool()
    async def zendesk_list_macros(
        active: bool | None = None,
        category: int | None = None,
        group_id: int | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        page_size: int | None = None,
        page_after: str | None = None,
        include: str | None = None,
    ) -> str:
        """List macros available to the agent.
        Args:
            active: Filter by active status
            category: Filter by category ID
            group_id: Filter by group ID
            sort_by: alphabetical, created_at, etc.
            sort_order: asc or desc
            page_size: Results per page (max 100)
            page_after: Cursor for next page
            include: Sideload (usage_7d, usage_24h)
        """
        params: dict = {}
        if active is not None:
            params["active"] = str(active).lower()
        if category is not None:
            params["category"] = str(category)
        if group_id is not None:
            params["group_id"] = str(group_id)
        if sort_by is not None:
            params["sort_by"] = sort_by
        if sort_order is not None:
            params["sort_order"] = sort_order
        if include is not None:
            params["include"] = include
        _cursor_params(params, page_size, page_after)
        data = await _req(
            "GET", "/macros.json", params=params,
        )
        macros = data.get("macros", []) if isinstance(
            data, dict
        ) else data
        pm = _page_meta(data) if isinstance(
            data, dict
        ) else {}
        return _success(
            200, data=macros,
            count=len(macros), **pm,
        )

    @mcp.tool()
    async def zendesk_get_macro(
        macro_id: int,
    ) -> str:
        """Get a single macro.
        Args:
            macro_id: Macro ID
        """
        data = await _req(
            "GET", f"/macros/{macro_id}.json",
        )
        m = data.get("macro", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=m)

    @mcp.tool()
    async def zendesk_create_macro(
        title: str,
        actions: list[dict],
        description: str | None = None,
        active: bool | None = None,
        restriction: dict | None = None,
    ) -> str:
        """Create a Zendesk macro.
        Args:
            title: Macro title
            actions: [{field: status, value: solved}]
            description: Macro description
            active: Active status
            restriction: {type: Group, id: 123}
        """
        macro: dict = {
            "title": title,
            "actions": actions,
        }
        if description is not None:
            macro["description"] = description
        if active is not None:
            macro["active"] = active
        if restriction is not None:
            macro["restriction"] = restriction
        data = await _req(
            "POST", "/macros.json",
            json={"macro": macro},
        )
        m = data.get("macro", data) if isinstance(
            data, dict
        ) else data
        return _success(201, data=m)

    @mcp.tool()
    async def zendesk_update_macro(
        macro_id: int,
        title: str | None = None,
        actions: list[dict] | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> str:
        """Update a Zendesk macro.
        Args:
            macro_id: Macro ID
            title: New title
            actions: New actions
            description: New description
            active: New active status
        """
        macro: dict = {}
        if title is not None:
            macro["title"] = title
        if actions is not None:
            macro["actions"] = actions
        if description is not None:
            macro["description"] = description
        if active is not None:
            macro["active"] = active
        if not macro:
            raise ToolError(
                "At least one field to update "
                "must be provided."
            )
        data = await _req(
            "PUT", f"/macros/{macro_id}.json",
            json={"macro": macro},
        )
        m = data.get("macro", data) if isinstance(
            data, dict
        ) else data
        return _success(200, data=m)

    @mcp.tool()
    async def zendesk_delete_macro(
        macro_id: int,
    ) -> str:
        """Delete a Zendesk macro.
        Args:
            macro_id: Macro ID
        """
        await _req(
            "DELETE", f"/macros/{macro_id}.json",
        )
        return _success(204, deleted=macro_id)
