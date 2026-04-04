"""Gmail API v1 integration — messages, threads, labels, drafts, settings."""

import asyncio
import base64
import json
import logging
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import GMAIL_DELEGATED_USER, GOOGLE_SERVICE_ACCOUNT_JSON

logger = logging.getLogger(__name__)

_credentials = None
_client: httpx.AsyncClient | None = None

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _get_token() -> str:
    global _credentials
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ToolError(
            "GOOGLE_SERVICE_ACCOUNT_JSON not configured."
        )
    if not GMAIL_DELEGATED_USER:
        raise ToolError(
            "GMAIL_DELEGATED_USER not configured. "
            "Gmail API requires domain-wide delegation."
        )
    if _credentials is None:
        import google.auth.transport.requests
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=["https://mail.google.com/"],
        )
        _credentials = creds.with_subject(GMAIL_DELEGATED_USER)
    if not _credentials.valid:
        import google.auth.transport.requests

        _credentials.refresh(
            google.auth.transport.requests.Request()
        )
    return _credentials.token


async def _get_client() -> httpx.AsyncClient:
    global _client
    token = await asyncio.to_thread(_get_token)
    if _client is None:
        _client = httpx.AsyncClient(base_url=BASE, timeout=30.0)
    _client.headers["Authorization"] = f"Bearer {token}"
    return _client


def _success(sc: int, **kw: object) -> str:
    return json.dumps(
        {"status": "success", "status_code": sc, **kw}
    )


async def _req(
    method: str,
    url: str,
    json_body: dict | None = None,
    params: dict | None = None,
) -> dict | list:
    client = await _get_client()
    kwargs: dict = {}
    if json_body is not None:
        kwargs["json"] = json_body
    if params:
        kwargs["params"] = params
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"Gmail request failed: {e}") from e
    if response.status_code == 429:
        raise ToolError("Gmail rate limit exceeded.")
    if response.status_code == 403:
        try:
            err = response.json().get("error", {})
            reason = ""
            for e_item in err.get("errors", []):
                if e_item.get("reason") == "rateLimitExceeded":
                    raise ToolError("Gmail rate limit exceeded.")
                reason = e_item.get("reason", "")
            msg = err.get("message", response.text)
        except ToolError:
            raise
        except Exception:
            msg = response.text
            reason = ""
        raise ToolError(
            f"Gmail error (403"
            f"{f' {reason}' if reason else ''}): {msg}"
        )
    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
            msg = err.get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(
            f"Gmail error ({response.status_code}): {msg}"
        )
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def _build_message(
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    cc: str | None = None,
    bcc: str | None = None,
    html_body: str | None = None,
    reply_to: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    """Build RFC 2822 MIME message, return base64url-encoded raw."""
    if html_body is not None and body is not None:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
    elif html_body is not None:
        msg = MIMEText(html_body, "html")
    else:
        msg = MIMEText(body or "", "plain")
    if to is not None:
        msg["To"] = to
    if subject is not None:
        msg["Subject"] = subject
    if cc is not None:
        msg["Cc"] = cc
    if bcc is not None:
        msg["Bcc"] = bcc
    if reply_to is not None:
        msg["Reply-To"] = reply_to
    if in_reply_to is not None:
        msg["In-Reply-To"] = in_reply_to
    if references is not None:
        msg["References"] = references
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def _build_message_with_attachment(
    to: str,
    subject: str,
    body: str,
    attachment_data: str,
    attachment_filename: str,
    attachment_content_type: str,
    cc: str | None = None,
    bcc: str | None = None,
    html_body: str | None = None,
) -> str:
    """Build MIME message with attachment, return base64url raw."""
    msg = MIMEMultipart("mixed")
    msg["To"] = to
    msg["Subject"] = subject
    if cc is not None:
        msg["Cc"] = cc
    if bcc is not None:
        msg["Bcc"] = bcc
    if html_body is not None:
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(body, "plain"))
        alt.attach(MIMEText(html_body, "html"))
        msg.attach(alt)
    else:
        msg.attach(MIMEText(body, "plain"))
    maintype, subtype = attachment_content_type.split("/", 1)
    part = MIMEBase(maintype, subtype)
    part.set_payload(base64.b64decode(attachment_data))
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        "attachment",
        filename=attachment_filename,
    )
    msg.attach(part)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def _decode_body(payload: dict) -> dict:
    """Extract text from MIME payload. Returns {plain, html}."""
    result: dict = {"plain": None, "html": None}
    mime = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")
    if body_data and "text/plain" in mime:
        result["plain"] = base64.urlsafe_b64decode(
            body_data + "=="
        ).decode("utf-8", errors="replace")
    elif body_data and "text/html" in mime:
        result["html"] = base64.urlsafe_b64decode(
            body_data + "=="
        ).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        child = _decode_body(part)
        if child.get("plain") and result["plain"] is None:
            result["plain"] = child["plain"]
        if child.get("html") and result["html"] is None:
            result["html"] = child["html"]
    return result


def register_tools(mcp: FastMCP) -> None:  # noqa: C901
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        logger.warning(
            "GOOGLE_SERVICE_ACCOUNT_JSON not set "
            "— Gmail tools will fail."
        )

    # ================================================================
    # TIER 1: MESSAGES (12 tools)
    # ================================================================

    @mcp.tool()
    async def gmail_send_message(
        to: str,
        subject: str,
        body: str,
        html_body: str | None = None,
        cc: str | None = None,
        bcc: str | None = None,
        reply_to: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Send an email message.
        Args:
            to: Recipient email(s), comma-separated
            subject: Email subject line
            body: Email body (plain text)
            html_body: HTML body (creates multipart/alternative)
            cc: CC recipients, comma-separated
            bcc: BCC recipients, comma-separated
            reply_to: Reply-To address
            in_reply_to: Message-ID being replied to
            references: References header for threading
            thread_id: Thread ID to add this message to
        """
        raw = _build_message(
            to=to, subject=subject, body=body,
            html_body=html_body, cc=cc, bcc=bcc,
            reply_to=reply_to, in_reply_to=in_reply_to,
            references=references,
        )
        payload: dict = {"raw": raw}
        if thread_id is not None:
            payload["threadId"] = thread_id
        data = await _req(
            "POST", "/messages/send", json_body=payload,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_send_message_with_attachment(
        to: str,
        subject: str,
        body: str,
        attachment_data: str,
        attachment_filename: str,
        attachment_content_type: str,
        html_body: str | None = None,
        cc: str | None = None,
        bcc: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Send an email with a file attachment.
        Args:
            to: Recipient email(s), comma-separated
            subject: Email subject line
            body: Email body (plain text)
            attachment_data: Base64-encoded file content
            attachment_filename: Filename for the attachment
            attachment_content_type: MIME type (e.g. application/pdf)
            html_body: HTML body
            cc: CC recipients, comma-separated
            bcc: BCC recipients, comma-separated
            thread_id: Thread ID to add this message to
        """
        raw = _build_message_with_attachment(
            to=to, subject=subject, body=body,
            attachment_data=attachment_data,
            attachment_filename=attachment_filename,
            attachment_content_type=attachment_content_type,
            cc=cc, bcc=bcc, html_body=html_body,
        )
        payload: dict = {"raw": raw}
        if thread_id is not None:
            payload["threadId"] = thread_id
        data = await _req(
            "POST", "/messages/send", json_body=payload,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_list_messages(
        query: str | None = None,
        label_ids: list[str] | None = None,
        max_results: int = 20,
        page_token: str | None = None,
        include_spam_trash: bool = False,
    ) -> str:
        """List messages with optional filtering.
        Args:
            query: Gmail search query (e.g. from:user@example.com)
            label_ids: Filter by label IDs (e.g. ["INBOX"])
            max_results: Max messages (default 20, max 500)
            page_token: Pagination token
            include_spam_trash: Include SPAM and TRASH
        """
        p: dict = {"maxResults": str(max_results)}
        if query is not None:
            p["q"] = query
        if label_ids is not None:
            p["labelIds"] = label_ids
        if page_token is not None:
            p["pageToken"] = page_token
        if include_spam_trash:
            p["includeSpamTrash"] = "true"
        data = await _req("GET", "/messages", params=p)
        items = (
            data.get("messages", [])
            if isinstance(data, dict) else data
        )
        npt = (
            data.get("nextPageToken")
            if isinstance(data, dict) else None
        )
        return _success(
            200, data=items, count=len(items),
            next_page_token=npt,
        )

    @mcp.tool()
    async def gmail_get_message(
        message_id: str,
        format: str = "full",
        metadata_headers: list[str] | None = None,
    ) -> str:
        """Get a single message by ID.
        Args:
            message_id: Message ID
            format: full, metadata, minimal, or raw
            metadata_headers: Headers when format=metadata
        """
        p: dict = {"format": format}
        if metadata_headers is not None:
            p["metadataHeaders"] = metadata_headers
        data = await _req(
            "GET", f"/messages/{message_id}", params=p,
        )
        if (
            isinstance(data, dict)
            and format == "full"
            and "payload" in data
        ):
            data["_decoded_body"] = _decode_body(
                data["payload"]
            )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_modify_message(
        message_id: str,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> str:
        """Add or remove labels from a message.
        Args:
            message_id: Message ID
            add_label_ids: Label IDs to add
            remove_label_ids: Label IDs to remove
        """
        body: dict = {}
        if add_label_ids is not None:
            body["addLabelIds"] = add_label_ids
        if remove_label_ids is not None:
            body["removeLabelIds"] = remove_label_ids
        data = await _req(
            "POST", f"/messages/{message_id}/modify",
            json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_delete_message(message_id: str) -> str:
        """Permanently delete a message. IRREVERSIBLE.
        Args:
            message_id: Message ID to permanently delete
        """
        await _req("DELETE", f"/messages/{message_id}")
        return _success(204, message="Message deleted.")

    @mcp.tool()
    async def gmail_trash_message(message_id: str) -> str:
        """Move a message to Trash. Recoverable for 30 days.
        Args:
            message_id: Message ID to trash
        """
        data = await _req(
            "POST", f"/messages/{message_id}/trash",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_untrash_message(message_id: str) -> str:
        """Remove a message from Trash.
        Args:
            message_id: Message ID to untrash
        """
        data = await _req(
            "POST", f"/messages/{message_id}/untrash",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_batch_modify_messages(
        message_ids: list[str],
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> str:
        """Add/remove labels from multiple messages (max 1000).
        Args:
            message_ids: Message IDs to modify
            add_label_ids: Label IDs to add
            remove_label_ids: Label IDs to remove
        """
        body: dict = {"ids": message_ids}
        if add_label_ids is not None:
            body["addLabelIds"] = add_label_ids
        if remove_label_ids is not None:
            body["removeLabelIds"] = remove_label_ids
        await _req(
            "POST", "/messages/batchModify", json_body=body,
        )
        return _success(
            204, message="Batch modify complete.",
        )

    @mcp.tool()
    async def gmail_batch_delete_messages(
        message_ids: list[str],
    ) -> str:
        """Permanently delete multiple messages. IRREVERSIBLE.
        Args:
            message_ids: Message IDs to delete (max 1000)
        """
        await _req(
            "POST", "/messages/batchDelete",
            json_body={"ids": message_ids},
        )
        return _success(
            204, message="Batch delete complete.",
        )

    @mcp.tool()
    async def gmail_import_message(
        raw: str,
        label_ids: list[str] | None = None,
        internal_date_source: str | None = None,
        never_mark_spam: bool = False,
        process_for_calendar: bool = False,
        deleted: bool = False,
    ) -> str:
        """Import a message (like receiving via SMTP). No send.
        Args:
            raw: Base64url-encoded RFC 2822 message
            label_ids: Labels to apply
            internal_date_source: receivedTime or dateHeader
            never_mark_spam: Never mark as spam
            process_for_calendar: Process calendar invites
            deleted: Mark as deleted (Trash)
        """
        p: dict = {}
        if internal_date_source is not None:
            p["internalDateSource"] = internal_date_source
        if never_mark_spam:
            p["neverMarkSpam"] = "true"
        if process_for_calendar:
            p["processForCalendar"] = "true"
        if deleted:
            p["deleted"] = "true"
        body: dict = {"raw": raw}
        if label_ids is not None:
            body["labelIds"] = label_ids
        data = await _req(
            "POST", "/messages/import",
            json_body=body, params=p or None,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_insert_message(
        raw: str,
        label_ids: list[str] | None = None,
        internal_date_source: str | None = None,
        deleted: bool = False,
    ) -> str:
        """Insert a message directly (bypasses spam/sending).
        Args:
            raw: Base64url-encoded RFC 2822 message
            label_ids: Labels to apply
            internal_date_source: receivedTime or dateHeader
            deleted: Mark as deleted (Trash)
        """
        p: dict = {}
        if internal_date_source is not None:
            p["internalDateSource"] = internal_date_source
        if deleted:
            p["deleted"] = "true"
        body: dict = {"raw": raw}
        if label_ids is not None:
            body["labelIds"] = label_ids
        data = await _req(
            "POST", "/messages",
            json_body=body, params=p or None,
        )
        return _success(200, data=data)

    # ================================================================
    # TIER 2: THREADS (6 tools)
    # ================================================================

    @mcp.tool()
    async def gmail_list_threads(
        query: str | None = None,
        label_ids: list[str] | None = None,
        max_results: int = 20,
        page_token: str | None = None,
        include_spam_trash: bool = False,
    ) -> str:
        """List conversation threads.
        Args:
            query: Gmail search query
            label_ids: Filter by label IDs
            max_results: Max threads (default 20, max 500)
            page_token: Pagination token
            include_spam_trash: Include SPAM and TRASH
        """
        p: dict = {"maxResults": str(max_results)}
        if query is not None:
            p["q"] = query
        if label_ids is not None:
            p["labelIds"] = label_ids
        if page_token is not None:
            p["pageToken"] = page_token
        if include_spam_trash:
            p["includeSpamTrash"] = "true"
        data = await _req("GET", "/threads", params=p)
        items = (
            data.get("threads", [])
            if isinstance(data, dict) else data
        )
        npt = (
            data.get("nextPageToken")
            if isinstance(data, dict) else None
        )
        return _success(
            200, data=items, count=len(items),
            next_page_token=npt,
        )

    @mcp.tool()
    async def gmail_get_thread(
        thread_id: str,
        format: str = "full",
        metadata_headers: list[str] | None = None,
    ) -> str:
        """Get a thread and all its messages.
        Args:
            thread_id: Thread ID
            format: Message format: full, metadata, minimal
            metadata_headers: Headers when format=metadata
        """
        p: dict = {"format": format}
        if metadata_headers is not None:
            p["metadataHeaders"] = metadata_headers
        data = await _req(
            "GET", f"/threads/{thread_id}", params=p,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_modify_thread(
        thread_id: str,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> str:
        """Add/remove labels from all messages in a thread.
        Args:
            thread_id: Thread ID
            add_label_ids: Label IDs to add
            remove_label_ids: Label IDs to remove
        """
        body: dict = {}
        if add_label_ids is not None:
            body["addLabelIds"] = add_label_ids
        if remove_label_ids is not None:
            body["removeLabelIds"] = remove_label_ids
        data = await _req(
            "POST", f"/threads/{thread_id}/modify",
            json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_delete_thread(thread_id: str) -> str:
        """Permanently delete a thread. IRREVERSIBLE.
        Args:
            thread_id: Thread ID to permanently delete
        """
        await _req("DELETE", f"/threads/{thread_id}")
        return _success(204, message="Thread deleted.")

    @mcp.tool()
    async def gmail_trash_thread(thread_id: str) -> str:
        """Move a thread to Trash.
        Args:
            thread_id: Thread ID to trash
        """
        data = await _req(
            "POST", f"/threads/{thread_id}/trash",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_untrash_thread(thread_id: str) -> str:
        """Remove a thread from Trash.
        Args:
            thread_id: Thread ID to untrash
        """
        data = await _req(
            "POST", f"/threads/{thread_id}/untrash",
        )
        return _success(200, data=data)

    # ================================================================
    # TIER 3: LABELS (6 tools)
    # ================================================================

    @mcp.tool()
    async def gmail_list_labels() -> str:
        """List all labels in the mailbox."""
        data = await _req("GET", "/labels")
        items = (
            data.get("labels", [])
            if isinstance(data, dict) else data
        )
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def gmail_get_label(label_id: str) -> str:
        """Get a single label's details.
        Args:
            label_id: Label ID (e.g. INBOX, Label_123)
        """
        data = await _req("GET", f"/labels/{label_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_create_label(
        name: str,
        message_list_visibility: str | None = None,
        label_list_visibility: str | None = None,
        background_color: str | None = None,
        text_color: str | None = None,
    ) -> str:
        """Create a new user label.
        Args:
            name: Label name (use / for nesting, e.g. Projects/Active)
            message_list_visibility: show or hide
            label_list_visibility: labelShow, labelShowIfUnread, labelHide
            background_color: Hex color (e.g. #16a765)
            text_color: Hex color (e.g. #ffffff)
        """
        body: dict = {"name": name}
        if message_list_visibility is not None:
            body["messageListVisibility"] = (
                message_list_visibility
            )
        if label_list_visibility is not None:
            body["labelListVisibility"] = label_list_visibility
        if (
            background_color is not None
            or text_color is not None
        ):
            color: dict = {}
            if background_color is not None:
                color["backgroundColor"] = background_color
            if text_color is not None:
                color["textColor"] = text_color
            body["color"] = color
        data = await _req(
            "POST", "/labels", json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_update_label(
        label_id: str,
        name: str | None = None,
        message_list_visibility: str | None = None,
        label_list_visibility: str | None = None,
        background_color: str | None = None,
        text_color: str | None = None,
    ) -> str:
        """Full update of a label (replaces all mutable fields).
        Args:
            label_id: Label ID to update
            name: New name
            message_list_visibility: show or hide
            label_list_visibility: labelShow, labelShowIfUnread, labelHide
            background_color: Hex color
            text_color: Hex color
        """
        body: dict = {"id": label_id}
        if name is not None:
            body["name"] = name
        if message_list_visibility is not None:
            body["messageListVisibility"] = (
                message_list_visibility
            )
        if label_list_visibility is not None:
            body["labelListVisibility"] = label_list_visibility
        if (
            background_color is not None
            or text_color is not None
        ):
            color: dict = {}
            if background_color is not None:
                color["backgroundColor"] = background_color
            if text_color is not None:
                color["textColor"] = text_color
            body["color"] = color
        data = await _req(
            "PUT", f"/labels/{label_id}", json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_patch_label(
        label_id: str,
        name: str | None = None,
        message_list_visibility: str | None = None,
        label_list_visibility: str | None = None,
        background_color: str | None = None,
        text_color: str | None = None,
    ) -> str:
        """Partially update a label (only provided fields change).
        Args:
            label_id: Label ID to patch
            name: New name
            message_list_visibility: show or hide
            label_list_visibility: labelShow, labelShowIfUnread, labelHide
            background_color: Hex color
            text_color: Hex color
        """
        body: dict = {}
        if name is not None:
            body["name"] = name
        if message_list_visibility is not None:
            body["messageListVisibility"] = (
                message_list_visibility
            )
        if label_list_visibility is not None:
            body["labelListVisibility"] = label_list_visibility
        if (
            background_color is not None
            or text_color is not None
        ):
            color: dict = {}
            if background_color is not None:
                color["backgroundColor"] = background_color
            if text_color is not None:
                color["textColor"] = text_color
            body["color"] = color
        if not body:
            raise ToolError(
                "At least one field must be provided."
            )
        data = await _req(
            "PATCH", f"/labels/{label_id}", json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_delete_label(label_id: str) -> str:
        """Delete a user label. System labels cannot be deleted.
        Args:
            label_id: Label ID to delete
        """
        await _req("DELETE", f"/labels/{label_id}")
        return _success(204, message="Label deleted.")

    # ================================================================
    # TIER 4: DRAFTS (6 tools)
    # ================================================================

    @mcp.tool()
    async def gmail_list_drafts(
        query: str | None = None,
        max_results: int = 20,
        page_token: str | None = None,
        include_spam_trash: bool = False,
    ) -> str:
        """List drafts in the mailbox.
        Args:
            query: Gmail search query
            max_results: Max drafts (default 20, max 500)
            page_token: Pagination token
            include_spam_trash: Include SPAM and TRASH
        """
        p: dict = {"maxResults": str(max_results)}
        if query is not None:
            p["q"] = query
        if page_token is not None:
            p["pageToken"] = page_token
        if include_spam_trash:
            p["includeSpamTrash"] = "true"
        data = await _req("GET", "/drafts", params=p)
        items = (
            data.get("drafts", [])
            if isinstance(data, dict) else data
        )
        npt = (
            data.get("nextPageToken")
            if isinstance(data, dict) else None
        )
        return _success(
            200, data=items, count=len(items),
            next_page_token=npt,
        )

    @mcp.tool()
    async def gmail_get_draft(
        draft_id: str,
        format: str = "full",
    ) -> str:
        """Get a draft and its message content.
        Args:
            draft_id: Draft ID
            format: Message format: full, metadata, minimal, raw
        """
        p: dict = {"format": format}
        data = await _req(
            "GET", f"/drafts/{draft_id}", params=p,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_create_draft(
        to: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        html_body: str | None = None,
        cc: str | None = None,
        bcc: str | None = None,
        reply_to: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Create a new draft.
        Args:
            to: Recipient email(s), comma-separated
            subject: Email subject line
            body: Email body (plain text)
            html_body: HTML body
            cc: CC recipients, comma-separated
            bcc: BCC recipients, comma-separated
            reply_to: Reply-To address
            in_reply_to: Message-ID for threading
            references: References header for threading
            thread_id: Thread ID
        """
        raw = _build_message(
            to=to, subject=subject, body=body,
            html_body=html_body, cc=cc, bcc=bcc,
            reply_to=reply_to, in_reply_to=in_reply_to,
            references=references,
        )
        message: dict = {"raw": raw}
        if thread_id is not None:
            message["threadId"] = thread_id
        data = await _req(
            "POST", "/drafts",
            json_body={"message": message},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_update_draft(
        draft_id: str,
        to: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        html_body: str | None = None,
        cc: str | None = None,
        bcc: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Replace a draft's content with new content.
        Args:
            draft_id: Draft ID to update
            to: Recipient email(s)
            subject: Email subject
            body: Email body (plain text)
            html_body: HTML body
            cc: CC recipients
            bcc: BCC recipients
            thread_id: Thread ID
        """
        raw = _build_message(
            to=to, subject=subject, body=body,
            html_body=html_body, cc=cc, bcc=bcc,
        )
        message: dict = {"raw": raw}
        if thread_id is not None:
            message["threadId"] = thread_id
        data = await _req(
            "PUT", f"/drafts/{draft_id}",
            json_body={"message": message},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_delete_draft(draft_id: str) -> str:
        """Delete a draft. Does not send.
        Args:
            draft_id: Draft ID to delete
        """
        await _req("DELETE", f"/drafts/{draft_id}")
        return _success(204, message="Draft deleted.")

    @mcp.tool()
    async def gmail_send_draft(draft_id: str) -> str:
        """Send an existing draft.
        Args:
            draft_id: Draft ID to send
        """
        data = await _req(
            "POST", "/drafts/send",
            json_body={"id": draft_id},
        )
        return _success(200, data=data)

    # ================================================================
    # TIER 5: HISTORY (1 tool)
    # ================================================================

    @mcp.tool()
    async def gmail_list_history(
        start_history_id: str,
        label_id: str | None = None,
        history_types: list[str] | None = None,
        max_results: int = 100,
        page_token: str | None = None,
    ) -> str:
        """List mailbox changes since a given history ID.
        Args:
            start_history_id: History ID to start from
            label_id: Filter to changes involving this label
            history_types: messageAdded, messageDeleted, labelAdded, labelRemoved
            max_results: Max records (default 100, max 500)
            page_token: Pagination token
        """
        p: dict = {
            "startHistoryId": start_history_id,
            "maxResults": str(max_results),
        }
        if label_id is not None:
            p["labelId"] = label_id
        if history_types is not None:
            p["historyTypes"] = history_types
        if page_token is not None:
            p["pageToken"] = page_token
        data = await _req("GET", "/history", params=p)
        items = (
            data.get("history", [])
            if isinstance(data, dict) else data
        )
        npt = (
            data.get("nextPageToken")
            if isinstance(data, dict) else None
        )
        hid = (
            data.get("historyId")
            if isinstance(data, dict) else None
        )
        return _success(
            200, data=items, count=len(items),
            next_page_token=npt, history_id=hid,
        )

    # ================================================================
    # TIER 6: SETTINGS & PROFILE (13 tools)
    # ================================================================

    @mcp.tool()
    async def gmail_get_vacation_settings() -> str:
        """Get vacation (out-of-office) auto-reply settings."""
        data = await _req("GET", "/settings/vacation")
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_update_vacation_settings(
        enable_auto_reply: bool,
        response_subject: str | None = None,
        response_body_plain_text: str | None = None,
        response_body_html: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        restrict_to_contacts: bool | None = None,
        restrict_to_domain: bool | None = None,
    ) -> str:
        """Update vacation auto-reply settings.
        Args:
            enable_auto_reply: Enable or disable auto-reply
            response_subject: Auto-reply subject
            response_body_plain_text: Plain text body
            response_body_html: HTML body
            start_time: Start time epoch ms (UTC)
            end_time: End time epoch ms (UTC)
            restrict_to_contacts: Only reply to contacts
            restrict_to_domain: Only reply to same domain
        """
        body: dict = {
            "enableAutoReply": enable_auto_reply,
        }
        if response_subject is not None:
            body["responseSubject"] = response_subject
        if response_body_plain_text is not None:
            body["responseBodyPlainText"] = (
                response_body_plain_text
            )
        if response_body_html is not None:
            body["responseBodyHtml"] = response_body_html
        if start_time is not None:
            body["startTime"] = start_time
        if end_time is not None:
            body["endTime"] = end_time
        if restrict_to_contacts is not None:
            body["restrictToContacts"] = restrict_to_contacts
        if restrict_to_domain is not None:
            body["restrictToDomain"] = restrict_to_domain
        data = await _req(
            "PUT", "/settings/vacation", json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_get_auto_forwarding() -> str:
        """Get auto-forwarding settings."""
        data = await _req(
            "GET", "/settings/autoForwarding",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_update_auto_forwarding(
        enabled: bool,
        email_address: str | None = None,
        disposition: str | None = None,
    ) -> str:
        """Update auto-forwarding settings.
        Args:
            enabled: Enable or disable forwarding
            email_address: Forwarding address (must be verified)
            disposition: leaveInInbox, archive, trash, markRead
        """
        body: dict = {"enabled": enabled}
        if email_address is not None:
            body["emailAddress"] = email_address
        if disposition is not None:
            body["disposition"] = disposition
        data = await _req(
            "PUT", "/settings/autoForwarding",
            json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_get_imap_settings() -> str:
        """Get IMAP access settings."""
        data = await _req("GET", "/settings/imap")
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_update_imap_settings(
        enabled: bool,
        auto_expunge: bool | None = None,
        expunge_behavior: str | None = None,
        max_folder_size: int | None = None,
    ) -> str:
        """Update IMAP access settings.
        Args:
            enabled: Enable or disable IMAP
            auto_expunge: Auto-expunge on delete
            expunge_behavior: archive, deleteForever, trash
            max_folder_size: Max folder size (0 = no limit)
        """
        body: dict = {"enabled": enabled}
        if auto_expunge is not None:
            body["autoExpunge"] = auto_expunge
        if expunge_behavior is not None:
            body["expungeBehavior"] = expunge_behavior
        if max_folder_size is not None:
            body["maxFolderSize"] = max_folder_size
        data = await _req(
            "PUT", "/settings/imap", json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_get_pop_settings() -> str:
        """Get POP access settings."""
        data = await _req("GET", "/settings/pop")
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_update_pop_settings(
        access_window: str,
        disposition: str | None = None,
    ) -> str:
        """Update POP access settings.
        Args:
            access_window: disabled, allMail, or fromNowOn
            disposition: leaveInInbox, archive, trash, markRead
        """
        body: dict = {"accessWindow": access_window}
        if disposition is not None:
            body["disposition"] = disposition
        data = await _req(
            "PUT", "/settings/pop", json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_get_language_settings() -> str:
        """Get the user's language/display settings."""
        data = await _req("GET", "/settings/language")
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_update_language_settings(
        display_language: str,
    ) -> str:
        """Update the user's display language.
        Args:
            display_language: BCP 47 tag (e.g. en, fr, ja)
        """
        data = await _req(
            "PUT", "/settings/language",
            json_body={"displayLanguage": display_language},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_get_profile() -> str:
        """Get user profile (email, counts, history ID)."""
        data = await _req("GET", "/profile")
        return _success(200, data=data)

    # --- Tier 6 count note: 11 tools above ---
    # get_vacation, update_vacation, get_auto_forwarding,
    # update_auto_forwarding, get_imap, update_imap,
    # get_pop, update_pop, get_language, update_language,
    # get_profile = 11 tools.
    # Analysis says 13 but only lists 11 distinct endpoints.
    # The 2 "missing" are update_imap and update_pop which
    # are included above. Count verified: 11 settings tools.

    # ================================================================
    # TIER 7: SEND-AS ALIASES (7 tools)
    # ================================================================

    @mcp.tool()
    async def gmail_list_send_as() -> str:
        """List send-as aliases for the user."""
        data = await _req("GET", "/settings/sendAs")
        items = (
            data.get("sendAs", [])
            if isinstance(data, dict) else data
        )
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def gmail_get_send_as(
        send_as_email: str,
    ) -> str:
        """Get a specific send-as alias.
        Args:
            send_as_email: Send-as email address
        """
        data = await _req(
            "GET", f"/settings/sendAs/{send_as_email}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_create_send_as(
        send_as_email: str,
        display_name: str | None = None,
        reply_to_address: str | None = None,
        is_default: bool | None = None,
        treat_as_alias: bool | None = None,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        smtp_security_mode: str | None = None,
    ) -> str:
        """Create a new send-as alias. Requires verification.
        Args:
            send_as_email: Email address for the alias
            display_name: Display name
            reply_to_address: Reply-to address
            is_default: Set as default send-as
            treat_as_alias: Treat as alias for reply behavior
            smtp_host: SMTP server (if custom)
            smtp_port: SMTP port
            smtp_username: SMTP username
            smtp_password: SMTP password
            smtp_security_mode: none, ssl, or starttls
        """
        body: dict = {"sendAsEmail": send_as_email}
        if display_name is not None:
            body["displayName"] = display_name
        if reply_to_address is not None:
            body["replyToAddress"] = reply_to_address
        if is_default is not None:
            body["isDefault"] = is_default
        if treat_as_alias is not None:
            body["treatAsAlias"] = treat_as_alias
        if smtp_host is not None:
            smtp: dict = {"host": smtp_host}
            if smtp_port is not None:
                smtp["port"] = smtp_port
            if smtp_username is not None:
                smtp["username"] = smtp_username
            if smtp_password is not None:
                smtp["password"] = smtp_password
            if smtp_security_mode is not None:
                smtp["securityMode"] = smtp_security_mode
            body["smtpMsa"] = smtp
        data = await _req(
            "POST", "/settings/sendAs", json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_update_send_as(
        send_as_email: str,
        display_name: str | None = None,
        reply_to_address: str | None = None,
        is_default: bool | None = None,
    ) -> str:
        """Update a send-as alias (full update).
        Args:
            send_as_email: Send-as email to update
            display_name: New display name
            reply_to_address: New reply-to address
            is_default: Set as default
        """
        body: dict = {"sendAsEmail": send_as_email}
        if display_name is not None:
            body["displayName"] = display_name
        if reply_to_address is not None:
            body["replyToAddress"] = reply_to_address
        if is_default is not None:
            body["isDefault"] = is_default
        data = await _req(
            "PUT", f"/settings/sendAs/{send_as_email}",
            json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_patch_send_as(
        send_as_email: str,
        display_name: str | None = None,
        reply_to_address: str | None = None,
        is_default: bool | None = None,
    ) -> str:
        """Partially update a send-as alias.
        Args:
            send_as_email: Send-as email to patch
            display_name: New display name
            reply_to_address: New reply-to address
            is_default: Set as default
        """
        body: dict = {}
        if display_name is not None:
            body["displayName"] = display_name
        if reply_to_address is not None:
            body["replyToAddress"] = reply_to_address
        if is_default is not None:
            body["isDefault"] = is_default
        if not body:
            raise ToolError(
                "At least one field must be provided."
            )
        data = await _req(
            "PATCH", f"/settings/sendAs/{send_as_email}",
            json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_delete_send_as(
        send_as_email: str,
    ) -> str:
        """Delete a send-as alias. Cannot delete primary.
        Args:
            send_as_email: Send-as email to delete
        """
        await _req(
            "DELETE", f"/settings/sendAs/{send_as_email}",
        )
        return _success(204, message="Send-as deleted.")

    @mcp.tool()
    async def gmail_verify_send_as(
        send_as_email: str,
    ) -> str:
        """Send verification email for a send-as alias.
        Args:
            send_as_email: Send-as email to verify
        """
        await _req(
            "POST",
            f"/settings/sendAs/{send_as_email}/verify",
        )
        return _success(
            204, message="Verification email sent.",
        )

    # ================================================================
    # TIER 8: FILTERS (4 tools)
    # ================================================================

    @mcp.tool()
    async def gmail_list_filters() -> str:
        """List all email filters."""
        data = await _req("GET", "/settings/filters")
        items = (
            data.get("filter", [])
            if isinstance(data, dict) else data
        )
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def gmail_get_filter(filter_id: str) -> str:
        """Get a specific email filter.
        Args:
            filter_id: Filter ID
        """
        data = await _req(
            "GET", f"/settings/filters/{filter_id}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_create_filter(
        criteria_from: str | None = None,
        criteria_to: str | None = None,
        criteria_subject: str | None = None,
        criteria_query: str | None = None,
        criteria_negated_query: str | None = None,
        criteria_has_attachment: bool | None = None,
        criteria_exclude_chats: bool | None = None,
        criteria_size: int | None = None,
        criteria_size_comparison: str | None = None,
        action_add_label_ids: list[str] | None = None,
        action_remove_label_ids: list[str] | None = None,
        action_forward: str | None = None,
    ) -> str:
        """Create a new email filter.
        Args:
            criteria_from: Match sender
            criteria_to: Match recipient
            criteria_subject: Match subject
            criteria_query: Gmail search query to match
            criteria_negated_query: Negated search query
            criteria_has_attachment: Match messages with attachments
            criteria_exclude_chats: Exclude chat messages
            criteria_size: Size in bytes for comparison
            criteria_size_comparison: larger or smaller
            action_add_label_ids: Labels to add
            action_remove_label_ids: Labels to remove
            action_forward: Forward to email (must be verified)
        """
        criteria: dict = {}
        if criteria_from is not None:
            criteria["from"] = criteria_from
        if criteria_to is not None:
            criteria["to"] = criteria_to
        if criteria_subject is not None:
            criteria["subject"] = criteria_subject
        if criteria_query is not None:
            criteria["query"] = criteria_query
        if criteria_negated_query is not None:
            criteria["negatedQuery"] = criteria_negated_query
        if criteria_has_attachment is not None:
            criteria["hasAttachment"] = criteria_has_attachment
        if criteria_exclude_chats is not None:
            criteria["excludeChats"] = criteria_exclude_chats
        if criteria_size is not None:
            criteria["size"] = criteria_size
        if criteria_size_comparison is not None:
            criteria["sizeComparison"] = (
                criteria_size_comparison
            )
        action: dict = {}
        if action_add_label_ids is not None:
            action["addLabelIds"] = action_add_label_ids
        if action_remove_label_ids is not None:
            action["removeLabelIds"] = action_remove_label_ids
        if action_forward is not None:
            action["forward"] = action_forward
        body: dict = {}
        if criteria:
            body["criteria"] = criteria
        if action:
            body["action"] = action
        data = await _req(
            "POST", "/settings/filters", json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_delete_filter(filter_id: str) -> str:
        """Delete an email filter.
        Args:
            filter_id: Filter ID to delete
        """
        await _req(
            "DELETE", f"/settings/filters/{filter_id}",
        )
        return _success(204, message="Filter deleted.")

    # ================================================================
    # TIER 9: FORWARDING ADDRESSES (4 tools)
    # ================================================================

    @mcp.tool()
    async def gmail_list_forwarding_addresses() -> str:
        """List forwarding addresses."""
        data = await _req(
            "GET", "/settings/forwardingAddresses",
        )
        items = (
            data.get("forwardingAddresses", [])
            if isinstance(data, dict) else data
        )
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def gmail_get_forwarding_address(
        forwarding_email: str,
    ) -> str:
        """Get a specific forwarding address.
        Args:
            forwarding_email: Forwarding email address
        """
        data = await _req(
            "GET",
            f"/settings/forwardingAddresses"
            f"/{forwarding_email}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_create_forwarding_address(
        forwarding_email: str,
    ) -> str:
        """Add a new forwarding address. Sends verification.
        Args:
            forwarding_email: Email to add as forwarding dest
        """
        data = await _req(
            "POST", "/settings/forwardingAddresses",
            json_body={
                "forwardingEmail": forwarding_email,
            },
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_delete_forwarding_address(
        forwarding_email: str,
    ) -> str:
        """Delete a forwarding address.
        Args:
            forwarding_email: Forwarding email to remove
        """
        await _req(
            "DELETE",
            f"/settings/forwardingAddresses"
            f"/{forwarding_email}",
        )
        return _success(
            204, message="Forwarding address deleted.",
        )

    # ================================================================
    # TIER 10: DELEGATES (4 tools)
    # ================================================================

    @mcp.tool()
    async def gmail_list_delegates() -> str:
        """List delegates with access to this account."""
        data = await _req("GET", "/settings/delegates")
        items = (
            data.get("delegates", [])
            if isinstance(data, dict) else data
        )
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def gmail_get_delegate(
        delegate_email: str,
    ) -> str:
        """Get a specific delegate.
        Args:
            delegate_email: Delegate email address
        """
        data = await _req(
            "GET",
            f"/settings/delegates/{delegate_email}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_create_delegate(
        delegate_email: str,
    ) -> str:
        """Add a delegate to the account.
        Args:
            delegate_email: Email of the delegate to add
        """
        data = await _req(
            "POST", "/settings/delegates",
            json_body={"delegateEmail": delegate_email},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gmail_delete_delegate(
        delegate_email: str,
    ) -> str:
        """Remove a delegate from the account.
        Args:
            delegate_email: Email of the delegate to remove
        """
        await _req(
            "DELETE",
            f"/settings/delegates/{delegate_email}",
        )
        return _success(204, message="Delegate deleted.")

    # ================================================================
    # TIER 11: ATTACHMENTS (1 tool)
    # ================================================================

    @mcp.tool()
    async def gmail_get_attachment(
        message_id: str,
        attachment_id: str,
    ) -> str:
        """Get attachment data from a message.
        Args:
            message_id: Message ID containing the attachment
            attachment_id: Attachment ID from message parts
        """
        data = await _req(
            "GET",
            f"/messages/{message_id}"
            f"/attachments/{attachment_id}",
        )
        return _success(200, data=data)
