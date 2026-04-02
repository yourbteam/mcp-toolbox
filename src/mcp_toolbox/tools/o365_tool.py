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
            f"Graph API error ({response.status_code}"
            f"{f' {error_code}' if error_code else ''}): {error_msg}"
        )

    if response.status_code in (202, 204):
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
        forward_body: dict = {"toRecipients": _recipients(to)}
        if comment:
            forward_body["comment"] = comment
        await _request(
            "POST", f"/users/{uid}/messages/{message_id}/forward",
            json=forward_body,
        )
        return _success(202, message="Email forwarded")

    # --- Mailbox Reading Tools ---

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

    # --- Draft Management Tools ---

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

    # --- Folder Management Tools ---

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
