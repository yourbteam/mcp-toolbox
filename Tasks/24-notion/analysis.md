# Task 24: Notion Integration - Analysis & Requirements

## Objective
Add Notion as a tool integration in mcp-toolbox, exposing the full Notion API (pages, databases, blocks, users, search, comments) as MCP tools for LLM clients.

---

## API Technical Details

### Notion API (v2022-06-28) -- REST
- **Base URL:** `https://api.notion.com/v1`
- **Auth:** Internal integration token via `Authorization: Bearer secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` header
- **Version Header:** `Notion-Version: 2022-06-28` (required on every request)
- **Format:** JSON request/response (`Content-Type: application/json`)

### Rate Limits

| Metric | Limit |
|--------|-------|
| Average rate | 3 requests per second |
| Burst | Short bursts above 3 rps tolerated, but sustained excess triggers 429 |
| Per integration | Rate limits are per integration token |

- HTTP 429 on exceed with `Retry-After` header (seconds)
- Rate limit responses include `"code": "rate_limited"` in JSON body
- Recommendation: Implement exponential backoff on 429

### No Official Python SDK Needed
Notion offers `notion-client` (Python SDK), but it adds unnecessary complexity. **Recommendation:** Use `httpx` (already in our dependencies) for direct async HTTP calls -- consistent with HubSpot/ClickUp pattern, simpler, full async control.

### Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `NOTION_API_TOKEN` | Yes | Internal integration token (starts with `secret_` or `ntn_`) |

### Key Quirks

- **Rich text objects** -- All text in Notion is represented as arrays of rich text objects: `[{"type": "text", "text": {"content": "Hello", "link": null}, "annotations": {"bold": false, "italic": false, ...}, "plain_text": "Hello", "href": null}]`. Tools must accept plain strings and wrap them into rich text arrays internally.
- **Property value objects** -- Database page properties are typed objects with structure varying by type (e.g., `{"Title": {"title": [{"text": {"content": "My Page"}}]}}` vs `{"Status": {"select": {"name": "Done"}}}`). The implementation should provide a helper to build property values from simpler inputs.
- **Block types** -- Content is structured as blocks (paragraph, heading_1/2/3, bulleted_list_item, numbered_list_item, to_do, toggle, code, image, divider, table, callout, quote, bookmark, embed, etc.). Each block type has its own schema.
- **Parent types** -- Pages/databases must specify a parent: `{"type": "page_id", "page_id": "..."}`, `{"type": "database_id", "database_id": "..."}`, or `{"type": "workspace", "workspace": true}`.
- **Pagination via cursor** -- All list endpoints return `{"has_more": true/false, "next_cursor": "..."}`. Pass `start_cursor` and `page_size` (max 100) to paginate.
- **IDs are UUIDs** -- All Notion IDs are UUIDs (with or without hyphens). The API accepts both formats.
- **Archived vs deleted** -- Pages and blocks are "archived" (soft-deleted), not permanently deleted via the API.
- **100-block limit** -- `append_block_children` accepts a maximum of 100 blocks per request.
- **Filter & sort objects** -- Database queries use structured filter objects with compound filters (`and`/`or`) and typed property filters.
- **Timestamps in ISO 8601** -- All dates use ISO 8601 format.
- **Integration must be shared** -- The integration must be explicitly shared with (connected to) each page/database it accesses; otherwise the API returns 404.
- **Title property required** -- Every database must have exactly one `title` property; every page in a database must provide it.

---

## Notion Object Model

```
Workspace
  |
  +-- Pages (top-level or nested)
  |     |
  |     +-- Blocks (content: paragraphs, headings, lists, etc.)
  |     |     |
  |     |     +-- Child blocks (nested content)
  |     |
  |     +-- Child pages (sub-pages)
  |     +-- Child databases (inline databases)
  |
  +-- Databases (top-level or inline)
  |     |
  |     +-- Pages (database entries/rows)
  |     +-- Properties (schema: title, rich_text, number, select, multi_select, date, etc.)
  |
  +-- Users (workspace members & bots)
  |
  +-- Comments (on pages or in discussions)
```

### Core Object Types

| Object | API Path | Description |
|--------|----------|-------------|
| Pages | `/v1/pages` | Content containers; can be standalone or database entries |
| Databases | `/v1/databases` | Structured collections with typed property schemas |
| Blocks | `/v1/blocks` | Content elements within pages (paragraphs, headings, lists, etc.) |
| Users | `/v1/users` | Workspace members (people and bots) |
| Comments | `/v1/comments` | Discussion comments on pages or blocks |
| Search | `/v1/search` | Cross-workspace search for pages and databases |

### Database Property Types
| Type | Value Structure | Example |
|------|----------------|---------|
| `title` | `[{rich_text}]` | Page name |
| `rich_text` | `[{rich_text}]` | Text content |
| `number` | `number` | `42` |
| `select` | `{"name": "..."}` | Single choice |
| `multi_select` | `[{"name": "..."}]` | Multiple choices |
| `date` | `{"start": "...", "end": "..."}` | Date or date range |
| `people` | `[{"id": "..."}]` | User references |
| `files` | `[{"name": "...", "external": {"url": "..."}}]` | File references |
| `checkbox` | `true/false` | Boolean |
| `url` | `"https://..."` | URL string |
| `email` | `"user@example.com"` | Email string |
| `phone_number` | `"+1234567890"` | Phone string |
| `formula` | (read-only) | Computed value |
| `relation` | `[{"id": "..."}]` | Relations to other database pages |
| `rollup` | (read-only) | Aggregated from relation |
| `status` | `{"name": "..."}` | Status property |

---

## Tool Specifications

### Tier 1: Pages (5 tools)

#### `notion_create_page`
Create a new page in Notion (either as a child of a page or as a database entry).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `parent_type` | str | Yes | `"page_id"` or `"database_id"` |
| `parent_id` | str | Yes | UUID of the parent page or database |
| `title` | str | Yes | Page title (plain text, converted to title property) |
| `properties` | dict | No | Additional database properties (required if parent is database). Keys are property names, values are property value objects. |
| `children` | list[dict] | No | Initial block content (max 100 blocks). Each item is a block object. |
| `icon` | dict | No | Page icon: `{"type": "emoji", "emoji": "..."}` or `{"type": "external", "external": {"url": "..."}}` |
| `cover` | dict | No | Cover image: `{"type": "external", "external": {"url": "..."}}` |

**Returns:** Created page object with ID and properties.
**Endpoint:** `POST /v1/pages`
**Body:**
```json
{
  "parent": {"type": "database_id", "database_id": "..."},
  "properties": {"Name": {"title": [{"text": {"content": "..."}}]}, ...},
  "children": [...]
}
```

#### `notion_get_page`
Retrieve a page by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `page_id` | str | Yes | Page UUID |
| `filter_properties` | list[str] | No | List of property IDs to return (reduces response size) |

**Returns:** Page object with properties.
**Endpoint:** `GET /v1/pages/{page_id}`
**Query params:** `filter_properties` (repeated param for each property ID)

#### `notion_update_page`
Update page properties, icon, cover, or archive status.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `page_id` | str | Yes | Page UUID |
| `properties` | dict | No | Properties to update (keys are property names, values are property value objects) |
| `icon` | dict | No | Updated icon object or `null` to remove |
| `cover` | dict | No | Updated cover object or `null` to remove |
| `archived` | bool | No | Set to `true` to archive (soft-delete) the page |

At least one of `properties`, `icon`, `cover`, or `archived` must be provided.
**Returns:** Updated page object.
**Endpoint:** `PATCH /v1/pages/{page_id}`
**Body:** `{"properties": {...}, "archived": false, ...}`

#### `notion_archive_page`
Archive (soft-delete) a page.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `page_id` | str | Yes | Page UUID |

**Returns:** Confirmation of archival.
**Endpoint:** `PATCH /v1/pages/{page_id}`
**Body:** `{"archived": true}`

#### `notion_get_page_property`
Retrieve a specific property value from a page (supports pagination for large properties like relations and rollups).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `page_id` | str | Yes | Page UUID |
| `property_id` | str | Yes | Property ID (from database schema or page object) |
| `start_cursor` | str | No | Pagination cursor for paginated property values |
| `page_size` | int | No | Number of items per page (max 100, default 100) |

**Returns:** Property value item or paginated list of property value items.
**Endpoint:** `GET /v1/pages/{page_id}/properties/{property_id}`

---

### Tier 2: Databases (5 tools)

#### `notion_create_database`
Create a new database as a child of an existing page.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `parent_page_id` | str | Yes | UUID of the parent page |
| `title` | str | Yes | Database title (plain text) |
| `properties` | dict | Yes | Property schema definitions. Keys are property names, values are property config objects (e.g., `{"Name": {"title": {}}, "Status": {"select": {"options": [{"name": "Todo"}, {"name": "Done"}]}}}`) |
| `is_inline` | bool | No | Whether the database appears inline in the parent page (default false) |
| `icon` | dict | No | Database icon |
| `cover` | dict | No | Database cover image |
| `description` | list[dict] | No | Database description as rich text array |

**Returns:** Created database object with ID and schema.
**Endpoint:** `POST /v1/databases`
**Body:**
```json
{
  "parent": {"type": "page_id", "page_id": "..."},
  "title": [{"type": "text", "text": {"content": "..."}}],
  "properties": {...},
  "is_inline": false
}
```

#### `notion_get_database`
Retrieve a database schema by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `database_id` | str | Yes | Database UUID |

**Returns:** Database object with full property schema.
**Endpoint:** `GET /v1/databases/{database_id}`

#### `notion_update_database`
Update a database title, description, or property schema.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `database_id` | str | Yes | Database UUID |
| `title` | str | No | Updated title (plain text) |
| `description` | str | No | Updated description (plain text) |
| `properties` | dict | No | Property schema updates. To add a property, include its definition. To rename, use `{"OldName": {"name": "NewName"}}`. To delete, use `{"PropName": null}`. |
| `icon` | dict | No | Updated icon object |
| `cover` | dict | No | Updated cover object |
| `archived` | bool | No | Set to `true` to archive the database |

At least one field must be provided.
**Returns:** Updated database object.
**Endpoint:** `PATCH /v1/databases/{database_id}`

#### `notion_query_database`
Query a database with optional filters, sorts, and pagination.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `database_id` | str | Yes | Database UUID |
| `filter` | dict | No | Filter object (see filter format below) |
| `sorts` | list[dict] | No | Sort criteria (see sort format below) |
| `start_cursor` | str | No | Pagination cursor from previous response |
| `page_size` | int | No | Results per page (max 100, default 100) |
| `filter_properties` | list[str] | No | Property IDs to include in results (reduces response size) |

**Filter format (property filter):**
```json
{"property": "Status", "select": {"equals": "Done"}}
```

**Filter format (compound):**
```json
{"and": [{"property": "Status", "select": {"equals": "Done"}}, {"property": "Priority", "number": {"greater_than": 3}}]}
```

**Sort format:**
```json
[{"property": "Created", "direction": "descending"}]
```
or timestamp sort: `[{"timestamp": "created_time", "direction": "ascending"}]`

**Filter operators by property type:**
- **text/rich_text/title/url/email/phone_number:** `equals`, `does_not_equal`, `contains`, `does_not_contain`, `starts_with`, `ends_with`, `is_empty`, `is_not_empty`
- **number:** `equals`, `does_not_equal`, `greater_than`, `less_than`, `greater_than_or_equal_to`, `less_than_or_equal_to`, `is_empty`, `is_not_empty`
- **checkbox:** `equals`, `does_not_equal`
- **select/status:** `equals`, `does_not_equal`, `is_empty`, `is_not_empty`
- **multi_select:** `contains`, `does_not_contain`, `is_empty`, `is_not_empty`
- **date:** `equals`, `before`, `after`, `on_or_before`, `on_or_after`, `is_empty`, `is_not_empty`, `past_week`, `past_month`, `past_year`, `next_week`, `next_month`, `next_year`
- **relation:** `contains`, `does_not_contain`, `is_empty`, `is_not_empty`
- **formula:** depends on formula result type (string/number/boolean/date)

**Returns:** Paginated list of page objects matching the query.
**Endpoint:** `POST /v1/databases/{database_id}/query`

#### `notion_archive_database`
Archive (soft-delete) a database.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `database_id` | str | Yes | Database UUID |

**Returns:** Confirmation of archival.
**Endpoint:** `PATCH /v1/databases/{database_id}`
**Body:** `{"archived": true}`

---

### Tier 3: Blocks (5 tools)

#### `notion_get_block`
Retrieve a single block by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `block_id` | str | Yes | Block UUID |

**Returns:** Block object with type-specific content.
**Endpoint:** `GET /v1/blocks/{block_id}`

#### `notion_get_block_children`
Retrieve the children of a block (or the content blocks of a page).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `block_id` | str | Yes | Block or page UUID |
| `start_cursor` | str | No | Pagination cursor |
| `page_size` | int | No | Results per page (max 100, default 100) |

**Returns:** Paginated list of child block objects.
**Endpoint:** `GET /v1/blocks/{block_id}/children`

#### `notion_append_block_children`
Append new content blocks as children of an existing block or page.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `block_id` | str | Yes | Parent block or page UUID |
| `children` | list[dict] | Yes | Array of block objects to append (max 100) |
| `after` | str | No | Block UUID to insert after (appends to end if omitted) |

**Block object examples:**
```json
{"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "Hello world"}}]}}
{"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "Title"}}]}}
{"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "Item"}}]}}
{"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "Task"}}], "checked": false}}
{"type": "code", "code": {"rich_text": [{"type": "text", "text": {"content": "print('hi')"}}], "language": "python"}}
{"type": "divider", "divider": {}}
{"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": "Note"}}], "icon": {"type": "emoji", "emoji": "!"}}}
{"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "A quote"}}]}}
{"type": "bookmark", "bookmark": {"url": "https://example.com"}}
{"type": "image", "image": {"type": "external", "external": {"url": "https://example.com/img.png"}}}
{"type": "table", "table": {"table_width": 2, "has_column_header": true, "children": [{"type": "table_row", "table_row": {"cells": [[{"type": "text", "text": {"content": "Col1"}}], [{"type": "text", "text": {"content": "Col2"}}]]}}]}}
```

**Returns:** Updated block object (the parent) with appended children.
**Endpoint:** `PATCH /v1/blocks/{block_id}/children`
**Body:** `{"children": [...], "after": "..."}`

#### `notion_update_block`
Update an existing block's content or type-specific properties.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `block_id` | str | Yes | Block UUID |
| `block_type` | str | Yes | Block type (e.g., `"paragraph"`, `"heading_1"`, `"to_do"`, etc.) |
| `content` | dict | Yes | Type-specific content object (e.g., `{"rich_text": [...]}` for paragraph) |
| `archived` | bool | No | Set to `true` to archive the block |

**Returns:** Updated block object.
**Endpoint:** `PATCH /v1/blocks/{block_id}`
**Body:** `{"paragraph": {"rich_text": [...]}}` (key is the block type)

#### `notion_delete_block`
Archive (soft-delete) a block.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `block_id` | str | Yes | Block UUID |

**Returns:** Confirmation of archival (block with `archived: true`).
**Endpoint:** `DELETE /v1/blocks/{block_id}`

---

### Tier 4: Users (3 tools)

#### `notion_list_users`
List all users in the workspace (people and bots).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `start_cursor` | str | No | Pagination cursor |
| `page_size` | int | No | Results per page (max 100, default 100) |

**Returns:** Paginated list of user objects.
**Endpoint:** `GET /v1/users`

#### `notion_get_user`
Retrieve a user by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | str | Yes | User UUID |

**Returns:** User object with name, avatar, type (person/bot), and email (for people).
**Endpoint:** `GET /v1/users/{user_id}`

#### `notion_get_bot_user`
Retrieve the bot user associated with the current integration token.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** Bot user object including owner info and workspace details.
**Endpoint:** `GET /v1/users/me`

---

### Tier 5: Search (1 tool)

#### `notion_search`
Search across all pages and databases the integration has access to.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | No | Search query string (searches page/database titles). Omit to return all accessible objects. |
| `filter_object_type` | str | No | `"page"` or `"database"` to filter results by object type |
| `sort_direction` | str | No | `"ascending"` or `"descending"` (sorts by `last_edited_time`) |
| `start_cursor` | str | No | Pagination cursor |
| `page_size` | int | No | Results per page (max 100, default 100) |

**Returns:** Paginated list of page and/or database objects matching the query.
**Endpoint:** `POST /v1/search`
**Body:**
```json
{
  "query": "...",
  "filter": {"value": "page", "property": "object"},
  "sort": {"direction": "descending", "timestamp": "last_edited_time"},
  "start_cursor": "...",
  "page_size": 100
}
```

**Note:** Search only matches against titles, not page content. Results are ranked by relevance when a query is provided.

---

### Tier 6: Comments (2 tools)

#### `notion_list_comments`
List comments on a page or in a discussion thread.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `block_id` | str | Yes | Page or block UUID to list comments for |
| `start_cursor` | str | No | Pagination cursor |
| `page_size` | int | No | Results per page (max 100, default 100) |

**Returns:** Paginated list of comment objects with rich text content and author.
**Endpoint:** `GET /v1/comments?block_id={block_id}`

#### `notion_create_comment`
Add a comment to a page or reply to an existing discussion thread.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `parent_page_id` | str | Conditional | Page UUID (use this to start a new discussion on a page) |
| `discussion_id` | str | Conditional | Discussion thread UUID (use this to reply to an existing thread) |
| `content` | str | Yes | Comment text (plain text, converted to rich text internally) |

One of `parent_page_id` or `discussion_id` is required.
**Returns:** Created comment object.
**Endpoint:** `POST /v1/comments`
**Body (new discussion):**
```json
{
  "parent": {"page_id": "..."},
  "rich_text": [{"type": "text", "text": {"content": "..."}}]
}
```
**Body (reply to discussion):**
```json
{
  "discussion_id": "...",
  "rich_text": [{"type": "text", "text": {"content": "..."}}]
}
```

---

## Tool Count Summary

| Tier | Category | Tools |
|------|----------|-------|
| 1 | Pages | 5 |
| 2 | Databases | 5 |
| 3 | Blocks | 5 |
| 4 | Users | 3 |
| 5 | Search | 1 |
| 6 | Comments | 2 |
| **Total** | | **21** |

---

## Implementation Architecture

### Singleton HTTP Client Pattern (consistent with HubSpot/ClickUp)

```python
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
```

### Helper Functions Needed

1. **`_rich_text(text: str) -> list[dict]`** -- Convert plain string to Notion rich text array: `[{"type": "text", "text": {"content": text}}]`
2. **`_title_prop(text: str) -> dict`** -- Build a title property value: `{"title": [{"type": "text", "text": {"content": text}}]}`
3. **`_request(method, path, **kwargs) -> dict`** -- Standard request wrapper with error handling (429 rate limit, 400/401/403/404 errors)
4. **`_paginated_params(start_cursor, page_size) -> dict`** -- Build pagination query params

### Error Handling
- **400:** Invalid request body or parameters
- **401:** Invalid or expired token
- **403:** Integration lacks access to the requested resource
- **404:** Resource not found (or integration not shared with it)
- **409:** Conflict (e.g., transaction conflict)
- **429:** Rate limited -- include `Retry-After` value in error message
- **502/503:** Notion service temporarily unavailable

All errors return JSON with `"code"`, `"message"`, and `"request_id"` fields.

### Config Addition (config.py)

```python
NOTION_API_TOKEN: str | None = os.getenv("NOTION_API_TOKEN")
```

### Registration (tools/__init__.py)

```python
from .notion_tool import register_tools as _notion
_notion(mcp)
```

---

## Testing Strategy

### Unit Tests (tests/test_notion_tool.py)
- Mock `httpx.AsyncClient` responses for all 21 tools
- Test rich text helper conversion
- Test error handling (429 rate limit, 404, 401)
- Test pagination parameter construction
- Test filter/sort object pass-through for database queries

### Key Test Scenarios
1. Create page with parent_type="database_id" includes properties correctly
2. Create page with parent_type="page_id" includes title and optional children
3. Query database with compound filters serialized correctly
4. Append block children with various block types
5. Search with and without filter_object_type
6. Create comment with parent_page_id vs discussion_id (mutually exclusive)
7. Rate limit (429) raises ToolError with descriptive message
8. Missing NOTION_API_TOKEN raises ToolError immediately

---

## Dependencies
- **httpx** -- Already in project dependencies (no new packages needed)
- **No SDK needed** -- Direct HTTP is simpler and fully async

## Files to Create/Modify

| File | Action |
|------|--------|
| `src/mcp_toolbox/tools/notion_tool.py` | Create -- 21 tools + helpers |
| `src/mcp_toolbox/config.py` | Modify -- Add `NOTION_API_TOKEN` |
| `src/mcp_toolbox/tools/__init__.py` | Modify -- Register notion tools |
| `tests/test_notion_tool.py` | Create -- Unit tests for all 21 tools |

---

## References
- Notion API Documentation: https://developers.notion.com/reference
- API Versioning: https://developers.notion.com/reference/versioning
- Authentication: https://developers.notion.com/docs/authorization
- Working with databases: https://developers.notion.com/docs/working-with-databases
- Block types: https://developers.notion.com/reference/block
- Rich text: https://developers.notion.com/reference/rich-text
- Property values: https://developers.notion.com/reference/property-value-object
- Pagination: https://developers.notion.com/reference/intro#pagination
- Rate limits: https://developers.notion.com/reference/request-limits
- Status codes: https://developers.notion.com/reference/status-codes
