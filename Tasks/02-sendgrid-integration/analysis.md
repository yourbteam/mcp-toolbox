# Task 02: SendGrid Integration (Tiers 1-3) - Analysis & Requirements

## Objective
Add SendGrid as the first tool integration in mcp-toolbox, exposing email sending, email management, and contact management as MCP tools for LLM clients.

**Scope:** Tiers 1 (Core Email), 2 (Email Management), 3 (Contact Management). Tiers 4 (WhatsApp/SMS via Twilio) and 5 (Email Validation) are out of scope for this task.

---

## SDK Technical Details

### Package: `sendgrid` v6.x on PyPI
- **Auth:** API Key via `Authorization: Bearer SG.xxxxx`
- **Base URL:** `api.sendgrid.com`
- **HTTP Client:** Synchronous only — uses `python_http_client` (wraps `requests`)
- **No native async support** — the official SDK is sync. For our async MCP tools, we will wrap sync calls with `asyncio.to_thread()` to avoid blocking the event loop.
- **Rate Limit:** Management/marketing API endpoints are limited to 600 requests/minute (HTTP 429 on exceed, with `X-RateLimit-Reset` header). The mail/send endpoint has plan-dependent rate limits and does not return 429 in the same way. All tools should handle 429 responses gracefully regardless.
- **Thread Safety:** The SDK client is thread-safe — each request creates a new URL opener with no shared mutable state. Safe for concurrent use with `asyncio.to_thread()`.

### Client Initialization
```python
import sendgrid
sg = sendgrid.SendGridAPIClient(api_key="SG.xxxxx")
```

### Response Object
All API calls return a response with:
- `response.status_code` — int (200, 202, 400, 401, 429, etc.)
- `response.body` — bytes (JSON for most endpoints)
- `response.headers` — dict (includes rate limit headers)

### Error Handling
- `python_http_client.exceptions.BadRequestsError` — raised on 4xx errors
- Status 429 — rate limit exceeded, must retry after `X-RateLimit-Reset`
- Status 202 — async operations (e.g., contact upserts) accepted for processing

### Key Import Paths
```python
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, Personalization, To, Cc, Bcc,
    Attachment, FileContent, FileName, FileType, Disposition,
    Content
)
```

---

## Configuration Requirements

### Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `SENDGRID_API_KEY` | SendGrid API key (format: `SG.xxxxx`) | Yes (at tool invocation) | `None` |
| `SENDGRID_FROM_EMAIL` | Default sender email address | Yes (at tool invocation) | `None` |
| `SENDGRID_FROM_NAME` | Default sender display name | No | `None` |

### Config Pattern
Add to `config.py` following the existing `os.getenv()` pattern:
```python
SENDGRID_API_KEY: str | None = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL: str | None = os.getenv("SENDGRID_FROM_EMAIL")
SENDGRID_FROM_NAME: str | None = os.getenv("SENDGRID_FROM_NAME")
```

Add to `.env.example`:
```env
SENDGRID_API_KEY=SG.your-api-key-here
SENDGRID_FROM_EMAIL=sender@yourdomain.com
SENDGRID_FROM_NAME=Your Name
```

### Missing API Key Strategy
The server must start successfully even if SendGrid is not configured. The strategy:
1. **At startup:** Register all SendGrid tools regardless of whether `SENDGRID_API_KEY` is set. Log a warning if it is missing.
2. **At tool invocation:** Each tool checks for the API key before making API calls. If missing, raise `ToolError("SENDGRID_API_KEY is not configured. Set it in your environment or .env file.")`.
3. **Rationale:** The MCP server may host multiple integrations. One unconfigured integration should not prevent others from working.

---

## Tier 1: Core Email Tools

### Tool: `send_email`
Send a transactional email with plain text and/or HTML body.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | str or list[str] | Yes | Recipient email(s) |
| `subject` | str | Yes | Email subject line |
| `body` | str | Yes | Email body (plain text) |
| `html_body` | str | No | HTML version of body |
| `from_email` | str | No | Override default sender |
| `cc` | str or list[str] | No | CC recipients |
| `bcc` | str or list[str] | No | BCC recipients |
| `reply_to` | str | No | Reply-to address |

**Returns:** Message ID and status code.

**SDK Pattern:**
```python
message = Mail(
    from_email=from_email,
    to_emails=to,
    subject=subject,
    plain_text_content=body,
    html_content=html_body
)
# CC/BCC via Personalization object
response = sg.send(message)
```

### Tool: `send_template_email`
Send an email using a SendGrid dynamic template with Handlebars data.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | str or list[str] | Yes | Recipient email(s) |
| `template_id` | str | Yes | Dynamic template ID (format: `d-xxxxx`) |
| `template_data` | dict | Yes | Key-value data for Handlebars substitution |
| `from_email` | str | No | Override default sender |
| `cc` | str or list[str] | No | CC recipients |
| `bcc` | str or list[str] | No | BCC recipients |

**Returns:** Message ID and status code.

**SDK Pattern:**
```python
message = Mail(from_email=from_email, to_emails=to)
message.template_id = template_id
message.dynamic_template_data = template_data
response = sg.send(message)
```

### Tool: `send_email_with_attachment`
Send an email with one or more file attachments.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | str or list[str] | Yes | Recipient email(s) |
| `subject` | str | Yes | Email subject line |
| `body` | str | Yes | Email body (plain text) |
| `html_body` | str | No | HTML version of body |
| `attachments` | list[dict] | Yes | List of `{file_path, file_name?, mime_type?}` |
| `from_email` | str | No | Override default sender |

**Returns:** Message ID and status code.

**Attachment limits:** 7MB per file, 20MB total message size.

**SDK Pattern:**
```python
import base64
with open(file_path, 'rb') as f:
    encoded = base64.b64encode(f.read()).decode()
attachment = Attachment(
    file_content=FileContent(encoded),
    file_type=FileType(mime_type),
    file_name=FileName(file_name),
    disposition=Disposition('attachment')
)
message.attachment = attachment
```

### Tool: `schedule_email`
Schedule an email for future delivery.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | str or list[str] | Yes | Recipient email(s) |
| `subject` | str | Yes | Email subject line |
| `body` | str | Yes | Email body |
| `html_body` | str | No | HTML version |
| `send_at` | str | Yes | ISO datetime or Unix timestamp for delivery |
| `from_email` | str | No | Override default sender |

**Constraint:** Maximum 72 hours in advance.

**Returns:** Message ID and status code.

**SDK Pattern:**
```python
message.send_at = unix_timestamp  # int
response = sg.send(message)
```

---

## Tier 2: Email Management Tools

### Tool: `list_templates`
List available SendGrid dynamic templates.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `page_size` | int | No | Results per page (default 10) |

**Returns:** List of templates with IDs, names, and versions.

**SDK Pattern:**
```python
response = sg.client.templates.get(query_params={'generations': 'dynamic', 'page_size': page_size})
```

### Tool: `get_template`
Get details of a specific template including its active version content.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `template_id` | str | Yes | Template ID (format: `d-xxxxx`) |

**Returns:** Template name, versions, active version content (subject, HTML, plain text).

**SDK Pattern:**
```python
response = sg.client.templates._(template_id).get()
```

### Tool: `get_email_stats`
Retrieve email sending statistics for a date range.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `start_date` | str | Yes | Start date (YYYY-MM-DD) |
| `end_date` | str | No | End date (YYYY-MM-DD), defaults to today |
| `aggregated_by` | str | No | `day`, `week`, or `month` (default: `day`) |

**Returns:** Stats including: requests, delivered, bounces, opens, clicks, spam reports, unsubscribes.

**SDK Pattern:**
```python
params = {'start_date': start_date, 'end_date': end_date, 'aggregated_by': aggregated_by}
response = sg.client.stats.get(query_params=params)
```

### Tool: `get_bounces`
List email addresses that have bounced.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `start_time` | str | No | Start datetime filter |
| `end_time` | str | No | End datetime filter |
| `limit` | int | No | Max results (default 100) |

**Returns:** List of bounced addresses with reason and timestamp.

**SDK Pattern:**
```python
response = sg.client.suppression.bounces.get(query_params=params)
```

### Tool: `get_spam_reports`
List email addresses that reported spam.

**Parameters:** Same as `get_bounces`.

**Returns:** List of addresses with timestamp.

**SDK Pattern:**
```python
response = sg.client.suppression.spam_reports.get(query_params=params)
```

### Tool: `manage_suppressions`
Add or remove email addresses from suppression lists.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `action` | str | Yes | `add` or `remove` |
| `suppression_type` | str | Yes | `bounces`, `blocks`, `spam_reports`, `invalid_emails`, or `global_unsubscribes` |
| `emails` | list[str] | Yes | Email addresses to add/remove |

**Returns:** Confirmation of action taken.

**Suppression type constraints:**
- `add` action is only valid for `global_unsubscribes` (POST `/asm/suppressions/global`). Bounces, blocks, spam reports, and invalid emails are populated by actual email events and cannot be manually added.
- `remove` action is valid for all types (DELETE `/suppression/{type}/{email}`).
- The tool must validate `action`/`suppression_type` combinations and return a clear `ToolError` for invalid ones.

**SDK Patterns:**
```python
# Add to global unsubscribes
sg.client.asm.suppressions._("global").post(request_body={"recipient_emails": emails})
# Remove a bounce
sg.client.suppression.bounces._(email).delete()
# Remove a spam report
sg.client.suppression.spam_reports._(email).delete()
```

---

## Tier 3: Contact Management Tools

### Tool: `add_contacts`
Add or update contacts (upsert by email address).

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `contacts` | list[dict] | Yes | List of contact objects with `email` (required) plus optional `first_name`, `last_name`, and custom fields |
| `list_ids` | list[str] | No | Add contacts to these list IDs |

**Note:** This is an async operation — SendGrid returns 202 and processes in background. Up to 30,000 contacts per request.

**Returns:** Job ID for tracking. Job status can be checked via `GET /marketing/contacts/imports/{job_id}` (future enhancement — not included as a separate tool in this task, but the job ID is returned so users can track if needed).

**SDK Pattern:**
```python
request_body = {"contacts": contacts}
if list_ids:
    request_body["list_ids"] = list_ids
response = sg.client.marketing.contacts.put(request_body=request_body)
```

### Tool: `search_contacts`
Search contacts using SendGrid Query Language (SGQL).

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | Yes | SGQL query (e.g., `email = 'john@example.com'`) |
| `max_results` | int | No | Limit results (default 50) |

**SGQL Examples:**
- `email = 'john@example.com'`
- `first_name = 'John' AND last_name = 'Doe'`
- `email LIKE '%@example.com'`

**Returns:** List of matching contacts with all fields.

**SDK Pattern:**
```python
request_body = {"query": query}
response = sg.client.marketing.contacts.search.post(request_body=request_body)
```

### Tool: `get_contact`
Retrieve a specific contact by ID.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `contact_id` | str | Yes | Contact UUID |

**Returns:** Full contact record.

**SDK Pattern:**
```python
response = sg.client.marketing.contacts._(contact_id).get()
```

### Tool: `manage_lists`
Create, list, or delete contact lists.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `action` | str | Yes | `create`, `list`, or `delete` |
| `name` | str | Conditional | List name (required for `create`) |
| `list_id` | str | Conditional | List ID (required for `delete`) |

**Returns:** List details or confirmation.

**SDK Pattern:**
```python
# Create
response = sg.client.marketing.lists.post(request_body={"name": name})
# List all
response = sg.client.marketing.lists.get()
# Delete
response = sg.client.marketing.lists._(list_id).delete()
```

---

## Architecture Decisions

### A1: Async Wrapping
The SendGrid SDK is synchronous (uses `requests`). Our MCP tools must be async. We will use `asyncio.to_thread()` to run SDK calls off the event loop:
```python
result = await asyncio.to_thread(sg.send, message)
```

### A2: Shared Client Instance
Create a single `SendGridAPIClient` instance in the tool module, initialized from config. Reuse across all tool calls to avoid repeated initialization.

### A3: Tool Module Structure
All SendGrid tools go in `src/mcp_toolbox/tools/sendgrid_tool.py` following the existing `register_tools(mcp)` convention. If the file becomes too large, we can split into `sendgrid_email.py`, `sendgrid_management.py`, `sendgrid_contacts.py` — but start with a single file.

### A4: Error Handling
- Catch `BadRequestsError` and SDK exceptions, convert to `ToolError` for MCP clients
- Parse error response bodies for human-readable messages
- Handle rate limiting (429) with a clear error message including retry timing

### A5: Response Format
All tools return a JSON-serialized string with a consistent structure:
```python
import json
return json.dumps({"status": "success", "message_id": "...", "status_code": 202})
return json.dumps({"status": "error", "error": "...", "status_code": 400})
return json.dumps({"status": "success", "data": [...], "count": 5})
```
Every response includes a `status` field (`"success"` or `"error"`). Success responses include type-specific data fields. Error responses include an `error` field with a human-readable message.

### A6: Input Flexibility
- Accept `to` as either a single string or a list of strings
- Accept `send_at` as either ISO datetime string or Unix timestamp
- Parse and normalize inputs in the tool functions

---

## Testing Strategy

### Approach
Use `unittest.mock.patch` to mock the `SendGridAPIClient` and its fluent API returns. No real API calls in unit tests.

### Mock Pattern
```python
from unittest.mock import patch, MagicMock

@patch("mcp_toolbox.tools.sendgrid_tool.sg")
async def test_send_email(mock_sg):
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.body = b""
    mock_response.headers = {}
    mock_sg.send.return_value = mock_response

    result = await server.call_tool("send_email", {...})
    assert "success" in str(result)
    mock_sg.send.assert_called_once()
```

### Test Coverage
For each tool, test:
1. **Happy path** — valid input, mocked success response
2. **Missing API key** — `SENDGRID_API_KEY` is `None`, expect `ToolError`
3. **API error** — mock 400/401/429 responses, verify error messages
4. **Input normalization** — single string vs list for `to`, ISO date vs timestamp for `send_at`

### Integration Tests (optional, manual)
Tag with `@pytest.mark.integration` for tests that hit the real API. Skipped in CI by default:
```bash
uv run pytest -m integration  # Run only integration tests (requires .env)
uv run pytest -m "not integration"  # Run only unit tests
```

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Modify | Add `sendgrid>=6.0.0` to dependencies |
| `src/mcp_toolbox/config.py` | Modify | Add `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`, `SENDGRID_FROM_NAME` |
| `.env.example` | Modify | Add SendGrid environment variables |
| `src/mcp_toolbox/tools/sendgrid_tool.py` | **New** | All SendGrid tools (Tiers 1-3) |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register sendgrid_tool |
| `tests/test_sendgrid_tool.py` | **New** | Tests for all SendGrid tools |
| `CLAUDE.md` | Modify | Document SendGrid integration |

---

## Dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| `sendgrid` | SendGrid Python SDK | `>=6.0.0` |

No additional system dependencies. The `sendgrid` package brings `python_http_client` and `starkbank-ecdsa` as transitive deps.

---

## Success Criteria

1. `uv sync` installs SendGrid dependency without errors
2. All 14 SendGrid tools register and are discoverable via MCP Inspector
3. `send_email` successfully sends an email through SendGrid API
4. All tools return meaningful error messages on invalid input or API errors
5. New tests pass and full regression suite remains green
6. Config handles missing API key gracefully (tools return clear error, server doesn't crash)

---

## Tool Summary (14 tools total)

### Tier 1 — Core Email (4 tools)
1. `send_email` — Send transactional email
2. `send_template_email` — Send with dynamic template
3. `send_email_with_attachment` — Send with file attachments
4. `schedule_email` — Schedule future delivery

### Tier 2 — Email Management (6 tools)
5. `list_templates` — List dynamic templates
6. `get_template` — Get template details
7. `get_email_stats` — Retrieve sending statistics
8. `get_bounces` — List bounced addresses
9. `get_spam_reports` — List spam report addresses
10. `manage_suppressions` — Add/remove from suppression lists

### Tier 3 — Contact Management (4 tools)
11. `add_contacts` — Add/update contacts
12. `search_contacts` — Search with SGQL
13. `get_contact` — Get contact by ID
14. `manage_lists` — Create/list/delete contact lists
