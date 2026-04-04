"""Notion integration — pages, databases, blocks, users, search, comments."""

import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import NOTION_API_TOKEN

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if not NOTION_API_TOKEN:
        raise ToolError("NOTION_API_TOKEN not configured.")
    if _client is None:
        _client = httpx.AsyncClient(
            base_url="https://api.notion.com/v1",
            headers={
                "Authorization": f"Bearer {NOTION_API_TOKEN}",
                "Notion-Version": "2022-06-28",
            },
            timeout=30.0,
        )
    return _client


def _success(sc: int, **kw) -> str:
    return json.dumps(
        {"status": "success", "status_code": sc, **kw}
    )


async def _req(
    method: str, path: str, **kwargs
) -> dict | list:
    client = _get_client()
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"Notion request failed: {e}") from e
    if response.status_code == 429:
        retry = response.headers.get("Retry-After", "unknown")
        raise ToolError(
            f"Notion rate limit exceeded. Retry after {retry}s."
        )
    if response.status_code >= 400:
        try:
            err = response.json()
            msg = err.get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(
            f"Notion error ({response.status_code}): {msg}"
        )
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def _rich_text(text: str) -> list[dict]:
    """Convert plain string to Notion rich text array."""
    return [{"type": "text", "text": {"content": text}}]


def _title_prop(text: str) -> dict:
    """Build a title property value."""
    return {"title": _rich_text(text)}


def _paginated_params(
    start_cursor: str | None = None,
    page_size: int | None = None,
) -> dict:
    """Build pagination query/body params."""
    params: dict = {}
    if start_cursor is not None:
        params["start_cursor"] = start_cursor
    if page_size is not None:
        params["page_size"] = page_size
    return params


def register_tools(mcp: FastMCP) -> None:
    if not NOTION_API_TOKEN:
        logger.warning(
            "NOTION_API_TOKEN not set — Notion tools will fail."
        )

    # ================================================================
    # Tier 1: Pages (5 tools)
    # ================================================================

    @mcp.tool()
    async def notion_create_page(
        parent_type: str,
        parent_id: str,
        title: str,
        properties: dict | None = None,
        children: list[dict] | None = None,
        icon: dict | None = None,
        cover: dict | None = None,
    ) -> str:
        """Create a Notion page (child of page or database entry).
        Args:
            parent_type: "page_id" or "database_id"
            parent_id: UUID of the parent page or database
            title: Page title (plain text)
            properties: Additional database properties (dict)
            children: Initial block content (max 100 blocks)
            icon: Page icon object
            cover: Cover image object
        """
        body: dict = {
            "parent": {
                "type": parent_type, parent_type: parent_id
            },
        }
        if parent_type == "database_id":
            props = properties.copy() if properties else {}
            if "Name" not in props and "title" not in props:
                props["Name"] = _title_prop(title)
            body["properties"] = props
        else:
            body["properties"] = {"title": _title_prop(title)}
            if properties is not None:
                body["properties"].update(properties)
        if children is not None:
            body["children"] = children
        if icon is not None:
            body["icon"] = icon
        if cover is not None:
            body["cover"] = cover
        data = await _req("POST", "/pages", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def notion_get_page(
        page_id: str,
        filter_properties: list[str] | None = None,
    ) -> str:
        """Retrieve a Notion page by ID.
        Args:
            page_id: Page UUID
            filter_properties: Property IDs to return
        """
        params: dict = {}
        if filter_properties is not None:
            params["filter_properties"] = filter_properties
        data = await _req(
            "GET", f"/pages/{page_id}", params=params
        )
        return _success(200, data=data)

    @mcp.tool()
    async def notion_update_page(
        page_id: str,
        properties: dict | None = None,
        icon: dict | None = None,
        cover: dict | None = None,
        archived: bool | None = None,
    ) -> str:
        """Update a Notion page (properties, icon, cover, archive).
        Args:
            page_id: Page UUID
            properties: Properties to update
            icon: Updated icon or null to remove
            cover: Updated cover or null to remove
            archived: True to archive the page
        """
        body: dict = {}
        if properties is not None:
            body["properties"] = properties
        if icon is not None:
            body["icon"] = icon
        if cover is not None:
            body["cover"] = cover
        if archived is not None:
            body["archived"] = archived
        if not body:
            raise ToolError(
                "At least one field must be provided."
            )
        data = await _req(
            "PATCH", f"/pages/{page_id}", json=body
        )
        return _success(200, data=data)

    @mcp.tool()
    async def notion_archive_page(page_id: str) -> str:
        """Archive (soft-delete) a Notion page.
        Args:
            page_id: Page UUID
        """
        data = await _req(
            "PATCH", f"/pages/{page_id}",
            json={"archived": True},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def notion_get_page_property(
        page_id: str,
        property_id: str,
        start_cursor: str | None = None,
        page_size: int | None = None,
    ) -> str:
        """Get a specific property value from a page.
        Args:
            page_id: Page UUID
            property_id: Property ID
            start_cursor: Pagination cursor
            page_size: Results per page (max 100)
        """
        params = _paginated_params(start_cursor, page_size)
        data = await _req(
            "GET",
            f"/pages/{page_id}/properties/{property_id}",
            params=params,
        )
        return _success(200, data=data)

    # ================================================================
    # Tier 2: Databases (5 tools)
    # ================================================================

    @mcp.tool()
    async def notion_create_database(
        parent_page_id: str,
        title: str,
        properties: dict,
        is_inline: bool | None = None,
        icon: dict | None = None,
        cover: dict | None = None,
        description: list[dict] | None = None,
    ) -> str:
        """Create a Notion database as child of a page.
        Args:
            parent_page_id: UUID of the parent page
            title: Database title (plain text)
            properties: Property schema definitions
            is_inline: Inline in parent page (default false)
            icon: Database icon
            cover: Database cover image
            description: Rich text array for description
        """
        body: dict = {
            "parent": {
                "type": "page_id",
                "page_id": parent_page_id,
            },
            "title": _rich_text(title),
            "properties": properties,
        }
        if is_inline is not None:
            body["is_inline"] = is_inline
        if icon is not None:
            body["icon"] = icon
        if cover is not None:
            body["cover"] = cover
        if description is not None:
            body["description"] = description
        data = await _req("POST", "/databases", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def notion_get_database(
        database_id: str,
    ) -> str:
        """Retrieve a Notion database schema by ID.
        Args:
            database_id: Database UUID
        """
        data = await _req(
            "GET", f"/databases/{database_id}"
        )
        return _success(200, data=data)

    @mcp.tool()
    async def notion_update_database(
        database_id: str,
        title: str | None = None,
        description: str | None = None,
        properties: dict | None = None,
        icon: dict | None = None,
        cover: dict | None = None,
        archived: bool | None = None,
    ) -> str:
        """Update a Notion database title, description, or schema.
        Args:
            database_id: Database UUID
            title: Updated title (plain text)
            description: Updated description (plain text)
            properties: Property schema updates
            icon: Updated icon
            cover: Updated cover
            archived: True to archive the database
        """
        body: dict = {}
        if title is not None:
            body["title"] = _rich_text(title)
        if description is not None:
            body["description"] = _rich_text(description)
        if properties is not None:
            body["properties"] = properties
        if icon is not None:
            body["icon"] = icon
        if cover is not None:
            body["cover"] = cover
        if archived is not None:
            body["archived"] = archived
        if not body:
            raise ToolError(
                "At least one field must be provided."
            )
        data = await _req(
            "PATCH", f"/databases/{database_id}", json=body
        )
        return _success(200, data=data)

    @mcp.tool()
    async def notion_query_database(
        database_id: str,
        filter: dict | None = None,
        sorts: list[dict] | None = None,
        start_cursor: str | None = None,
        page_size: int | None = None,
        filter_properties: list[str] | None = None,
    ) -> str:
        """Query a Notion database with filters and sorts.
        Args:
            database_id: Database UUID
            filter: Filter object (property or compound)
            sorts: Sort criteria list
            start_cursor: Pagination cursor
            page_size: Results per page (max 100)
            filter_properties: Property IDs to include
        """
        body: dict = {}
        if filter is not None:
            body["filter"] = filter
        if sorts is not None:
            body["sorts"] = sorts
        if start_cursor is not None:
            body["start_cursor"] = start_cursor
        if page_size is not None:
            body["page_size"] = page_size
        if filter_properties is not None:
            body["filter_properties"] = filter_properties
        data = await _req(
            "POST", f"/databases/{database_id}/query",
            json=body,
        )
        results = (
            data.get("results", [])
            if isinstance(data, dict) else data
        )
        has_more = (
            data.get("has_more", False)
            if isinstance(data, dict) else False
        )
        next_cursor = (
            data.get("next_cursor")
            if isinstance(data, dict) else None
        )
        return _success(
            200, data=results, count=len(results),
            has_more=has_more, next_cursor=next_cursor,
        )

    @mcp.tool()
    async def notion_archive_database(
        database_id: str,
    ) -> str:
        """Archive (soft-delete) a Notion database.
        Args:
            database_id: Database UUID
        """
        data = await _req(
            "PATCH", f"/databases/{database_id}",
            json={"archived": True},
        )
        return _success(200, data=data)

    # ================================================================
    # Tier 3: Blocks (5 tools)
    # ================================================================

    @mcp.tool()
    async def notion_get_block(block_id: str) -> str:
        """Retrieve a single Notion block by ID.
        Args:
            block_id: Block UUID
        """
        data = await _req("GET", f"/blocks/{block_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def notion_get_block_children(
        block_id: str,
        start_cursor: str | None = None,
        page_size: int | None = None,
    ) -> str:
        """Get children of a block or content blocks of a page.
        Args:
            block_id: Block or page UUID
            start_cursor: Pagination cursor
            page_size: Results per page (max 100)
        """
        params = _paginated_params(start_cursor, page_size)
        data = await _req(
            "GET", f"/blocks/{block_id}/children",
            params=params,
        )
        results = (
            data.get("results", [])
            if isinstance(data, dict) else data
        )
        has_more = (
            data.get("has_more", False)
            if isinstance(data, dict) else False
        )
        next_cursor = (
            data.get("next_cursor")
            if isinstance(data, dict) else None
        )
        return _success(
            200, data=results, count=len(results),
            has_more=has_more, next_cursor=next_cursor,
        )

    @mcp.tool()
    async def notion_append_block_children(
        block_id: str,
        children: list[dict],
        after: str | None = None,
    ) -> str:
        """Append content blocks as children of a block or page.
        Args:
            block_id: Parent block or page UUID
            children: Block objects to append (max 100)
            after: Block UUID to insert after
        """
        body: dict = {"children": children}
        if after is not None:
            body["after"] = after
        data = await _req(
            "PATCH", f"/blocks/{block_id}/children",
            json=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def notion_update_block(
        block_id: str,
        block_type: str,
        content: dict,
        archived: bool | None = None,
    ) -> str:
        """Update an existing block's content.
        Args:
            block_id: Block UUID
            block_type: Block type (paragraph, heading_1, etc.)
            content: Type-specific content object
            archived: True to archive the block
        """
        body: dict = {block_type: content}
        if archived is not None:
            body["archived"] = archived
        data = await _req(
            "PATCH", f"/blocks/{block_id}", json=body
        )
        return _success(200, data=data)

    @mcp.tool()
    async def notion_delete_block(block_id: str) -> str:
        """Archive (soft-delete) a Notion block.
        Args:
            block_id: Block UUID
        """
        data = await _req("DELETE", f"/blocks/{block_id}")
        return _success(200, data=data)

    # ================================================================
    # Tier 4: Users (3 tools)
    # ================================================================

    @mcp.tool()
    async def notion_list_users(
        start_cursor: str | None = None,
        page_size: int | None = None,
    ) -> str:
        """List all users in the Notion workspace.
        Args:
            start_cursor: Pagination cursor
            page_size: Results per page (max 100)
        """
        params = _paginated_params(start_cursor, page_size)
        data = await _req("GET", "/users", params=params)
        results = (
            data.get("results", [])
            if isinstance(data, dict) else data
        )
        has_more = (
            data.get("has_more", False)
            if isinstance(data, dict) else False
        )
        next_cursor = (
            data.get("next_cursor")
            if isinstance(data, dict) else None
        )
        return _success(
            200, data=results, count=len(results),
            has_more=has_more, next_cursor=next_cursor,
        )

    @mcp.tool()
    async def notion_get_user(user_id: str) -> str:
        """Retrieve a Notion user by ID.
        Args:
            user_id: User UUID
        """
        data = await _req("GET", f"/users/{user_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def notion_get_bot_user() -> str:
        """Get the bot user for the current integration token."""
        data = await _req("GET", "/users/me")
        return _success(200, data=data)

    # ================================================================
    # Tier 5: Search (1 tool)
    # ================================================================

    @mcp.tool()
    async def notion_search(
        query: str | None = None,
        filter_object_type: str | None = None,
        sort_direction: str | None = None,
        start_cursor: str | None = None,
        page_size: int | None = None,
    ) -> str:
        """Search across all Notion pages and databases.
        Args:
            query: Search query (matches titles only)
            filter_object_type: "page" or "database"
            sort_direction: "ascending" or "descending"
            start_cursor: Pagination cursor
            page_size: Results per page (max 100)
        """
        body: dict = {}
        if query is not None:
            body["query"] = query
        if filter_object_type is not None:
            body["filter"] = {
                "value": filter_object_type,
                "property": "object",
            }
        if sort_direction is not None:
            body["sort"] = {
                "direction": sort_direction,
                "timestamp": "last_edited_time",
            }
        if start_cursor is not None:
            body["start_cursor"] = start_cursor
        if page_size is not None:
            body["page_size"] = page_size
        data = await _req("POST", "/search", json=body)
        results = (
            data.get("results", [])
            if isinstance(data, dict) else data
        )
        has_more = (
            data.get("has_more", False)
            if isinstance(data, dict) else False
        )
        next_cursor = (
            data.get("next_cursor")
            if isinstance(data, dict) else None
        )
        return _success(
            200, data=results, count=len(results),
            has_more=has_more, next_cursor=next_cursor,
        )

    # ================================================================
    # Tier 6: Comments (2 tools)
    # ================================================================

    @mcp.tool()
    async def notion_list_comments(
        block_id: str,
        start_cursor: str | None = None,
        page_size: int | None = None,
    ) -> str:
        """List comments on a Notion page or block.
        Args:
            block_id: Page or block UUID
            start_cursor: Pagination cursor
            page_size: Results per page (max 100)
        """
        params: dict = {"block_id": block_id}
        params.update(
            _paginated_params(start_cursor, page_size)
        )
        data = await _req(
            "GET", "/comments", params=params
        )
        results = (
            data.get("results", [])
            if isinstance(data, dict) else data
        )
        has_more = (
            data.get("has_more", False)
            if isinstance(data, dict) else False
        )
        next_cursor = (
            data.get("next_cursor")
            if isinstance(data, dict) else None
        )
        return _success(
            200, data=results, count=len(results),
            has_more=has_more, next_cursor=next_cursor,
        )

    @mcp.tool()
    async def notion_create_comment(
        content: str,
        parent_page_id: str | None = None,
        discussion_id: str | None = None,
    ) -> str:
        """Add a comment to a page or reply to a discussion.
        Args:
            content: Comment text (plain text)
            parent_page_id: Page UUID (new discussion)
            discussion_id: Discussion UUID (reply)
        """
        if (
            parent_page_id is None
            and discussion_id is None
        ):
            raise ToolError(
                "Provide parent_page_id or discussion_id."
            )
        body: dict = {"rich_text": _rich_text(content)}
        if parent_page_id is not None:
            body["parent"] = {"page_id": parent_page_id}
        if discussion_id is not None:
            body["discussion_id"] = discussion_id
        data = await _req(
            "POST", "/comments", json=body
        )
        return _success(200, data=data)
