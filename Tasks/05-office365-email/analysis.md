# Task 05: Office 365 Email Integration - Analysis & Requirements

## Objective
Add Microsoft 365 email sending (and mailbox access) via Microsoft Graph API as a tool integration in mcp-toolbox.

---

## API Technical Details

### Microsoft Graph API v1.0
- **Base URL:** `https://graph.microsoft.com/v1.0`
- **Mail endpoint:** `/users/{user-id}/sendMail` (app-only) or `/me/sendMail` (delegated)
- **Format:** JSON request/response
- **Auth:** OAuth2 Bearer token

### Authentication — Client Credentials Flow (App-Only)

For an MCP server (daemon/service with no user interaction), **client credentials flow** is the right choice:

1. **Register app** in Microsoft Entra ID (Azure AD)
2. **Configure permissions:** `Mail.Send` (application permission, requires admin consent)
3. **Get credentials:** `tenant_id`, `client_id`, `client_secret`
4. **Token acquisition:** `POST https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token`
5. **Send as specific user:** `POST /users/{user-id-or-email}/sendMail`

Token details:
- Access tokens valid for **1 hour**
- No refresh token in client credentials flow — request new token when expired
- The `msal` library handles caching and automatic renewal

### Required Permissions (Application)

| Permission | Type | Description | Admin Consent |
|-----------|------|-------------|---------------|
| `Mail.Send` | Application | Send email as any user | Required |
| `Mail.Read` | Application | Read any user's mailbox | Required |
| `Mail.ReadWrite` | Application | Read/write any user's mailbox (drafts) | Required |

**Security note:** Application Access Policy can restrict the app to specific mailboxes instead of the entire tenant.

### Rate Limits

| Limit | Value |
|-------|-------|
| Requests per 10 min per mailbox | 10,000 |
| Concurrent requests per app per mailbox | 4 |
| Recipients per day per mailbox | 10,000 |
| Messages per minute (Exchange limit) | 30 |
| Attachment via JSON payload | 3 MB max |
| Attachment via upload session | 3-150 MB |
| Total message size | 150 MB |

HTTP 429 with `Retry-After` header on throttle.

---

## Available Capabilities

| Capability | Endpoint Pattern | Notes |
|-----------|-----------------|-------|
| **Send email** | `POST /users/{id}/sendMail` | To, CC, BCC, HTML/text body, attachments, importance |
| **Create draft** | `POST /users/{id}/messages` | Creates in Drafts folder |
| **Send draft** | `POST /users/{id}/messages/{msg-id}/send` | Sends existing draft |
| **Update draft** | `PATCH /users/{id}/messages/{msg-id}` | Modify before sending |
| **Delete draft** | `DELETE /users/{id}/messages/{msg-id}` | Remove unsent draft |
| **List messages** | `GET /users/{id}/messages` | With OData filters |
| **Get message** | `GET /users/{id}/messages/{msg-id}` | Full message details |
| **Search messages** | `GET /users/{id}/messages?$search=...` | Full-text search |
| **Reply** | `POST /users/{id}/messages/{msg-id}/reply` | Reply to sender |
| **Reply All** | `POST /users/{id}/messages/{msg-id}/replyAll` | Reply to all |
| **Forward** | `POST /users/{id}/messages/{msg-id}/forward` | Forward to recipients |
| **Move message** | `POST /users/{id}/messages/{msg-id}/move` | Move between folders |
| **List folders** | `GET /users/{id}/mailFolders` | All mail folders |
| **Get folder** | `GET /users/{id}/mailFolders/{folder-id}` | Single folder details |
| **Create folder** | `POST /users/{id}/mailFolders` | Create new folder |
| **List attachments** | `GET /users/{id}/messages/{msg-id}/attachments` | Message attachments |
| **Add attachment** | `POST /users/{id}/messages/{msg-id}/attachments` | To draft (≤3MB) |

---

## Architecture Decisions

### A1: Direct HTTP with httpx + msal (no msgraph-sdk)
The official `msgraph-sdk` is async-first but heavyweight (kiota-based, complex imports). For targeted mail operations, direct `httpx` calls with `msal` for token management is simpler and consistent with our ClickUp pattern.

### A2: Token Management with msal
Use `msal.ConfidentialClientApplication` for automatic token caching and renewal:
```python
import msal

_msal_app: msal.ConfidentialClientApplication | None = None

def _get_token() -> str:
    global _msal_app
    if _msal_app is None:
        _msal_app = msal.ConfidentialClientApplication(
            client_id=O365_CLIENT_ID,
            client_credential=O365_CLIENT_SECRET,
            authority=f"https://login.microsoftonline.com/{O365_TENANT_ID}",
        )
    result = _msal_app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        raise ToolError(f"Failed to acquire O365 token: {result.get('error_description', 'unknown error')}")
    return result["access_token"]
```

### A3: Shared httpx Client with Per-Request Auth
Use a singleton `httpx.AsyncClient` (like ClickUp) for connection pooling, but pass the Authorization header per-request since tokens expire hourly:
```python
_http_client: httpx.AsyncClient | None = None

def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url="https://graph.microsoft.com/v1.0",
            timeout=30.0,
        )
    return _http_client

async def _request(method: str, path: str, **kwargs) -> dict | list:
    token = await asyncio.to_thread(_get_token)  # sync msal call off event loop
    client = _get_http_client()
    response = await client.request(
        method, path,
        headers={"Authorization": f"Bearer {token}"},
        **kwargs,
    )
    # ... error handling
```

**Note:** `_get_token()` uses `msal.acquire_token_for_client()` which is synchronous. On cache hit it returns instantly; on cache miss (every ~60 min) it makes an HTTP call to `login.microsoftonline.com`. Wrapping in `asyncio.to_thread()` prevents blocking the event loop during token renewal.

### A4: User ID Resolution
All endpoints require `/users/{user-id}`. Accept user_id as optional parameter with fallback to `O365_USER_ID` config:
```python
def _get_user_id(override: str | None = None) -> str:
    user_id = override or O365_USER_ID
    if not user_id:
        raise ToolError("No user_id provided. Set O365_USER_ID or pass user_id.")
    return user_id
```

### A5: Error Handling
Same pattern: catch httpx exceptions, parse Graph API error responses (which return `{"error": {"code": "...", "message": "..."}}`), convert to ToolError.

### A6: Response Format
Same JSON convention: `{"status": "success", ...}`.

### A7: Missing Config Strategy
Same as other integrations: register tools regardless, fail at invocation with clear ToolError.

---

## Configuration Requirements

### Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `O365_TENANT_ID` | Entra ID tenant ID | Yes (at invocation) | `None` |
| `O365_CLIENT_ID` | App registration client ID | Yes (at invocation) | `None` |
| `O365_CLIENT_SECRET` | App client secret | Yes (at invocation) | `None` |
| `O365_USER_ID` | Default sender email/user ID | Yes (at invocation) | `None` |

### Config Pattern
```python
O365_TENANT_ID: str | None = os.getenv("O365_TENANT_ID")
O365_CLIENT_ID: str | None = os.getenv("O365_CLIENT_ID")
O365_CLIENT_SECRET: str | None = os.getenv("O365_CLIENT_SECRET")
O365_USER_ID: str | None = os.getenv("O365_USER_ID")
```

---

## Tool Specifications

### Sending Tools (4 tools)

#### `o365_send_email`
Send an email from an Office 365 mailbox.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | str or list[str] | Yes | Recipient email(s) |
| `subject` | str | Yes | Email subject |
| `body` | str | Yes | Email body |
| `content_type` | str | No | `HTML` or `Text` (default `HTML`) |
| `cc` | str or list[str] | No | CC recipients |
| `bcc` | str or list[str] | No | BCC recipients |
| `importance` | str | No | `low`, `normal`, or `high` |
| `reply_to` | str or list[str] | No | Reply-to addresses |
| `save_to_sent` | bool | No | Save to Sent Items (default true) |
| `user_id` | str | No | Sender mailbox (falls back to config) |

**Returns:** Confirmation with status code.
**Endpoint:** `POST /users/{user_id}/sendMail`

#### `o365_send_email_with_attachment`
Send an email with file attachments (≤3MB per file via JSON).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | str or list[str] | Yes | Recipient email(s) |
| `subject` | str | Yes | Email subject |
| `body` | str | Yes | Email body |
| `attachments` | list[dict] | Yes | `{file_path, file_name?, content_type?}` |
| `content_type` | str | No | `HTML` or `Text` (default `HTML`) |
| `cc` | str or list[str] | No | CC recipients |
| `bcc` | str or list[str] | No | BCC recipients |
| `user_id` | str | No | Sender mailbox |

**Returns:** Confirmation with status code.
**Endpoint:** `POST /users/{user_id}/sendMail`
**Attachment limit:** 3MB per file via JSON payload.

#### `o365_reply`
Reply to an email.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID to reply to |
| `comment` | str | Yes | Reply text (HTML) |
| `user_id` | str | No | Mailbox user |

**Returns:** Confirmation.
**Endpoint:** `POST /users/{user_id}/messages/{message_id}/reply`

#### `o365_reply_all`
Reply to all recipients of an email.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID to reply to |
| `comment` | str | Yes | Reply text (HTML) |
| `user_id` | str | No | Mailbox user |

**Returns:** Confirmation.
**Endpoint:** `POST /users/{user_id}/messages/{message_id}/replyAll`

#### `o365_forward`
Forward an email to new recipients.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID to forward |
| `to` | str or list[str] | Yes | Forward recipients |
| `comment` | str | No | Comment to include |
| `user_id` | str | No | Mailbox user |

**Returns:** Confirmation.
**Endpoint:** `POST /users/{user_id}/messages/{message_id}/forward`

---

### Mailbox Reading Tools (4 tools)

#### `o365_list_messages`
List messages in a mailbox or folder.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `folder` | str | No | Folder name or ID (default: Inbox) |
| `top` | int | No | Max results (default 10, max 1000) |
| `filter` | str | No | OData filter (e.g., `isRead eq false`) |
| `select` | str | No | Fields to return (comma-separated) |
| `order_by` | str | No | Sort field (e.g., `receivedDateTime desc`) |
| `user_id` | str | No | Mailbox user |

**Returns:** List of messages with subject, from, date, preview.
**Endpoint:** `GET /users/{user_id}/mailFolders/{folder}/messages` or `GET /users/{user_id}/messages`

#### `o365_get_message`
Get full details of a specific message.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID |
| `user_id` | str | No | Mailbox user |

**Returns:** Full message with body, attachments, headers.
**Endpoint:** `GET /users/{user_id}/messages/{message_id}`

#### `o365_search_messages`
Search messages using full-text search (KQL — Keyword Query Language).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | Yes | KQL search query |
| `top` | int | No | Max results (default 10) |
| `user_id` | str | No | Mailbox user |

**KQL examples:**
- `"quarterly report"` — search all fields
- `from:john@example.com` — from specific sender
- `subject:invoice` — in subject line
- `hasAttachments:true` — messages with attachments
- `received>=2025-01-01` — received after date

**Returns:** List of matching messages.
**Endpoint:** `GET /users/{user_id}/messages?$search="{query}"`

#### `o365_list_attachments`
List attachments on a message.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID |
| `user_id` | str | No | Mailbox user |

**Returns:** List of attachments with IDs, names, sizes, content types.
**Endpoint:** `GET /users/{user_id}/messages/{message_id}/attachments`

#### `o365_move_message`
Move a message to a different folder.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID |
| `destination_folder` | str | Yes | Folder ID or well-known name (Inbox, Archive, DeletedItems, etc.) |
| `user_id` | str | No | Mailbox user |

**Returns:** Moved message.
**Endpoint:** `POST /users/{user_id}/messages/{message_id}/move`

---

### Draft Management Tools (4 tools)

#### `o365_create_draft`
Create a draft email.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | str | Yes | Email subject |
| `body` | str | Yes | Email body |
| `to` | str or list[str] | No | Recipients (can add later) |
| `content_type` | str | No | `HTML` or `Text` (default `HTML`) |
| `cc` | str or list[str] | No | CC recipients |
| `bcc` | str or list[str] | No | BCC recipients |
| `user_id` | str | No | Mailbox user |

**Returns:** Created draft with message ID.
**Endpoint:** `POST /users/{user_id}/messages`

#### `o365_update_draft`
Update a draft email before sending.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Draft message ID |
| `subject` | str | No | New subject |
| `body` | str | No | New body |
| `to` | str or list[str] | No | New recipients |
| `cc` | str or list[str] | No | New CC |
| `bcc` | str or list[str] | No | New BCC |
| `user_id` | str | No | Mailbox user |

**Returns:** Updated draft.
**Endpoint:** `PATCH /users/{user_id}/messages/{message_id}`

#### `o365_send_draft`
Send an existing draft.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Draft message ID |
| `user_id` | str | No | Mailbox user |

**Returns:** Confirmation.
**Endpoint:** `POST /users/{user_id}/messages/{message_id}/send`

#### `o365_add_draft_attachment`
Add an attachment to a draft message (≤3MB).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Draft message ID |
| `file_path` | str | Yes | Local file path |
| `file_name` | str | No | Override filename |
| `content_type` | str | No | MIME type (default `application/octet-stream`) |
| `user_id` | str | No | Mailbox user |

**Returns:** Created attachment with ID.
**Endpoint:** `POST /users/{user_id}/messages/{message_id}/attachments`

#### `o365_delete_draft`
Delete an unsent draft.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Draft message ID |
| `user_id` | str | No | Mailbox user |

**Returns:** Confirmation.
**Endpoint:** `DELETE /users/{user_id}/messages/{message_id}`

---

### Folder Management Tools (3 tools)

#### `o365_get_folder`
Get details of a specific mail folder.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `folder_id` | str | Yes | Folder ID or well-known name (Inbox, Drafts, SentItems, etc.) |
| `user_id` | str | No | Mailbox user |

**Returns:** Folder with ID, name, message count, unread count.
**Endpoint:** `GET /users/{user_id}/mailFolders/{folder_id}`

#### `o365_list_folders`
List mail folders.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | str | No | Mailbox user |

**Returns:** List of folders with IDs, names, message counts.
**Endpoint:** `GET /users/{user_id}/mailFolders`

#### `o365_create_folder`
Create a new mail folder.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Folder name |
| `parent_folder_id` | str | No | Parent folder ID (creates subfolder) |
| `user_id` | str | No | Mailbox user |

**Returns:** Created folder with ID.
**Endpoint:** `POST /users/{user_id}/mailFolders` or `POST /users/{user_id}/mailFolders/{parent}/childFolders`

#### `o365_delete_folder`
Delete a mail folder.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `folder_id` | str | Yes | Folder ID |
| `user_id` | str | No | Mailbox user |

**Returns:** Confirmation.
**Endpoint:** `DELETE /users/{user_id}/mailFolders/{folder_id}`

---

## Tool Summary (19 tools total)

### Sending (5 tools)
1. `o365_send_email` — Send email
2. `o365_send_email_with_attachment` — Send with attachments
3. `o365_reply` — Reply to sender
4. `o365_reply_all` — Reply to all recipients
5. `o365_forward` — Forward message

### Mailbox Reading (5 tools)
6. `o365_list_messages` — List/filter messages
7. `o365_get_message` — Get message details
8. `o365_search_messages` — Full-text KQL search
9. `o365_list_attachments` — List message attachments
10. `o365_move_message` — Move to folder

### Draft Management (5 tools)
11. `o365_create_draft` — Create draft
12. `o365_update_draft` — Update draft
13. `o365_add_draft_attachment` — Add attachment to draft
14. `o365_send_draft` — Send draft
15. `o365_delete_draft` — Delete draft

### Folder Management (4 tools)
16. `o365_get_folder` — Get folder details
17. `o365_list_folders` — List mail folders
18. `o365_create_folder` — Create folder
19. `o365_delete_folder` — Delete folder

---

## Dependencies

| Package | Purpose | Already in project? |
|---------|---------|-------------------|
| `msal` | Microsoft authentication library (token management) | **New** — add to runtime deps |
| `httpx` | Async HTTP client | Yes |

No new dev dependencies needed — `respx` already available for testing.

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Modify | Add `msal>=1.28.0` to dependencies |
| `src/mcp_toolbox/config.py` | Modify | Add O365 config variables |
| `.env.example` | Modify | Add O365 environment variables |
| `src/mcp_toolbox/tools/o365_tool.py` | **New** | All O365 email tools |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register o365_tool |
| `tests/test_o365_tool.py` | **New** | Tests for all O365 tools |
| `tests/test_server.py` | Modify | Update tool count and names |
| `CLAUDE.md` | Modify | Document O365 integration |

---

## Testing Strategy

### Approach
Mock both `msal` token acquisition and `httpx` HTTP calls:
- Use `unittest.mock.patch` for `msal.ConfidentialClientApplication.acquire_token_for_client`
- Use `respx` for Graph API HTTP mocking

### Test Coverage
1. Happy path for every tool
2. Missing config (tenant_id, client_id, etc.) → ToolError
3. Token acquisition failure → ToolError
4. API errors (401, 403, 429)
5. Input normalization (single string vs list for recipients)

---

## Success Criteria

1. `uv sync` installs `msal` without errors
2. All 19 O365 tools register and are discoverable
3. Tools return meaningful errors when config is missing
4. Token management works (msal caching, expiry handling)
5. New tests pass and full regression suite remains green
6. Total toolbox: 97 existing + 19 new = **116 tools**
