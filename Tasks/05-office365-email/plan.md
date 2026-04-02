# Task 05: Office 365 Email Integration - Implementation Plan

## Overview
Implement 19 O365 email tools using Microsoft Graph API with `msal` for OAuth2 token management and `httpx` for HTTP calls. 

**Final state:** 116 tools total (97 existing + 19 new).

---

## Step 1: Dependencies & Configuration

### 1a. Add `msal` to `pyproject.toml`
```toml
dependencies = [
    "mcp[cli]>=1.6.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.0",
    "pydantic>=2.0.0",
    "sendgrid>=6.0.0",
    "msal>=1.28.0",
]
```

### 1b. Add O365 config to `src/mcp_toolbox/config.py`
Append after ClickUp variables:
```python
# Office 365 (Microsoft Graph)
O365_TENANT_ID: str | None = os.getenv("O365_TENANT_ID")
O365_CLIENT_ID: str | None = os.getenv("O365_CLIENT_ID")
O365_CLIENT_SECRET: str | None = os.getenv("O365_CLIENT_SECRET")
O365_USER_ID: str | None = os.getenv("O365_USER_ID")
```

### 1c. Update `.env.example`
```env
# Office 365 (Microsoft Graph) Integration
O365_TENANT_ID=your-entra-id-tenant-id
O365_CLIENT_ID=your-app-registration-client-id
O365_CLIENT_SECRET=your-app-client-secret
O365_USER_ID=sender@yourdomain.com
```

### 1d. Run `uv sync`
```bash
uv sync --dev --all-extras
```

---

## Step 2: Tool Module Foundation

Create `src/mcp_toolbox/tools/o365_tool.py`:

```python
"""Office 365 email integration — send, read, drafts, folders via Microsoft Graph."""

import asyncio
import base64
import json
import logging
from pathlib import Path

import httpx
import msal
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import O365_CLIENT_ID, O365_CLIENT_SECRET, O365_TENANT_ID, O365_USER_ID

logger = logging.getLogger(__name__)

_msal_app: msal.ConfidentialClientApplication | None = None
_http_client: httpx.AsyncClient | None = None


def _get_token() -> str:
    """Acquire an OAuth2 token via client credentials. Sync — call via asyncio.to_thread."""
    global _msal_app
    if not O365_TENANT_ID or not O365_CLIENT_ID or not O365_CLIENT_SECRET:
        raise ToolError(
            "O365 credentials not configured. Set O365_TENANT_ID, "
            "O365_CLIENT_ID, and O365_CLIENT_SECRET in your environment."
        )
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
        raise ToolError(
            f"Failed to acquire O365 token: "
            f"{result.get('error_description', result.get('error', 'unknown error'))}"
        )
    return result["access_token"]


def _get_http_client() -> httpx.AsyncClient:
    """Get or create the singleton httpx client for Graph API."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url="https://graph.microsoft.com/v1.0",
            timeout=30.0,
        )
    return _http_client


def _get_user_id(override: str | None = None) -> str:
    """Resolve user/mailbox ID: override > config > error."""
    user_id = override or O365_USER_ID
    if not user_id:
        raise ToolError(
            "No user_id provided. Either pass user_id or set "
            "O365_USER_ID in your environment."
        )
    return user_id


def _ensure_list(value: str | list[str]) -> list[str]:
    """Normalize a string-or-list input to a list."""
    if isinstance(value, str):
        return [value]
    return value


def _recipients(emails: str | list[str]) -> list[dict]:
    """Build Graph API recipient array from email string(s)."""
    return [{"emailAddress": {"address": e}} for e in _ensure_list(emails)]


def _success(status_code: int, **kwargs) -> str:
    """Build a success JSON response."""
    return json.dumps({"status": "success", "status_code": status_code, **kwargs})


async def _request(method: str, path: str, **kwargs) -> dict | list:
    """Make an authenticated Graph API request with error handling."""
    token = await asyncio.to_thread(_get_token)
    client = _get_http_client()
    try:
        response = await client.request(
            method, path,
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
    except httpx.HTTPError as e:
        raise ToolError(f"Graph API request failed: {e}") from e

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        raise ToolError(
            f"Graph API rate limit exceeded. Retry after {retry_after} seconds."
        )

    if response.status_code >= 400:
        try:
            error_body = response.json()
            error_info = error_body.get("error", {})
            error_msg = error_info.get("message", response.text)
            error_code = error_info.get("code", "")
        except Exception:
            error_msg = response.text
            error_code = ""
        raise ToolError(
            f"Graph API error ({response.status_code}{f' {error_code}' if error_code else ''}): "
            f"{error_msg}"
        )

    if response.status_code == 202 or response.status_code == 204:
        return {}

    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def register_tools(mcp: FastMCP) -> None:
    """Register all O365 email tools with the MCP server."""

    if not O365_CLIENT_ID:
        logger.warning(
            "O365 credentials not set — O365 tools will be registered "
            "but will fail at invocation until configured."
        )

    # --- Sending Tools ---
    # (Step 3)

    # --- Mailbox Reading Tools ---
    # (Step 4)

    # --- Draft Management Tools ---
    # (Step 5)

    # --- Folder Management Tools ---
    # (Step 6)
```

Key design decisions:
- **`_get_token()`** is sync (msal is sync) — called via `asyncio.to_thread()` in `_request()`
- **`_get_http_client()`** returns singleton for connection pooling, auth header passed per-request
- **`_recipients()`** helper builds the Graph API recipient format `[{"emailAddress": {"address": "..."}}]`
- **202 Accepted** handled same as 204 (sendMail returns 202 with empty body)
- **Graph error format** parsed: `{"error": {"code": "...", "message": "..."}}`

---

## Step 3: Sending Tools (5 tools)

```python
    @mcp.tool()
    async def o365_send_email(
        to: str | list[str],
        subject: str,
        body: str,
        content_type: str = "HTML",
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        importance: str | None = None,
        reply_to: str | list[str] | None = None,
        save_to_sent: bool = True,
        user_id: str | None = None,
    ) -> str:
        """Send an email from an Office 365 mailbox.

        Args:
            to: Recipient email address(es)
            subject: Email subject
            body: Email body
            content_type: 'HTML' or 'Text' (default HTML)
            cc: CC recipient(s)
            bcc: BCC recipient(s)
            importance: 'low', 'normal', or 'high'
            reply_to: Reply-to address(es)
            save_to_sent: Save to Sent Items (default true)
            user_id: Sender mailbox (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        message: dict = {
            "subject": subject,
            "body": {"contentType": content_type, "content": body},
            "toRecipients": _recipients(to),
        }
        if cc:
            message["ccRecipients"] = _recipients(cc)
        if bcc:
            message["bccRecipients"] = _recipients(bcc)
        if importance:
            message["importance"] = importance
        if reply_to:
            message["replyTo"] = _recipients(reply_to)

        logger.info("Sending O365 email to=%s subject=%s", to, subject)
        await _request(
            "POST", f"/users/{uid}/sendMail",
            json={"message": message, "saveToSentItems": save_to_sent},
        )
        return _success(202, message="Email sent successfully")

    @mcp.tool()
    async def o365_send_email_with_attachment(
        to: str | list[str],
        subject: str,
        body: str,
        attachments: list[dict],
        content_type: str = "HTML",
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        user_id: str | None = None,
    ) -> str:
        """Send an O365 email with file attachments (max 3MB per file).

        Args:
            to: Recipient email address(es)
            subject: Email subject
            body: Email body
            attachments: List of {file_path, file_name?, content_type?}
            content_type: 'HTML' or 'Text' (default HTML)
            cc: CC recipient(s)
            bcc: BCC recipient(s)
            user_id: Sender mailbox (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        message: dict = {
            "subject": subject,
            "body": {"contentType": content_type, "content": body},
            "toRecipients": _recipients(to),
            "attachments": [],
        }
        if cc:
            message["ccRecipients"] = _recipients(cc)
        if bcc:
            message["bccRecipients"] = _recipients(bcc)

        for att in attachments:
            file_path = att.get("file_path")
            if not file_path:
                raise ToolError("Each attachment must have a 'file_path' key.")
            try:
                with open(file_path, "rb") as f:
                    content_bytes = base64.b64encode(f.read()).decode()
            except FileNotFoundError:
                raise ToolError(f"Attachment file not found: {file_path}") from None
            except OSError as e:
                raise ToolError(f"Error reading attachment {file_path}: {e}") from e

            message["attachments"].append({
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att.get("file_name", Path(file_path).name),
                "contentType": att.get("content_type", "application/octet-stream"),
                "contentBytes": content_bytes,
            })

        logger.info("Sending O365 email with %d attachment(s) to=%s", len(attachments), to)
        await _request(
            "POST", f"/users/{uid}/sendMail",
            json={"message": message, "saveToSentItems": True},
        )
        return _success(202, message="Email with attachments sent successfully")

    @mcp.tool()
    async def o365_reply(
        message_id: str,
        comment: str,
        user_id: str | None = None,
    ) -> str:
        """Reply to an O365 email.

        Args:
            message_id: Message ID to reply to
            comment: Reply text (HTML)
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        await _request(
            "POST", f"/users/{uid}/messages/{message_id}/reply",
            json={"comment": comment},
        )
        return _success(202, message="Reply sent")

    @mcp.tool()
    async def o365_reply_all(
        message_id: str,
        comment: str,
        user_id: str | None = None,
    ) -> str:
        """Reply to all recipients of an O365 email.

        Args:
            message_id: Message ID to reply to
            comment: Reply text (HTML)
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        await _request(
            "POST", f"/users/{uid}/messages/{message_id}/replyAll",
            json={"comment": comment},
        )
        return _success(202, message="Reply all sent")

    @mcp.tool()
    async def o365_forward(
        message_id: str,
        to: str | list[str],
        comment: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Forward an O365 email to new recipients.

        Args:
            message_id: Message ID to forward
            to: Forward recipient(s)
            comment: Optional comment to include
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        body: dict = {"toRecipients": _recipients(to)}
        if comment:
            body["comment"] = comment
        await _request(
            "POST", f"/users/{uid}/messages/{message_id}/forward",
            json=body,
        )
        return _success(202, message="Email forwarded")
```

---

## Step 4: Mailbox Reading Tools (5 tools)

```python
    @mcp.tool()
    async def o365_list_messages(
        folder: str = "Inbox",
        top: int = 10,
        filter: str | None = None,
        select: str | None = None,
        order_by: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """List messages in an O365 mailbox folder.

        Args:
            folder: Folder name or ID (default Inbox)
            top: Max results (default 10, max 1000)
            filter: OData filter (e.g., 'isRead eq false')
            select: Fields to return (comma-separated)
            order_by: Sort field (e.g., 'receivedDateTime desc')
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        params: dict = {"$top": str(top)}
        if filter:
            params["$filter"] = filter
        if select:
            params["$select"] = select
        if order_by:
            params["$orderby"] = order_by

        data = await _request(
            "GET", f"/users/{uid}/mailFolders/{folder}/messages", params=params
        )
        messages = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=messages, count=len(messages))

    @mcp.tool()
    async def o365_get_message(
        message_id: str,
        user_id: str | None = None,
    ) -> str:
        """Get full details of an O365 email message.

        Args:
            message_id: Message ID
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        data = await _request("GET", f"/users/{uid}/messages/{message_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def o365_search_messages(
        query: str,
        top: int = 10,
        user_id: str | None = None,
    ) -> str:
        """Search O365 messages using KQL (Keyword Query Language).

        Args:
            query: KQL search query. Examples:
                  - "quarterly report" (search all fields)
                  - from:john@example.com
                  - subject:invoice
                  - hasAttachments:true
                  - received>=2025-01-01
            top: Max results (default 10)
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        params = {"$search": f'"{query}"', "$top": str(top)}
        data = await _request("GET", f"/users/{uid}/messages", params=params)
        messages = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=messages, count=len(messages))

    @mcp.tool()
    async def o365_list_attachments(
        message_id: str,
        user_id: str | None = None,
    ) -> str:
        """List attachments on an O365 email message.

        Args:
            message_id: Message ID
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        data = await _request("GET", f"/users/{uid}/messages/{message_id}/attachments")
        attachments = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=attachments, count=len(attachments))

    @mcp.tool()
    async def o365_move_message(
        message_id: str,
        destination_folder: str,
        user_id: str | None = None,
    ) -> str:
        """Move an O365 email to a different folder.

        Args:
            message_id: Message ID
            destination_folder: Folder ID or well-known name (Inbox, Archive, DeletedItems, etc.)
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        data = await _request(
            "POST", f"/users/{uid}/messages/{message_id}/move",
            json={"destinationId": destination_folder},
        )
        return _success(200, data=data)
```

---

## Step 5: Draft Management Tools (5 tools)

```python
    @mcp.tool()
    async def o365_create_draft(
        subject: str,
        body: str,
        to: str | list[str] | None = None,
        content_type: str = "HTML",
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        user_id: str | None = None,
    ) -> str:
        """Create a draft email in O365.

        Args:
            subject: Email subject
            body: Email body
            to: Recipient(s) (can add later)
            content_type: 'HTML' or 'Text' (default HTML)
            cc: CC recipient(s)
            bcc: BCC recipient(s)
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        message: dict = {
            "subject": subject,
            "body": {"contentType": content_type, "content": body},
        }
        if to:
            message["toRecipients"] = _recipients(to)
        if cc:
            message["ccRecipients"] = _recipients(cc)
        if bcc:
            message["bccRecipients"] = _recipients(bcc)

        data = await _request("POST", f"/users/{uid}/messages", json=message)
        return _success(201, data=data)

    @mcp.tool()
    async def o365_update_draft(
        message_id: str,
        subject: str | None = None,
        body: str | None = None,
        to: str | list[str] | None = None,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        user_id: str | None = None,
    ) -> str:
        """Update an O365 draft email before sending.

        Args:
            message_id: Draft message ID
            subject: New subject
            body: New body (HTML)
            to: New recipients
            cc: New CC
            bcc: New BCC
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        patch: dict = {}
        if subject is not None:
            patch["subject"] = subject
        if body is not None:
            patch["body"] = {"contentType": "HTML", "content": body}
        if to is not None:
            patch["toRecipients"] = _recipients(to)
        if cc is not None:
            patch["ccRecipients"] = _recipients(cc)
        if bcc is not None:
            patch["bccRecipients"] = _recipients(bcc)
        if not patch:
            raise ToolError("At least one field to update must be provided.")

        data = await _request("PATCH", f"/users/{uid}/messages/{message_id}", json=patch)
        return _success(200, data=data)

    @mcp.tool()
    async def o365_add_draft_attachment(
        message_id: str,
        file_path: str,
        file_name: str | None = None,
        content_type: str = "application/octet-stream",
        user_id: str | None = None,
    ) -> str:
        """Add an attachment to an O365 draft message (max 3MB).

        Args:
            message_id: Draft message ID
            file_path: Local file path
            file_name: Override filename
            content_type: MIME type (default application/octet-stream)
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        try:
            with open(file_path, "rb") as f:
                content_bytes = base64.b64encode(f.read()).decode()
        except FileNotFoundError:
            raise ToolError(f"Attachment file not found: {file_path}") from None
        except OSError as e:
            raise ToolError(f"Error reading attachment {file_path}: {e}") from e

        attachment = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": file_name or Path(file_path).name,
            "contentType": content_type,
            "contentBytes": content_bytes,
        }
        data = await _request(
            "POST", f"/users/{uid}/messages/{message_id}/attachments",
            json=attachment,
        )
        return _success(201, data=data)

    @mcp.tool()
    async def o365_send_draft(
        message_id: str,
        user_id: str | None = None,
    ) -> str:
        """Send an existing O365 draft.

        Args:
            message_id: Draft message ID
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        await _request("POST", f"/users/{uid}/messages/{message_id}/send")
        return _success(202, message="Draft sent")

    @mcp.tool()
    async def o365_delete_draft(
        message_id: str,
        user_id: str | None = None,
    ) -> str:
        """Delete an unsent O365 draft.

        Args:
            message_id: Draft message ID
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        await _request("DELETE", f"/users/{uid}/messages/{message_id}")
        return _success(204, deleted_message_id=message_id)
```

---

## Step 6: Folder Management Tools (4 tools)

```python
    @mcp.tool()
    async def o365_get_folder(
        folder_id: str,
        user_id: str | None = None,
    ) -> str:
        """Get details of an O365 mail folder.

        Args:
            folder_id: Folder ID or well-known name (Inbox, Drafts, SentItems, etc.)
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        data = await _request("GET", f"/users/{uid}/mailFolders/{folder_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def o365_list_folders(user_id: str | None = None) -> str:
        """List O365 mail folders.

        Args:
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        data = await _request("GET", f"/users/{uid}/mailFolders")
        folders = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=folders, count=len(folders))

    @mcp.tool()
    async def o365_create_folder(
        name: str,
        parent_folder_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Create an O365 mail folder.

        Args:
            name: Folder name
            parent_folder_id: Parent folder ID (creates subfolder if provided)
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        if parent_folder_id:
            path = f"/users/{uid}/mailFolders/{parent_folder_id}/childFolders"
        else:
            path = f"/users/{uid}/mailFolders"
        data = await _request("POST", path, json={"displayName": name})
        return _success(201, data=data)

    @mcp.tool()
    async def o365_delete_folder(
        folder_id: str,
        user_id: str | None = None,
    ) -> str:
        """Delete an O365 mail folder.

        Args:
            folder_id: Folder ID
            user_id: Mailbox user (uses default if not provided)
        """
        uid = _get_user_id(user_id)
        await _request("DELETE", f"/users/{uid}/mailFolders/{folder_id}")
        return _success(204, deleted_folder_id=folder_id)
```

---

## Step 7: Registration & Config

### 7a. Update `src/mcp_toolbox/tools/__init__.py`
```python
from mcp_toolbox.tools import clickup_tool, example_tool, o365_tool, sendgrid_tool


def register_all_tools(mcp: FastMCP) -> None:
    """Register all tool modules with the MCP server."""
    example_tool.register_tools(mcp)
    sendgrid_tool.register_tools(mcp)
    clickup_tool.register_tools(mcp)
    o365_tool.register_tools(mcp)
```

### 7b. Add pyright exclusion in `pyproject.toml`
The `msal` package lacks type stubs (`py.typed` marker). Add `o365_tool.py` to the pyright exclude list:
```toml
[tool.pyright]
pythonVersion = "3.10"
typeCheckingMode = "basic"
exclude = ["src/mcp_toolbox/tools/sendgrid_tool.py", "src/mcp_toolbox/tools/o365_tool.py"]
```

---

## Step 8: Tests

Create `tests/test_o365_tool.py`. Mock both `msal` (token) and `httpx` (Graph API) calls.

### 8a. Fixtures & Helpers

```python
"""Tests for O365 email tool integration."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.o365_tool import register_tools

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _get_result_data(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_msal = MagicMock()
    mock_msal.acquire_token_for_client.return_value = {"access_token": "test-token-123"}
    with patch("mcp_toolbox.tools.o365_tool.O365_TENANT_ID", "tenant_123"), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_ID", "client_123"), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_SECRET", "secret_123"), \
         patch("mcp_toolbox.tools.o365_tool.O365_USER_ID", "user@example.com"), \
         patch("mcp_toolbox.tools.o365_tool._msal_app", mock_msal), \
         patch("mcp_toolbox.tools.o365_tool._http_client", None):
        register_tools(mcp)
        yield mcp
```

### 8b. Config & Auth Error Tests

```python
@pytest.mark.asyncio
async def test_missing_credentials():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.o365_tool.O365_TENANT_ID", None), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_ID", None), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_SECRET", None), \
         patch("mcp_toolbox.tools.o365_tool.O365_USER_ID", "user@example.com"), \
         patch("mcp_toolbox.tools.o365_tool._msal_app", None), \
         patch("mcp_toolbox.tools.o365_tool._http_client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="O365 credentials not configured"):
            await mcp.call_tool("o365_list_folders", {})


@pytest.mark.asyncio
async def test_token_acquisition_failure():
    mcp = FastMCP("test")
    mock_msal = MagicMock()
    mock_msal.acquire_token_for_client.return_value = {
        "error": "invalid_client", "error_description": "Bad credentials"
    }
    with patch("mcp_toolbox.tools.o365_tool.O365_TENANT_ID", "t"), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_ID", "c"), \
         patch("mcp_toolbox.tools.o365_tool.O365_CLIENT_SECRET", "s"), \
         patch("mcp_toolbox.tools.o365_tool.O365_USER_ID", "u@e.com"), \
         patch("mcp_toolbox.tools.o365_tool._msal_app", mock_msal), \
         patch("mcp_toolbox.tools.o365_tool._http_client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="Failed to acquire O365 token"):
            await mcp.call_tool("o365_list_folders", {})
```

### 8c. Sending Tool Tests

```python
@pytest.mark.asyncio
@respx.mock
async def test_send_email(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/sendMail").mock(
        return_value=httpx.Response(202)
    )
    result = await server.call_tool("o365_send_email", {
        "to": "recipient@example.com", "subject": "Hello", "body": "<p>Hi</p>",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_send_email_with_attachment(server, tmp_path):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/sendMail").mock(
        return_value=httpx.Response(202)
    )
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello")
    result = await server.call_tool("o365_send_email_with_attachment", {
        "to": "r@example.com", "subject": "With file", "body": "See attached",
        "attachments": [{"file_path": str(test_file)}],
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_reply(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1/reply").mock(
        return_value=httpx.Response(202)
    )
    result = await server.call_tool("o365_reply", {
        "message_id": "msg_1", "comment": "Thanks!",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_reply_all(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1/replyAll").mock(
        return_value=httpx.Response(202)
    )
    result = await server.call_tool("o365_reply_all", {
        "message_id": "msg_1", "comment": "Agreed!",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_forward(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1/forward").mock(
        return_value=httpx.Response(202)
    )
    result = await server.call_tool("o365_forward", {
        "message_id": "msg_1", "to": "other@example.com",
    })
    assert _get_result_data(result)["status"] == "success"
```

### 8d. Mailbox Reading Tests

```python
@pytest.mark.asyncio
@respx.mock
async def test_list_messages(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/mailFolders/Inbox/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "m1", "subject": "Test"}]})
    )
    result = await server.call_tool("o365_list_messages", {})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_message(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1").mock(
        return_value=httpx.Response(200, json={"id": "msg_1", "subject": "Test"})
    )
    result = await server.call_tool("o365_get_message", {"message_id": "msg_1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_search_messages(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "m1"}]})
    )
    result = await server.call_tool("o365_search_messages", {"query": "subject:invoice"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_attachments(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1/attachments").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "a1", "name": "file.pdf"}]})
    )
    result = await server.call_tool("o365_list_attachments", {"message_id": "msg_1"})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_move_message(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/msg_1/move").mock(
        return_value=httpx.Response(200, json={"id": "msg_1"})
    )
    result = await server.call_tool("o365_move_message", {
        "message_id": "msg_1", "destination_folder": "Archive",
    })
    assert _get_result_data(result)["status"] == "success"
```

### 8e. Draft Management Tests

```python
@pytest.mark.asyncio
@respx.mock
async def test_create_draft(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages").mock(
        return_value=httpx.Response(201, json={"id": "draft_1"})
    )
    result = await server.call_tool("o365_create_draft", {
        "subject": "Draft", "body": "<p>WIP</p>",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_draft(server):
    respx.patch(f"{GRAPH_BASE}/users/user@example.com/messages/draft_1").mock(
        return_value=httpx.Response(200, json={"id": "draft_1"})
    )
    result = await server.call_tool("o365_update_draft", {
        "message_id": "draft_1", "subject": "Updated Draft",
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
async def test_update_draft_no_fields(server):
    with pytest.raises(Exception, match="At least one field"):
        await server.call_tool("o365_update_draft", {"message_id": "draft_1"})


@pytest.mark.asyncio
@respx.mock
async def test_add_draft_attachment(server, tmp_path):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/draft_1/attachments").mock(
        return_value=httpx.Response(201, json={"id": "att_1"})
    )
    test_file = tmp_path / "doc.pdf"
    test_file.write_bytes(b"PDF content")
    result = await server.call_tool("o365_add_draft_attachment", {
        "message_id": "draft_1", "file_path": str(test_file),
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_send_draft(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/messages/draft_1/send").mock(
        return_value=httpx.Response(202)
    )
    result = await server.call_tool("o365_send_draft", {"message_id": "draft_1"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_draft(server):
    respx.delete(f"{GRAPH_BASE}/users/user@example.com/messages/draft_1").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("o365_delete_draft", {"message_id": "draft_1"})
    assert _get_result_data(result)["status"] == "success"
```

### 8f. Folder Management Tests

```python
@pytest.mark.asyncio
@respx.mock
async def test_get_folder(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/mailFolders/Inbox").mock(
        return_value=httpx.Response(200, json={"id": "inbox_id", "displayName": "Inbox"})
    )
    result = await server.call_tool("o365_get_folder", {"folder_id": "Inbox"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_folders(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/mailFolders").mock(
        return_value=httpx.Response(200, json={"value": [
            {"id": "f1", "displayName": "Inbox"},
            {"id": "f2", "displayName": "Drafts"},
        ]})
    )
    result = await server.call_tool("o365_list_folders", {})
    data = _get_result_data(result)
    assert data["count"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_create_folder(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/mailFolders").mock(
        return_value=httpx.Response(201, json={"id": "f_new", "displayName": "Custom"})
    )
    result = await server.call_tool("o365_create_folder", {"name": "Custom"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_folder(server):
    respx.delete(f"{GRAPH_BASE}/users/user@example.com/mailFolders/f1").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("o365_delete_folder", {"folder_id": "f1"})
    assert _get_result_data(result)["status"] == "success"
```

### 8g. API Error Tests

```python
@pytest.mark.asyncio
@respx.mock
async def test_api_error_401(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/mailFolders").mock(
        return_value=httpx.Response(401, json={
            "error": {"code": "InvalidAuthenticationToken", "message": "Token expired"}
        })
    )
    with pytest.raises(Exception, match="Graph API error.*401.*Token expired"):
        await server.call_tool("o365_list_folders", {})


@pytest.mark.asyncio
@respx.mock
async def test_api_error_429(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/mailFolders").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )
    with pytest.raises(Exception, match="rate limit.*30 seconds"):
        await server.call_tool("o365_list_folders", {})
```

---

## Step 9: Update test_server.py

Add all 19 O365 tool names to the expected set and update count to 116:

```python
        # O365 tools (19)
        "o365_send_email", "o365_send_email_with_attachment",
        "o365_reply", "o365_reply_all", "o365_forward",
        "o365_list_messages", "o365_get_message", "o365_search_messages",
        "o365_list_attachments", "o365_move_message",
        "o365_create_draft", "o365_update_draft", "o365_add_draft_attachment",
        "o365_send_draft", "o365_delete_draft",
        "o365_get_folder", "o365_list_folders", "o365_create_folder",
        "o365_delete_folder",
```

Total assertion: `assert len(tools) == 116`

---

## Step 10: Documentation & Validation

### 10a. Update CLAUDE.md
Add O365 integration to Source Layout and Integrations sections.

### 10b. Run validation
```bash
uv sync --dev --all-extras
uv run pytest -v
uv run ruff check src/ tests/
uv run pyright src/
```

---

## Execution Order

| Order | Step | Description | Depends On |
|-------|------|-------------|------------|
| 1 | Dependencies & config | pyproject.toml, config.py, .env.example | — |
| 2 | Tool module foundation | o365_tool.py scaffolding + helpers | Step 1 |
| 3 | Sending tools | 5 tools | Step 2 |
| 4 | Reading tools | 5 tools | Step 2 |
| 5 | Draft tools | 5 tools | Step 2 |
| 6 | Folder tools | 4 tools | Step 2 |
| 7 | Registration | __init__.py | Steps 3-6 |
| 8 | Tests | 25+ tests | Steps 3-7 |
| 9 | test_server.py | 116 tool names | Steps 3-7 |
| 10 | Docs & validation | CLAUDE.md, full suite | Steps 1-9 |

Steps 3-6 are independent.

---

## Risk Notes

- **msal sync in async context:** `acquire_token_for_client()` is synchronous. Wrapped in `asyncio.to_thread()` to prevent event loop blocking during token renewal (~every 60 min).
- **Graph API 202 responses:** `sendMail`, `reply`, `replyAll`, `forward`, and `send` (draft) all return 202 with empty body. The `_request()` helper returns `{}` for 202.
- **PATCH method:** `o365_update_draft` uses PATCH, which httpx supports. respx also supports `respx.patch()`.
- **Attachment limit:** 3MB practical limit per file via JSON payload. Larger files need upload session (not implemented — out of scope).
- **`filter` parameter name:** `o365_list_messages` uses `filter` as a parameter which shadows Python builtin. Same situation as `type` in ClickUp views — ruff's `A` ruleset is not enabled, so no linting error.
