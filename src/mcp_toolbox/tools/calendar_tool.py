"""Microsoft Graph Calendar integration — events, scheduling, availability."""

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
    global _msal_app
    if not O365_TENANT_ID or not O365_CLIENT_ID or not O365_CLIENT_SECRET:
        raise ToolError(
            "O365 credentials not configured. Set O365_TENANT_ID, "
            "O365_CLIENT_ID, and O365_CLIENT_SECRET."
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
            f"Failed to acquire token: "
            f"{result.get('error_description', result.get('error', 'unknown'))}"
        )
    return result["access_token"]


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url="https://graph.microsoft.com/v1.0",
            timeout=30.0,
        )
    return _http_client


def _uid(override: str | None = None) -> str:
    uid = override or O365_USER_ID
    if not uid:
        raise ToolError("No user_id provided. Set O365_USER_ID or pass user_id.")
    return uid


def _ensure_list(v: str | list[str]) -> list[str]:
    return [v] if isinstance(v, str) else v


def _recipients(emails: str | list[str]) -> list[dict]:
    return [{"emailAddress": {"address": e}, "type": "required"} for e in _ensure_list(emails)]


def _success(sc: int, **kw) -> str:
    return json.dumps({"status": "success", "status_code": sc, **kw})


async def _request(method: str, path: str, **kwargs) -> dict | list:
    token = await asyncio.to_thread(_get_token)
    client = _get_http_client()
    try:
        response = await client.request(
            method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs,
        )
    except httpx.HTTPError as e:
        raise ToolError(f"Graph API request failed: {e}") from e
    if response.status_code == 429:
        ra = response.headers.get("Retry-After", "unknown")
        raise ToolError(f"Rate limit exceeded. Retry after {ra} seconds.")
    if response.status_code >= 400:
        try:
            ei = response.json().get("error", {})
            msg = ei.get("message", response.text)
            code = ei.get("code", "")
        except Exception:
            msg, code = response.text, ""
        raise ToolError(
            f"Graph API error ({response.status_code}"
            f"{f' {code}' if code else ''}): {msg}"
        )
    if response.status_code in (202, 204):
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def _dt(dt_str: str, tz: str = "UTC") -> dict:
    return {"dateTime": dt_str, "timeZone": tz}


def register_tools(mcp: FastMCP) -> None:
    if not O365_CLIENT_ID:
        logger.warning("O365 credentials not set — calendar tools will fail at invocation.")

    # --- Calendar Management ---

    @mcp.tool()
    async def calendar_list_calendars(user_id: str | None = None) -> str:
        """List all calendars for a user.

        Args:
            user_id: User email or ID (uses default if not provided)
        """
        data = await _request("GET", f"/users/{_uid(user_id)}/calendars")
        cals = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=cals, count=len(cals))

    @mcp.tool()
    async def calendar_get_calendar(
        calendar_id: str, user_id: str | None = None,
    ) -> str:
        """Get calendar details.

        Args:
            calendar_id: Calendar ID
            user_id: User email or ID
        """
        data = await _request("GET", f"/users/{_uid(user_id)}/calendars/{calendar_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def calendar_create_calendar(
        name: str, user_id: str | None = None,
    ) -> str:
        """Create a new calendar.

        Args:
            name: Calendar display name
            user_id: User email or ID
        """
        data = await _request(
            "POST", f"/users/{_uid(user_id)}/calendars", json={"name": name},
        )
        return _success(201, data=data)

    @mcp.tool()
    async def calendar_delete_calendar(
        calendar_id: str, user_id: str | None = None,
    ) -> str:
        """Delete a calendar.

        Args:
            calendar_id: Calendar ID
            user_id: User email or ID
        """
        await _request("DELETE", f"/users/{_uid(user_id)}/calendars/{calendar_id}")
        return _success(204, deleted_calendar_id=calendar_id)

    # --- Event CRUD ---

    @mcp.tool()
    async def calendar_create_event(
        subject: str,
        start_datetime: str,
        end_datetime: str,
        timezone: str = "UTC",
        body: str | None = None,
        body_content_type: str = "HTML",
        location: str | None = None,
        attendees: str | list[str] | None = None,
        is_all_day: bool = False,
        is_online_meeting: bool = False,
        online_meeting_provider: str = "teamsForBusiness",
        importance: str | None = None,
        sensitivity: str | None = None,
        show_as: str | None = None,
        is_reminder_on: bool = True,
        reminder_minutes: int = 15,
        categories: list[str] | None = None,
        recurrence: dict | None = None,
        calendar_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Create a calendar event with optional attendees and online meeting.

        Args:
            subject: Event title
            start_datetime: Start (ISO 8601)
            end_datetime: End (ISO 8601)
            timezone: IANA timezone (default UTC)
            body: Event description
            body_content_type: HTML or Text
            location: Location name
            attendees: Attendee email(s)
            is_all_day: All-day event
            is_online_meeting: Create Teams meeting
            online_meeting_provider: teamsForBusiness, skypeForBusiness
            importance: low, normal, high
            sensitivity: normal, personal, private, confidential
            show_as: free, tentative, busy, oof, workingElsewhere
            is_reminder_on: Enable reminder
            reminder_minutes: Minutes before for reminder
            categories: Category labels
            recurrence: Recurrence pattern (Graph API format)
            calendar_id: Specific calendar (default if omitted)
            user_id: User email or ID
        """
        ev: dict = {
            "subject": subject,
            "start": _dt(start_datetime, timezone),
            "end": _dt(end_datetime, timezone),
            "isAllDay": is_all_day,
            "isOnlineMeeting": is_online_meeting,
            "isReminderOn": is_reminder_on,
            "reminderMinutesBeforeStart": reminder_minutes,
        }
        if body:
            ev["body"] = {"contentType": body_content_type, "content": body}
        if location:
            ev["location"] = {"displayName": location}
        if attendees:
            ev["attendees"] = _recipients(attendees)
        if is_online_meeting:
            ev["onlineMeetingProvider"] = online_meeting_provider
        if importance:
            ev["importance"] = importance
        if sensitivity:
            ev["sensitivity"] = sensitivity
        if show_as:
            ev["showAs"] = show_as
        if categories:
            ev["categories"] = categories
        if recurrence:
            ev["recurrence"] = recurrence

        uid = _uid(user_id)
        path = (
            f"/users/{uid}/calendars/{calendar_id}/events"
            if calendar_id
            else f"/users/{uid}/calendar/events"
        )
        data = await _request("POST", path, json=ev)
        return _success(201, data=data)

    @mcp.tool()
    async def calendar_get_event(
        event_id: str, select: str | None = None, user_id: str | None = None,
    ) -> str:
        """Get event details.

        Args:
            event_id: Event ID
            select: Comma-separated fields to return
            user_id: User email or ID
        """
        params = {}
        if select:
            params["$select"] = select
        data = await _request(
            "GET", f"/users/{_uid(user_id)}/events/{event_id}", params=params,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def calendar_update_event(
        event_id: str,
        subject: str | None = None,
        start_datetime: str | None = None,
        end_datetime: str | None = None,
        timezone: str | None = None,
        body: str | None = None,
        body_content_type: str = "HTML",
        location: str | None = None,
        attendees: str | list[str] | None = None,
        is_all_day: bool | None = None,
        is_online_meeting: bool | None = None,
        importance: str | None = None,
        sensitivity: str | None = None,
        show_as: str | None = None,
        is_reminder_on: bool | None = None,
        reminder_minutes: int | None = None,
        categories: list[str] | None = None,
        recurrence: dict | None = None,
        user_id: str | None = None,
    ) -> str:
        """Update event properties.

        Args:
            event_id: Event ID
            subject: New subject
            start_datetime: New start (ISO 8601)
            end_datetime: New end (ISO 8601)
            timezone: IANA timezone
            body: New description
            body_content_type: HTML or Text
            location: New location
            attendees: New attendee list
            is_all_day: All-day flag
            is_online_meeting: Online meeting flag
            importance: low, normal, high
            sensitivity: normal, personal, private, confidential
            show_as: Free/busy status
            is_reminder_on: Reminder flag
            reminder_minutes: Minutes before
            categories: Category labels
            recurrence: Recurrence pattern
            user_id: User email or ID
        """
        patch: dict = {}
        tz = timezone or "UTC"
        if subject is not None:
            patch["subject"] = subject
        if start_datetime is not None:
            patch["start"] = _dt(start_datetime, tz)
        if end_datetime is not None:
            patch["end"] = _dt(end_datetime, tz)
        if body is not None:
            patch["body"] = {"contentType": body_content_type, "content": body}
        if location is not None:
            patch["location"] = {"displayName": location}
        if attendees is not None:
            patch["attendees"] = _recipients(attendees)
        if is_all_day is not None:
            patch["isAllDay"] = is_all_day
        if is_online_meeting is not None:
            patch["isOnlineMeeting"] = is_online_meeting
        if importance is not None:
            patch["importance"] = importance
        if sensitivity is not None:
            patch["sensitivity"] = sensitivity
        if show_as is not None:
            patch["showAs"] = show_as
        if is_reminder_on is not None:
            patch["isReminderOn"] = is_reminder_on
        if reminder_minutes is not None:
            patch["reminderMinutesBeforeStart"] = reminder_minutes
        if categories is not None:
            patch["categories"] = categories
        if recurrence is not None:
            patch["recurrence"] = recurrence
        if not patch:
            raise ToolError("At least one field to update must be provided.")
        data = await _request(
            "PATCH", f"/users/{_uid(user_id)}/events/{event_id}", json=patch,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def calendar_delete_event(
        event_id: str, user_id: str | None = None,
    ) -> str:
        """Delete a calendar event.

        Args:
            event_id: Event ID
            user_id: User email or ID
        """
        await _request("DELETE", f"/users/{_uid(user_id)}/events/{event_id}")
        return _success(204, deleted_event_id=event_id)

    @mcp.tool()
    async def calendar_list_events(
        start_datetime: str,
        end_datetime: str,
        top: int = 25,
        select: str | None = None,
        filter: str | None = None,
        order_by: str | None = None,
        calendar_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """List events in a date range (expands recurring events).

        Args:
            start_datetime: Range start (ISO 8601)
            end_datetime: Range end (ISO 8601)
            top: Max results (default 25)
            select: Comma-separated fields
            filter: OData filter
            order_by: Sort field
            calendar_id: Specific calendar
            user_id: User email or ID
        """
        uid = _uid(user_id)
        base = (
            f"/users/{uid}/calendars/{calendar_id}/calendarView"
            if calendar_id
            else f"/users/{uid}/calendarView"
        )
        params: dict = {
            "startDateTime": start_datetime,
            "endDateTime": end_datetime,
            "$top": str(top),
        }
        if select:
            params["$select"] = select
        if filter:
            params["$filter"] = filter
        if order_by:
            params["$orderby"] = order_by
        data = await _request("GET", base, params=params)
        events = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=events, count=len(events))

    # --- Event Responses ---

    @mcp.tool()
    async def calendar_accept_event(
        event_id: str, comment: str | None = None,
        send_response: bool = True, user_id: str | None = None,
    ) -> str:
        """Accept a meeting invitation.

        Args:
            event_id: Event ID
            comment: Response comment
            send_response: Notify organizer (default true)
            user_id: User email or ID
        """
        body: dict = {"sendResponse": send_response}
        if comment:
            body["comment"] = comment
        await _request(
            "POST", f"/users/{_uid(user_id)}/events/{event_id}/accept", json=body,
        )
        return _success(202, message="Event accepted")

    @mcp.tool()
    async def calendar_decline_event(
        event_id: str, comment: str | None = None,
        send_response: bool = True, proposed_new_time: dict | None = None,
        user_id: str | None = None,
    ) -> str:
        """Decline a meeting invitation.

        Args:
            event_id: Event ID
            comment: Response comment
            send_response: Notify organizer (default true)
            proposed_new_time: Alternative time proposal
            user_id: User email or ID
        """
        body: dict = {"sendResponse": send_response}
        if comment:
            body["comment"] = comment
        if proposed_new_time:
            body["proposedNewTime"] = proposed_new_time
        await _request(
            "POST", f"/users/{_uid(user_id)}/events/{event_id}/decline", json=body,
        )
        return _success(202, message="Event declined")

    @mcp.tool()
    async def calendar_tentatively_accept_event(
        event_id: str, comment: str | None = None,
        send_response: bool = True, proposed_new_time: dict | None = None,
        user_id: str | None = None,
    ) -> str:
        """Tentatively accept a meeting invitation.

        Args:
            event_id: Event ID
            comment: Response comment
            send_response: Notify organizer
            proposed_new_time: Alternative time proposal
            user_id: User email or ID
        """
        body: dict = {"sendResponse": send_response}
        if comment:
            body["comment"] = comment
        if proposed_new_time:
            body["proposedNewTime"] = proposed_new_time
        await _request(
            "POST",
            f"/users/{_uid(user_id)}/events/{event_id}/tentativelyAccept",
            json=body,
        )
        return _success(202, message="Event tentatively accepted")

    # --- Scheduling ---

    @mcp.tool()
    async def calendar_get_schedule(
        schedules: str | list[str],
        start_datetime: str,
        end_datetime: str,
        timezone: str = "UTC",
        availability_view_interval: int = 30,
        user_id: str | None = None,
    ) -> str:
        """Get free/busy availability for users/rooms (max 20).

        Args:
            schedules: Email address(es) to check (max 20)
            start_datetime: Range start (ISO 8601)
            end_datetime: Range end (ISO 8601)
            timezone: IANA timezone
            availability_view_interval: Slot duration in minutes (default 30)
            user_id: User making the request
        """
        body = {
            "schedules": _ensure_list(schedules),
            "startTime": _dt(start_datetime, timezone),
            "endTime": _dt(end_datetime, timezone),
            "availabilityViewInterval": availability_view_interval,
        }
        data = await _request(
            "POST", f"/users/{_uid(user_id)}/calendar/getSchedule", json=body,
        )
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def calendar_find_meeting_times(
        attendees: list[dict],
        duration: str | None = None,
        time_constraint: dict | None = None,
        user_id: str | None = None,
    ) -> str:
        """Suggest meeting times based on attendee availability.

        Args:
            attendees: List of attendee objects
            duration: ISO 8601 duration (e.g., PT1H, PT30M)
            time_constraint: Time constraint object
            user_id: User email or ID
        """
        body: dict = {"attendees": attendees}
        if duration:
            body["meetingDuration"] = duration
        if time_constraint:
            body["timeConstraint"] = time_constraint
        data = await _request(
            "POST", f"/users/{_uid(user_id)}/findMeetingTimes", json=body,
        )
        return _success(200, data=data)

    # --- Recurring Events ---

    @mcp.tool()
    async def calendar_list_event_instances(
        event_id: str,
        start_datetime: str,
        end_datetime: str,
        top: int = 10,
        select: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """List instances of a recurring event in a time range.

        Args:
            event_id: Series master event ID
            start_datetime: Range start (ISO 8601)
            end_datetime: Range end (ISO 8601)
            top: Max results (default 10)
            select: Comma-separated fields
            user_id: User email or ID
        """
        params: dict = {
            "startDateTime": start_datetime,
            "endDateTime": end_datetime,
            "$top": str(top),
        }
        if select:
            params["$select"] = select
        data = await _request(
            "GET", f"/users/{_uid(user_id)}/events/{event_id}/instances",
            params=params,
        )
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))

    # --- Event Actions ---

    @mcp.tool()
    async def calendar_forward_event(
        event_id: str, to: str | list[str],
        comment: str | None = None, user_id: str | None = None,
    ) -> str:
        """Forward a calendar event to recipients.

        Args:
            event_id: Event ID
            to: Recipient email(s)
            comment: Comment to include
            user_id: User email or ID
        """
        body: dict = {
            "toRecipients": [
                {"emailAddress": {"address": e}} for e in _ensure_list(to)
            ],
        }
        if comment:
            body["comment"] = comment
        await _request(
            "POST", f"/users/{_uid(user_id)}/events/{event_id}/forward", json=body,
        )
        return _success(202, message="Event forwarded")

    @mcp.tool()
    async def calendar_cancel_event(
        event_id: str, comment: str | None = None, user_id: str | None = None,
    ) -> str:
        """Cancel a meeting and notify attendees (organizer only).

        Args:
            event_id: Event ID
            comment: Cancellation message
            user_id: User email or ID
        """
        body: dict = {}
        if comment:
            body["comment"] = comment
        await _request(
            "POST", f"/users/{_uid(user_id)}/events/{event_id}/cancel", json=body,
        )
        return _success(202, message="Event cancelled")

    # --- Event Attachments ---

    @mcp.tool()
    async def calendar_add_event_attachment(
        event_id: str, file_path: str,
        file_name: str | None = None, content_type: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Add a file attachment to an event (max 3MB).

        Args:
            event_id: Event ID
            file_path: Local file path
            file_name: Display name
            content_type: MIME type
            user_id: User email or ID
        """
        fp = Path(file_path)
        if not fp.is_file():
            raise ToolError(f"File not found: {file_path}") from None
        content_bytes = base64.b64encode(fp.read_bytes()).decode()
        att = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": file_name or fp.name,
            "contentType": content_type or "application/octet-stream",
            "contentBytes": content_bytes,
        }
        data = await _request(
            "POST", f"/users/{_uid(user_id)}/events/{event_id}/attachments",
            json=att,
        )
        return _success(201, data=data)

    @mcp.tool()
    async def calendar_list_event_attachments(
        event_id: str, user_id: str | None = None,
    ) -> str:
        """List attachments on an event.

        Args:
            event_id: Event ID
            user_id: User email or ID
        """
        data = await _request(
            "GET", f"/users/{_uid(user_id)}/events/{event_id}/attachments",
        )
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def calendar_get_event_attachment(
        event_id: str, attachment_id: str, user_id: str | None = None,
    ) -> str:
        """Get a specific event attachment.

        Args:
            event_id: Event ID
            attachment_id: Attachment ID
            user_id: User email or ID
        """
        data = await _request(
            "GET",
            f"/users/{_uid(user_id)}/events/{event_id}/attachments/{attachment_id}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def calendar_delete_event_attachment(
        event_id: str, attachment_id: str, user_id: str | None = None,
    ) -> str:
        """Delete an event attachment.

        Args:
            event_id: Event ID
            attachment_id: Attachment ID
            user_id: User email or ID
        """
        await _request(
            "DELETE",
            f"/users/{_uid(user_id)}/events/{event_id}/attachments/{attachment_id}",
        )
        return _success(204, deleted_attachment_id=attachment_id)

    # --- Event Reminders ---

    @mcp.tool()
    async def calendar_snooze_reminder(
        event_id: str, new_reminder_time: str, user_id: str | None = None,
    ) -> str:
        """Snooze an event reminder to a new time.

        Args:
            event_id: Event ID
            new_reminder_time: New reminder time (ISO 8601)
            user_id: User email or ID
        """
        body = {
            "newReminderTime": {"dateTime": new_reminder_time, "timeZone": "UTC"},
        }
        await _request(
            "POST", f"/users/{_uid(user_id)}/events/{event_id}/snoozeReminder",
            json=body,
        )
        return _success(200, message="Reminder snoozed")

    @mcp.tool()
    async def calendar_dismiss_reminder(
        event_id: str, user_id: str | None = None,
    ) -> str:
        """Dismiss an event reminder.

        Args:
            event_id: Event ID
            user_id: User email or ID
        """
        await _request(
            "POST", f"/users/{_uid(user_id)}/events/{event_id}/dismissReminder",
        )
        return _success(200, message="Reminder dismissed")
