"""SendGrid integration — email sending, management, and contact tools."""

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

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


def _get_from_email(override: str | None = None) -> str | tuple[str, str]:
    """Resolve sender email: override > config > error. Includes display name if set."""
    email = override or SENDGRID_FROM_EMAIL
    if not email:
        raise ToolError(
            "No sender email provided. Either pass from_email or set "
            "SENDGRID_FROM_EMAIL in your environment."
        )
    if not override and SENDGRID_FROM_NAME:
        return (email, SENDGRID_FROM_NAME)
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


def _parse_response(response) -> dict | list:
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
                raise ToolError(f"Attachment file not found: {file_path}") from None
            except OSError as e:
                raise ToolError(f"Error reading attachment {file_path}: {e}") from e

            file_name = att.get("file_name", Path(file_path).name)
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

    # --- Tier 2: Email Management Tools ---

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
        templates = (
            data if isinstance(data, list)
            else data.get("templates", data.get("result", []))
        )
        return _success(
            response.status_code,
            data=[
                {"id": t.get("id"), "name": t.get("name"), "updated_at": t.get("updated_at")}
                for t in templates
            ]
            if isinstance(templates, list)
            else templates,
            count=len(templates) if isinstance(templates, list) else 0,
        )

    @mcp.tool()
    async def get_template(template_id: str) -> str:
        """Get details of a specific SendGrid dynamic template.

        Args:
            template_id: Template ID (format: d-xxxxx)
        """
        sg = _get_client()

        try:
            response = await asyncio.to_thread(sg.client.templates._(template_id).get)
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        data = _parse_response(response)
        return _success(response.status_code, data=data)

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
            response = await asyncio.to_thread(sg.client.stats.get, query_params=params)
        except Exception as e:
            raise ToolError(f"SendGrid API error: {e}") from e

        data = _parse_response(response)
        return _success(response.status_code, data=data)

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

        valid_types = [
            "bounces",
            "blocks",
            "spam_reports",
            "invalid_emails",
            "global_unsubscribes",
        ]
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
            endpoint_map = {
                "bounces": sg.client.suppression.bounces,
                "blocks": sg.client.suppression.blocks,
                "spam_reports": sg.client.suppression.spam_reports,
                "invalid_emails": sg.client.suppression.invalid_emails,
                "global_unsubscribes": sg.client.asm.suppressions._("global"),
            }
            endpoint = endpoint_map[suppression_type]

            results = []
            for email in emails:
                try:
                    response = await asyncio.to_thread(endpoint._(email).delete)
                    results.append({"email": email, "status": "removed"})
                except Exception as e:
                    results.append({"email": email, "status": "error", "error": str(e)})

            return _success(200, action="removed", results=results)

        else:
            raise ToolError(f"Invalid action '{action}'. Must be 'add' or 'remove'.")

    # --- Tier 3: Contact Management Tools ---

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
        job_id = data.get("job_id") if isinstance(data, dict) else None
        return _success(response.status_code, job_id=job_id, contacts_count=len(contacts))

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
        if isinstance(data, list):
            results = data
            count = len(results)
        else:
            results = data.get("result", [])
            count = data.get("contact_count", len(results))
        return _success(response.status_code, data=results, count=count)

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
                response = await asyncio.to_thread(sg.client.marketing.lists.get)
            except Exception as e:
                raise ToolError(f"SendGrid API error: {e}") from e

            data = _parse_response(response)
            lists = data if isinstance(data, list) else data.get("result", [])
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
            raise ToolError(
                f"Invalid action '{action}'. Must be 'create', 'list', or 'delete'."
            )
