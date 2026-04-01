# Task 02: SendGrid Integration (Tiers 1-3) - Implementation Plan

## Overview
Implement 14 SendGrid tools across 3 tiers in 7 sequential steps. Each step is independently verifiable.

---

## Step 1: Dependencies & Configuration

### 1a. Add `sendgrid` to `pyproject.toml`
Add to the `dependencies` list in `pyproject.toml`:
```toml
dependencies = [
    "mcp[cli]>=1.6.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.0",
    "pydantic>=2.0.0",
    "sendgrid>=6.0.0",
]
```

### 1b. Add SendGrid config to `src/mcp_toolbox/config.py`
Append after the `LOG_LEVEL` line (line 15):
```python
# SendGrid
SENDGRID_API_KEY: str | None = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL: str | None = os.getenv("SENDGRID_FROM_EMAIL")
SENDGRID_FROM_NAME: str | None = os.getenv("SENDGRID_FROM_NAME")
```

### 1c. Update `.env.example`
Replace the placeholder comment with actual SendGrid variables:
```env
# SendGrid Integration
SENDGRID_API_KEY=SG.your-api-key-here
SENDGRID_FROM_EMAIL=sender@yourdomain.com
SENDGRID_FROM_NAME=Your Name
```

### 1d. Run `uv sync`
```bash
uv sync --dev --all-extras
```
**Verify:** `sendgrid` installs successfully, `uv run python -c "import sendgrid; print(sendgrid.__version__)"` prints version.

---

## Step 2: Tool Module Foundation

Create `src/mcp_toolbox/tools/sendgrid_tool.py` with the shared infrastructure: client initialization, helper functions, API key guard, and the `register_tools()` entry point.

```python
"""SendGrid integration — email sending, management, and contact tools."""

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Attachment,
    Bcc,
    Cc,
    Disposition,
    FileContent,
    FileName,
    FileType,
    Mail,
    Personalization,
    To,
)

from mcp_toolbox.config import SENDGRID_API_KEY, SENDGRID_FROM_EMAIL, SENDGRID_FROM_NAME

logger = logging.getLogger(__name__)

# Shared client instance — initialized lazily on first use
_sg: SendGridAPIClient | None = None


def _get_client() -> SendGridAPIClient:
    """Get or create the SendGrid client. Raises ToolError if API key is missing."""
    global _sg
    if not SENDGRID_API_KEY:
        raise ToolError(
            "SENDGRID_API_KEY is not configured. "
            "Set it in your environment or .env file."
        )
    if _sg is None:
        _sg = SendGridAPIClient(api_key=SENDGRID_API_KEY)
    return _sg


def _get_from_email(override: str | None = None) -> str:
    """Resolve sender email: override > config > error."""
    email = override or SENDGRID_FROM_EMAIL
    if not email:
        raise ToolError(
            "No sender email provided. Either pass from_email or set "
            "SENDGRID_FROM_EMAIL in your environment."
        )
    return email


def _ensure_list(value: str | list[str]) -> list[str]:
    """Normalize a string-or-list input to a list."""
    if isinstance(value, str):
        return [value]
    return value


def _parse_send_at(send_at: str | int) -> int:
    """Parse send_at as Unix timestamp or ISO datetime string."""
    if isinstance(send_at, int):
        return send_at
    try:
        return int(send_at)
    except ValueError:
        pass
    dt = datetime.fromisoformat(send_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _parse_response(response) -> dict:
    """Parse a SendGrid API response into a dict."""
    body = response.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    if body:
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"raw": body}
    return {}


def _success(status_code: int, **kwargs) -> str:
    """Build a success JSON response."""
    return json.dumps({"status": "success", "status_code": status_code, **kwargs})


def _extract_message_id(headers) -> str | None:
    """Extract the X-Message-Id from SendGrid response headers."""
    if hasattr(headers, "get"):
        return headers.get("X-Message-Id")
    return None


def register_tools(mcp: FastMCP) -> None:
    """Register all SendGrid tools with the MCP server."""

    if not SENDGRID_API_KEY:
        logger.warning(
            "SENDGRID_API_KEY not set — SendGrid tools will be registered "
            "but will fail at invocation until configured."
        )

    # --- Tier 1: Core Email Tools ---
    # (defined in Step 3)

    # --- Tier 2: Email Management Tools ---
    # (defined in Step 4)

    # --- Tier 3: Contact Management Tools ---
    # (defined in Step 5)
```

Key design decisions:
- **Lazy client init** via `_get_client()` — avoids crash if API key missing at import time
- **`_get_from_email()`** — resolves sender with override > config fallback
- **`_ensure_list()`** — normalizes `str | list[str]` inputs
- **`_parse_send_at()`** — handles both Unix timestamps and ISO datetime strings
- **`_success()`** — consistent JSON response builder
- **Warning at registration** — logged once at startup if key is missing

---

## Step 3: Tier 1 — Core Email Tools (4 tools)

Add inside `register_tools()`, replacing the Tier 1 placeholder comment:

### 3a. `send_email`
```python
    @mcp.tool()
    async def send_email(
        to: str | list[str],
        subject: str,
        body: str,
        html_body: str | None = None,
        from_email: str | None = None,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        reply_to: str | None = None,
    ) -> str:
        """Send a transactional email via SendGrid.

        Args:
            to: Recipient email address(es)
            subject: Email subject line
            body: Plain text email body
            html_body: Optional HTML version of the body
            from_email: Sender email (overrides default)
            cc: CC recipient(s)
            bcc: BCC recipient(s)
            reply_to: Reply-to email address
        """
        sg = _get_client()
        sender = _get_from_email(from_email)

        message = Mail(
            from_email=sender,
            subject=subject,
            plain_text_content=body,
            html_content=html_body,
        )

        personalization = Personalization()
        for addr in _ensure_list(to):
            personalization.add_to(To(addr))
        if cc:
            for addr in _ensure_list(cc):
                personalization.add_cc(Cc(addr))
        if bcc:
            for addr in _ensure_list(bcc):
                personalization.add_bcc(Bcc(addr))
        message.add_personalization(personalization)

        if reply_to:
            message.reply_to = reply_to

        logger.info("Sending email to=%s subject=%s", to, subject)
        try:
            response = await asyncio.to_thread(sg.send, message)
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        message_id = _extract_message_id(response.headers)
        return _success(response.status_code, message_id=message_id)
```

### 3b. `send_template_email`
```python
    @mcp.tool()
    async def send_template_email(
        to: str | list[str],
        template_id: str,
        template_data: dict,
        from_email: str | None = None,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
    ) -> str:
        """Send an email using a SendGrid dynamic template.

        Args:
            to: Recipient email address(es)
            template_id: SendGrid dynamic template ID (format: d-xxxxx)
            template_data: Key-value data for Handlebars substitution
            from_email: Sender email (overrides default)
            cc: CC recipient(s)
            bcc: BCC recipient(s)
        """
        sg = _get_client()
        sender = _get_from_email(from_email)

        message = Mail(from_email=sender)
        message.template_id = template_id

        personalization = Personalization()
        for addr in _ensure_list(to):
            personalization.add_to(To(addr))
        if cc:
            for addr in _ensure_list(cc):
                personalization.add_cc(Cc(addr))
        if bcc:
            for addr in _ensure_list(bcc):
                personalization.add_bcc(Bcc(addr))
        personalization.dynamic_template_data = template_data
        message.add_personalization(personalization)

        logger.info("Sending template email to=%s template_id=%s", to, template_id)
        try:
            response = await asyncio.to_thread(sg.send, message)
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        message_id = _extract_message_id(response.headers)
        return _success(response.status_code, message_id=message_id)
```

### 3c. `send_email_with_attachment`
```python
    @mcp.tool()
    async def send_email_with_attachment(
        to: str | list[str],
        subject: str,
        body: str,
        attachments: list[dict],
        html_body: str | None = None,
        from_email: str | None = None,
    ) -> str:
        """Send an email with file attachments via SendGrid.

        Args:
            to: Recipient email address(es)
            subject: Email subject line
            body: Plain text email body
            attachments: List of attachment dicts with keys: file_path (required),
                        file_name (optional), mime_type (optional, default application/octet-stream)
            html_body: Optional HTML version of the body
            from_email: Sender email (overrides default)
        """
        sg = _get_client()
        sender = _get_from_email(from_email)

        message = Mail(
            from_email=sender,
            to_emails=_ensure_list(to),
            subject=subject,
            plain_text_content=body,
            html_content=html_body,
        )

        for att in attachments:
            file_path = att.get("file_path")
            if not file_path:
                raise ToolError("Each attachment must have a 'file_path' key.")

            try:
                with open(file_path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode()
            except FileNotFoundError:
                raise ToolError(f"Attachment file not found: {file_path}")
            except OSError as e:
                raise ToolError(f"Error reading attachment {file_path}: {e}")

            file_name = att.get("file_name", file_path.split("/")[-1])
            mime_type = att.get("mime_type", "application/octet-stream")

            attachment = Attachment(
                file_content=FileContent(encoded),
                file_type=FileType(mime_type),
                file_name=FileName(file_name),
                disposition=Disposition("attachment"),
            )
            message.attachment = attachment

        logger.info("Sending email with %d attachment(s) to=%s", len(attachments), to)
        try:
            response = await asyncio.to_thread(sg.send, message)
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        message_id = _extract_message_id(response.headers)
        return _success(response.status_code, message_id=message_id)
```

### 3d. `schedule_email`
```python
    @mcp.tool()
    async def schedule_email(
        to: str | list[str],
        subject: str,
        body: str,
        send_at: str | int,
        html_body: str | None = None,
        from_email: str | None = None,
    ) -> str:
        """Schedule an email for future delivery via SendGrid.

        Args:
            to: Recipient email address(es)
            subject: Email subject line
            body: Plain text email body
            send_at: Delivery time as ISO datetime string or Unix timestamp (max 72h ahead)
            html_body: Optional HTML version of the body
            from_email: Sender email (overrides default)
        """
        sg = _get_client()
        sender = _get_from_email(from_email)

        timestamp = _parse_send_at(send_at)

        message = Mail(
            from_email=sender,
            to_emails=_ensure_list(to),
            subject=subject,
            plain_text_content=body,
            html_content=html_body,
        )
        message.send_at = timestamp

        logger.info("Scheduling email to=%s send_at=%s", to, timestamp)
        try:
            response = await asyncio.to_thread(sg.send, message)
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        message_id = _extract_message_id(response.headers)
        return _success(
            response.status_code,
            message_id=message_id,
            scheduled_for=timestamp,
        )
```

---

## Step 4: Tier 2 — Email Management Tools (6 tools)

Add inside `register_tools()`, replacing the Tier 2 placeholder comment:

### 4a. `list_templates`
```python
    @mcp.tool()
    async def list_templates(page_size: int = 10) -> str:
        """List available SendGrid dynamic email templates.

        Args:
            page_size: Number of templates per page (default 10)
        """
        sg = _get_client()
        params = {"generations": "dynamic", "page_size": page_size}

        try:
            response = await asyncio.to_thread(
                sg.client.templates.get, query_params=params
            )
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        data = _parse_response(response)
        templates = data.get("templates", data.get("result", []))
        return _success(
            response.status_code,
            data=[
                {"id": t.get("id"), "name": t.get("name"), "updated_at": t.get("updated_at")}
                for t in templates
            ] if isinstance(templates, list) else templates,
            count=len(templates) if isinstance(templates, list) else 0,
        )
```

### 4b. `get_template`
```python
    @mcp.tool()
    async def get_template(template_id: str) -> str:
        """Get details of a specific SendGrid dynamic template.

        Args:
            template_id: Template ID (format: d-xxxxx)
        """
        sg = _get_client()

        try:
            response = await asyncio.to_thread(
                sg.client.templates._(template_id).get
            )
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        data = _parse_response(response)
        return _success(response.status_code, data=data)
```

### 4c. `get_email_stats`
```python
    @mcp.tool()
    async def get_email_stats(
        start_date: str,
        end_date: str | None = None,
        aggregated_by: str = "day",
    ) -> str:
        """Retrieve SendGrid email sending statistics for a date range.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD), defaults to today
            aggregated_by: Aggregation period: 'day', 'week', or 'month'
        """
        sg = _get_client()

        if not end_date:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        params = {
            "start_date": start_date,
            "end_date": end_date,
            "aggregated_by": aggregated_by,
        }

        try:
            response = await asyncio.to_thread(
                sg.client.stats.get, query_params=params
            )
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        data = _parse_response(response)
        return _success(response.status_code, data=data)
```

### 4d. `get_bounces`
```python
    @mcp.tool()
    async def get_bounces(
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 100,
    ) -> str:
        """List email addresses that have bounced in SendGrid.

        Args:
            start_time: Filter by start time (Unix timestamp)
            end_time: Filter by end time (Unix timestamp)
            limit: Maximum results to return (default 100)
        """
        sg = _get_client()

        params: dict = {"limit": limit}
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        try:
            response = await asyncio.to_thread(
                sg.client.suppression.bounces.get, query_params=params
            )
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        data = _parse_response(response)
        items = data if isinstance(data, list) else data.get("result", [])
        return _success(response.status_code, data=items, count=len(items))
```

### 4e. `get_spam_reports`
```python
    @mcp.tool()
    async def get_spam_reports(
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 100,
    ) -> str:
        """List email addresses that reported spam in SendGrid.

        Args:
            start_time: Filter by start time (Unix timestamp)
            end_time: Filter by end time (Unix timestamp)
            limit: Maximum results to return (default 100)
        """
        sg = _get_client()

        params: dict = {"limit": limit}
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        try:
            response = await asyncio.to_thread(
                sg.client.suppression.spam_reports.get, query_params=params
            )
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        data = _parse_response(response)
        items = data if isinstance(data, list) else data.get("result", [])
        return _success(response.status_code, data=items, count=len(items))
```

### 4f. `manage_suppressions`
```python
    @mcp.tool()
    async def manage_suppressions(
        action: str,
        suppression_type: str,
        emails: list[str],
    ) -> str:
        """Add or remove email addresses from SendGrid suppression lists.

        Args:
            action: 'add' or 'remove'
            suppression_type: One of 'bounces', 'blocks', 'spam_reports',
                            'invalid_emails', or 'global_unsubscribes'
            emails: List of email addresses
        """
        sg = _get_client()

        valid_types = ["bounces", "blocks", "spam_reports", "invalid_emails", "global_unsubscribes"]
        if suppression_type not in valid_types:
            raise ToolError(
                f"Invalid suppression_type '{suppression_type}'. "
                f"Must be one of: {', '.join(valid_types)}"
            )

        if action == "add":
            if suppression_type != "global_unsubscribes":
                raise ToolError(
                    f"Cannot manually add to '{suppression_type}'. "
                    "Only 'global_unsubscribes' supports the 'add' action. "
                    "Other suppression types are populated by email events."
                )
            try:
                response = await asyncio.to_thread(
                    sg.client.asm.suppressions._("global").post,
                    request_body={"recipient_emails": emails},
                )
            except Exception as e:
                raise ToolError(f"SendGrid API error: {e}") from e

            return _success(response.status_code, action="added", emails=emails)

        elif action == "remove":
            results = []
            endpoint_map = {
                "bounces": sg.client.suppression.bounces,
                "blocks": sg.client.suppression.blocks,
                "spam_reports": sg.client.suppression.spam_reports,
                "invalid_emails": sg.client.suppression.invalid_emails,
                "global_unsubscribes": sg.client.asm.suppressions._("global"),
            }
            endpoint = endpoint_map[suppression_type]

            for email in emails:
                try:
                    response = await asyncio.to_thread(
                        endpoint._(email).delete
                    )
                    results.append({"email": email, "status": "removed"})
                except Exception as e:
                    results.append({"email": email, "status": "error", "error": str(e)})

            return _success(200, action="removed", results=results)

        else:
            raise ToolError(f"Invalid action '{action}'. Must be 'add' or 'remove'.")
```

---

## Step 5: Tier 3 — Contact Management Tools (4 tools)

Add inside `register_tools()`, replacing the Tier 3 placeholder comment:

### 5a. `add_contacts`
```python
    @mcp.tool()
    async def add_contacts(
        contacts: list[dict],
        list_ids: list[str] | None = None,
    ) -> str:
        """Add or update contacts in SendGrid (upsert by email).

        Args:
            contacts: List of contact dicts. Each must have 'email'.
                     Optional: 'first_name', 'last_name', custom fields.
            list_ids: Optional list IDs to add contacts to.
        """
        sg = _get_client()

        for c in contacts:
            if "email" not in c:
                raise ToolError("Each contact must have an 'email' field.")

        request_body: dict = {"contacts": contacts}
        if list_ids:
            request_body["list_ids"] = list_ids

        logger.info("Upserting %d contact(s)", len(contacts))
        try:
            response = await asyncio.to_thread(
                sg.client.marketing.contacts.put,
                request_body=request_body,
            )
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        data = _parse_response(response)
        job_id = data.get("job_id")
        return _success(response.status_code, job_id=job_id, contacts_count=len(contacts))
```

### 5b. `search_contacts`
```python
    @mcp.tool()
    async def search_contacts(query: str) -> str:
        """Search SendGrid contacts using SGQL (SendGrid Query Language).

        Args:
            query: SGQL query string. Examples:
                  - email = 'john@example.com'
                  - first_name = 'John' AND last_name = 'Doe'
                  - email LIKE '%@example.com'
        """
        sg = _get_client()

        try:
            response = await asyncio.to_thread(
                sg.client.marketing.contacts.search.post,
                request_body={"query": query},
            )
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        data = _parse_response(response)
        results = data.get("result", [])
        return _success(
            response.status_code,
            data=results,
            count=data.get("contact_count", len(results)),
        )
```

### 5c. `get_contact`
```python
    @mcp.tool()
    async def get_contact(contact_id: str) -> str:
        """Retrieve a specific SendGrid contact by ID.

        Args:
            contact_id: Contact UUID
        """
        sg = _get_client()

        try:
            response = await asyncio.to_thread(
                sg.client.marketing.contacts._(contact_id).get
            )
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        data = _parse_response(response)
        return _success(response.status_code, data=data)
```

### 5d. `manage_lists`
```python
    @mcp.tool()
    async def manage_lists(
        action: str,
        name: str | None = None,
        list_id: str | None = None,
    ) -> str:
        """Create, list, or delete SendGrid contact lists.

        Args:
            action: 'create', 'list', or 'delete'
            name: List name (required for 'create')
            list_id: List ID (required for 'delete')
        """
        sg = _get_client()

        if action == "create":
            if not name:
                raise ToolError("'name' is required for action 'create'.")
            try:
                response = await asyncio.to_thread(
                    sg.client.marketing.lists.post,
                    request_body={"name": name},
                )
            except Exception as e:
                raise ToolError(f"SendGrid API error: {e}") from e

            data = _parse_response(response)
            return _success(response.status_code, data=data)

        elif action == "list":
            try:
                response = await asyncio.to_thread(
                    sg.client.marketing.lists.get
                )
            except Exception as e:
                raise ToolError(f"SendGrid API error: {e}") from e

            data = _parse_response(response)
            lists = data.get("result", [])
            return _success(response.status_code, data=lists, count=len(lists))

        elif action == "delete":
            if not list_id:
                raise ToolError("'list_id' is required for action 'delete'.")
            try:
                response = await asyncio.to_thread(
                    sg.client.marketing.lists._(list_id).delete
                )
            except Exception as e:
                raise ToolError(f"SendGrid API error: {e}") from e

            return _success(response.status_code, deleted_list_id=list_id)

        else:
            raise ToolError(f"Invalid action '{action}'. Must be 'create', 'list', or 'delete'.")
```

---

## Step 6: Register SendGrid Tools

### 6a. Update `src/mcp_toolbox/tools/__init__.py`
```python
"""Tool registration hub — imports all tool modules and registers them."""

from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools import example_tool, sendgrid_tool


def register_all_tools(mcp: FastMCP) -> None:
    """Register all tool modules with the MCP server."""
    example_tool.register_tools(mcp)
    sendgrid_tool.register_tools(mcp)
```

---

## Step 7: Tests

Create `tests/test_sendgrid_tool.py` with mocked SendGrid API calls. No real API calls.

### 7a. Test Infrastructure & Fixtures
```python
"""Tests for SendGrid tool integration."""

import json
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.sendgrid_tool import register_tools


def _mock_response(status_code=202, body=b"", headers=None):
    """Create a mock SendGrid API response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.body = body
    resp.headers = headers or {"X-Message-Id": "test-message-id-123"}
    return resp


def _get_result_data(result) -> dict:
    """Extract and parse JSON from call_tool result.
    
    call_tool returns (list[TextContent], dict). Access result[0][0].text
    to get the tool's JSON string output.
    """
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    """Create a test MCP server with SendGrid tools registered.
    
    Uses yield to keep config patches active for the duration of the test.
    Resets the cached _sg client between tests to prevent leakage.
    """
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.sendgrid_tool.SENDGRID_API_KEY", "SG.test-key"), \
         patch("mcp_toolbox.tools.sendgrid_tool.SENDGRID_FROM_EMAIL", "test@example.com"), \
         patch("mcp_toolbox.tools.sendgrid_tool.SENDGRID_FROM_NAME", "Test Sender"), \
         patch("mcp_toolbox.tools.sendgrid_tool._sg", None):
        register_tools(mcp)
        yield mcp
```

**Critical design notes:**
- **`yield` not `return`** — patches must stay active during test execution, not just during registration
- **`_sg` reset to `None`** — prevents cached client from one test leaking into the next
- **`_get_result_data()`** — `call_tool()` returns `(list[TextContent], dict)`, so the text is at `result[0][0].text`

### 7b. Tier 1 Tests — Core Email

```python
# --- Missing API Key ---

@pytest.mark.asyncio
async def test_send_email_missing_api_key():
    """Tools should raise ToolError when API key is not configured."""
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.sendgrid_tool.SENDGRID_API_KEY", None), \
         patch("mcp_toolbox.tools.sendgrid_tool.SENDGRID_FROM_EMAIL", "test@example.com"), \
         patch("mcp_toolbox.tools.sendgrid_tool._sg", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="SENDGRID_API_KEY"):
            await mcp.call_tool("send_email", {
                "to": "user@example.com",
                "subject": "Test",
                "body": "Hello",
            })


# --- send_email ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_send_email_success(mock_sg, server):
    mock_sg.send.return_value = _mock_response(202)

    result = await server.call_tool("send_email", {
        "to": "user@example.com",
        "subject": "Test Subject",
        "body": "Hello World",
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["status_code"] == 202
    mock_sg.send.assert_called_once()


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_send_email_with_cc_bcc(mock_sg, server):
    mock_sg.send.return_value = _mock_response(202)

    result = await server.call_tool("send_email", {
        "to": ["user1@example.com", "user2@example.com"],
        "subject": "Test",
        "body": "Hello",
        "cc": "cc@example.com",
        "bcc": ["bcc1@example.com", "bcc2@example.com"],
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


# --- send_template_email ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_send_template_email_success(mock_sg, server):
    mock_sg.send.return_value = _mock_response(202)

    result = await server.call_tool("send_template_email", {
        "to": "user@example.com",
        "template_id": "d-abc123",
        "template_data": {"name": "John", "code": "XYZ"},
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


# --- schedule_email ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_schedule_email_unix_timestamp(mock_sg, server):
    mock_sg.send.return_value = _mock_response(202)

    result = await server.call_tool("schedule_email", {
        "to": "user@example.com",
        "subject": "Scheduled",
        "body": "Future email",
        "send_at": 1735689600,
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["scheduled_for"] == 1735689600


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_schedule_email_iso_datetime(mock_sg, server):
    mock_sg.send.return_value = _mock_response(202)

    result = await server.call_tool("schedule_email", {
        "to": "user@example.com",
        "subject": "Scheduled",
        "body": "Future email",
        "send_at": "2025-01-01T12:00:00+00:00",
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
```

### 7c. Tier 2 Tests — Email Management

```python
# --- list_templates ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_list_templates(mock_sg, server):
    mock_sg.client.templates.get.return_value = _mock_response(
        200, json.dumps({"templates": [
            {"id": "d-1", "name": "Welcome", "updated_at": "2025-01-01"},
            {"id": "d-2", "name": "Reset", "updated_at": "2025-01-02"},
        ]}).encode()
    )

    result = await server.call_tool("list_templates", {})
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["count"] == 2


# --- get_email_stats ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_get_email_stats(mock_sg, server):
    mock_sg.client.stats.get.return_value = _mock_response(
        200, json.dumps([{"date": "2025-01-01", "stats": []}]).encode()
    )

    result = await server.call_tool("get_email_stats", {
        "start_date": "2025-01-01",
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


# --- get_bounces ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_get_bounces(mock_sg, server):
    mock_sg.client.suppression.bounces.get.return_value = _mock_response(
        200, json.dumps([{"email": "bad@example.com", "reason": "550"}]).encode()
    )

    result = await server.call_tool("get_bounces", {})
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["count"] == 1


# --- manage_suppressions ---

@pytest.mark.asyncio
async def test_manage_suppressions_add_invalid_type(server):
    """Adding to bounces should fail — only global_unsubscribes supports add."""
    with pytest.raises(Exception, match="Cannot manually add"):
        await server.call_tool("manage_suppressions", {
            "action": "add",
            "suppression_type": "bounces",
            "emails": ["test@example.com"],
        })


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_manage_suppressions_add_global(mock_sg, server):
    mock_sg.client.asm.suppressions._("global").post.return_value = _mock_response(201)

    result = await server.call_tool("manage_suppressions", {
        "action": "add",
        "suppression_type": "global_unsubscribes",
        "emails": ["unsub@example.com"],
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
```

### 7d. Tier 3 Tests — Contact Management

```python
# --- add_contacts ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_add_contacts(mock_sg, server):
    mock_sg.client.marketing.contacts.put.return_value = _mock_response(
        202, json.dumps({"job_id": "job-123"}).encode()
    )

    result = await server.call_tool("add_contacts", {
        "contacts": [
            {"email": "john@example.com", "first_name": "John"},
            {"email": "jane@example.com", "first_name": "Jane"},
        ],
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["job_id"] == "job-123"
    assert result_data["contacts_count"] == 2


@pytest.mark.asyncio
async def test_add_contacts_missing_email(server):
    """Contacts without 'email' field should fail."""
    with pytest.raises(Exception, match="email"):
        await server.call_tool("add_contacts", {
            "contacts": [{"first_name": "John"}],
        })


# --- search_contacts ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_search_contacts(mock_sg, server):
    mock_sg.client.marketing.contacts.search.post.return_value = _mock_response(
        200, json.dumps({
            "result": [{"email": "john@example.com", "first_name": "John"}],
            "contact_count": 1,
        }).encode()
    )

    result = await server.call_tool("search_contacts", {
        "query": "email = 'john@example.com'",
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["count"] == 1


# --- manage_lists ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_manage_lists_create(mock_sg, server):
    mock_sg.client.marketing.lists.post.return_value = _mock_response(
        201, json.dumps({"id": "list-abc", "name": "VIPs"}).encode()
    )

    result = await server.call_tool("manage_lists", {
        "action": "create",
        "name": "VIPs",
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


@pytest.mark.asyncio
async def test_manage_lists_create_missing_name(server):
    """Creating a list without a name should fail."""
    with pytest.raises(Exception, match="name"):
        await server.call_tool("manage_lists", {"action": "create"})
```

### 7e. Missing Tool Tests (complete coverage)

```python
# --- send_email_with_attachment ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_send_email_with_attachment(mock_sg, server, tmp_path):
    mock_sg.send.return_value = _mock_response(202)

    # Create a temp file to attach
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello attachment")

    result = await server.call_tool("send_email_with_attachment", {
        "to": "user@example.com",
        "subject": "With attachment",
        "body": "See attached",
        "attachments": [{"file_path": str(test_file)}],
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    mock_sg.send.assert_called_once()


@pytest.mark.asyncio
async def test_send_email_with_attachment_missing_file(server):
    """Attachment with nonexistent file should fail."""
    with pytest.raises(Exception, match="not found"):
        await server.call_tool("send_email_with_attachment", {
            "to": "user@example.com",
            "subject": "Test",
            "body": "Test",
            "attachments": [{"file_path": "/nonexistent/file.txt"}],
        })


# --- get_template ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_get_template(mock_sg, server):
    mock_sg.client.templates._("d-123").get.return_value = _mock_response(
        200, json.dumps({"id": "d-123", "name": "Welcome"}).encode()
    )

    result = await server.call_tool("get_template", {"template_id": "d-123"})
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


# --- get_spam_reports ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_get_spam_reports(mock_sg, server):
    mock_sg.client.suppression.spam_reports.get.return_value = _mock_response(
        200, json.dumps([{"email": "spam@example.com"}]).encode()
    )

    result = await server.call_tool("get_spam_reports", {})
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["count"] == 1


# --- get_contact ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_get_contact(mock_sg, server):
    mock_sg.client.marketing.contacts._("contact-uuid").get.return_value = _mock_response(
        200, json.dumps({"id": "contact-uuid", "email": "john@example.com"}).encode()
    )

    result = await server.call_tool("get_contact", {"contact_id": "contact-uuid"})
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
```

### 7f. API Error Response Tests

```python
# --- API error handling ---

@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_send_email_api_error(mock_sg, server):
    """API errors should be converted to ToolError."""
    mock_sg.send.side_effect = Exception("403 Forbidden: insufficient permissions")

    with pytest.raises(Exception, match="SendGrid API error"):
        await server.call_tool("send_email", {
            "to": "user@example.com",
            "subject": "Test",
            "body": "Hello",
        })


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_list_templates_api_error(mock_sg, server):
    """Management API errors should be converted to ToolError."""
    mock_sg.client.templates.get.side_effect = Exception("429 Too Many Requests")

    with pytest.raises(Exception, match="SendGrid API error"):
        await server.call_tool("list_templates", {})
```

### 7g. Update `test_server.py`

Update the tool count assertion to verify SendGrid tools are registered:
```python
def test_server_has_tools():
    # After import, tools should be registered (2 example + 14 sendgrid)
    tools = mcp._tool_manager._tools
    assert len(tools) >= 16
```

**Note:** Uses `>=` instead of `==` to avoid brittleness if more tools are added later.

---

## Step 8: Documentation & Validation

### 8a. Update `CLAUDE.md`
Add to the Source Layout section that `sendgrid_tool.py` exists. Add a brief note about the SendGrid integration in the project overview.

### 8b. Run validation
```bash
# Install new dependency
uv sync --dev --all-extras

# Run all tests (regression + new)
uv run pytest -v

# Lint
uv run ruff check src/ tests/

# Type check
uv run pyright src/
```

### 8c. Success criteria verification
1. `uv sync` — sendgrid installs
2. All 14 tools registered — verify via `uv run pytest tests/test_server.py` (tool count check)
3. All new tests pass
4. Full regression suite green
5. Ruff + pyright clean

---

## Execution Order

| Order | Step | Description | Depends On |
|-------|------|-------------|------------|
| 1 | Dependencies & config | pyproject.toml, config.py, .env.example | — |
| 2 | Tool module foundation | sendgrid_tool.py scaffolding + helpers | Step 1 |
| 3 | Tier 1 tools | 4 email sending tools | Step 2 |
| 4 | Tier 2 tools | 6 email management tools | Step 2 |
| 5 | Tier 3 tools | 4 contact management tools | Step 2 |
| 6 | Registration | tools/__init__.py update | Steps 3-5 |
| 7 | Tests | test_sendgrid_tool.py | Steps 3-6 |
| 8 | Docs & validation | CLAUDE.md, full test run | Steps 1-7 |

Steps 3, 4, and 5 are independent of each other (all depend only on Step 2).

---

## Risk Notes

- **Fluent API mocking:** The `sg.client.x.y.z.get()` chain requires careful mock setup. If mock chaining fails, use `MagicMock()`'s auto-speccing — `MagicMock()` automatically creates child mocks for chained attribute access.
- **`call_tool` return format:** Returns a tuple `(list[TextContent], dict)`. Tests access `result[0][0].text` to get the tool's string output via the `_get_result_data()` helper. Assertions parse this as JSON.
- **`send_at` type:** MCP may serialize the parameter as a string even if declared as `str | int`. The `_parse_send_at()` helper handles both.
- **Attachment security:** `send_email_with_attachment` reads files from the local filesystem. The MCP client controls what paths are passed — this is acceptable for a tool-use pattern but worth noting.
