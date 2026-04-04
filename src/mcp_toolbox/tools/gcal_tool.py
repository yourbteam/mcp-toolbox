"""Google Calendar API v3 integration — calendars, events, ACLs, scheduling."""

import asyncio
import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import (
    GCAL_DEFAULT_CALENDAR_ID,
    GOOGLE_SERVICE_ACCOUNT_JSON,
)

logger = logging.getLogger(__name__)

_credentials = None
_client: httpx.AsyncClient | None = None

BASE = "https://www.googleapis.com/calendar/v3"


def _get_token() -> str:
    global _credentials
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ToolError(
            "GOOGLE_SERVICE_ACCOUNT_JSON not configured. "
            "Set it to the path of your service account JSON key file."
        )
    if _credentials is None:
        import google.auth.transport.requests
        from google.oauth2 import service_account

        _credentials = (
            service_account.Credentials.from_service_account_file(
                GOOGLE_SERVICE_ACCOUNT_JSON,
                scopes=[
                    "https://www.googleapis.com/auth/calendar"
                ],
            )
        )
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
        _client = httpx.AsyncClient(
            base_url=BASE, timeout=30.0
        )
    _client.headers["Authorization"] = f"Bearer {token}"
    return _client


def _success(sc: int, **kw: object) -> str:
    return json.dumps(
        {"status": "success", "status_code": sc, **kw}
    )


def _cid(override: str | None = None) -> str:
    return override or GCAL_DEFAULT_CALENDAR_ID or "primary"


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
        raise ToolError(
            f"Google Calendar request failed: {e}"
        ) from e
    if response.status_code == 429:
        raise ToolError(
            "Google Calendar rate limit exceeded. "
            "Retry after a short delay."
        )
    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
            msg = err.get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(
            f"Google Calendar error "
            f"({response.status_code}): {msg}"
        )
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


# -- helpers ------------------------------------------------


def _build_event_body(
    summary: str | None = None,
    description: str | None = None,
    location: str | None = None,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    time_zone: str | None = None,
    attendees: list[str] | None = None,
    recurrence: list[str] | None = None,
    reminders: dict | None = None,
    color_id: str | None = None,
    visibility: str | None = None,
    transparency: str | None = None,
    status: str | None = None,
    conference_data: dict | None = None,
    source: dict | None = None,
    extended_properties: dict | None = None,
    guests_can_modify: bool | None = None,
    guests_can_invite_others: bool | None = None,
    guests_can_see_other_guests: bool | None = None,
) -> dict:
    """Build an event resource body from keyword args."""
    body: dict = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location

    # Start / end — timed vs all-day
    if start_datetime is not None:
        s: dict = {"dateTime": start_datetime}
        if time_zone is not None:
            s["timeZone"] = time_zone
        body["start"] = s
    elif start_date is not None:
        body["start"] = {"date": start_date}

    if end_datetime is not None:
        e: dict = {"dateTime": end_datetime}
        if time_zone is not None:
            e["timeZone"] = time_zone
        body["end"] = e
    elif end_date is not None:
        body["end"] = {"date": end_date}

    if attendees is not None:
        body["attendees"] = [
            {"email": a} for a in attendees
        ]
    if recurrence is not None:
        body["recurrence"] = recurrence
    if reminders is not None:
        body["reminders"] = reminders
    if color_id is not None:
        body["colorId"] = color_id
    if visibility is not None:
        body["visibility"] = visibility
    if transparency is not None:
        body["transparency"] = transparency
    if status is not None:
        body["status"] = status
    if conference_data is not None:
        body["conferenceData"] = conference_data
    if source is not None:
        body["source"] = source
    if extended_properties is not None:
        body["extendedProperties"] = extended_properties
    if guests_can_modify is not None:
        body["guestsCanModify"] = guests_can_modify
    if guests_can_invite_others is not None:
        body["guestsCanInviteOthers"] = (
            guests_can_invite_others
        )
    if guests_can_see_other_guests is not None:
        body["guestsCanSeeOtherGuests"] = (
            guests_can_see_other_guests
        )
    return body


# -- registration -------------------------------------------


def register_tools(mcp: FastMCP) -> None:
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        logger.warning(
            "GOOGLE_SERVICE_ACCOUNT_JSON not set "
            "— Google Calendar tools will fail."
        )

    # ===================================================
    # TIER 1: CALENDAR LIST (5 tools)
    # ===================================================

    @mcp.tool()
    async def gcal_list_calendar_list(
        min_access_role: str | None = None,
        show_deleted: bool = False,
        show_hidden: bool = False,
        page_token: str | None = None,
        max_results: int = 100,
        sync_token: str | None = None,
    ) -> str:
        """List all calendars in the user's calendar list.
        Args:
            min_access_role: Filter by access role
                (freeBusyReader/owner/reader/writer)
            show_deleted: Include deleted entries
            show_hidden: Include hidden entries
            page_token: Pagination token
            max_results: Max results per page (default 100)
            sync_token: Incremental sync token
        """
        p: dict = {"maxResults": max_results}
        if min_access_role is not None:
            p["minAccessRole"] = min_access_role
        if show_deleted:
            p["showDeleted"] = "true"
        if show_hidden:
            p["showHidden"] = "true"
        if page_token is not None:
            p["pageToken"] = page_token
        if sync_token is not None:
            p["syncToken"] = sync_token
        data = await _req(
            "GET", "/users/me/calendarList", params=p
        )
        items = (
            data.get("items", [])
            if isinstance(data, dict)
            else data
        )
        npt = (
            data.get("nextPageToken")
            if isinstance(data, dict)
            else None
        )
        return _success(
            200,
            data=items,
            count=len(items),
            next_page_token=npt,
        )

    @mcp.tool()
    async def gcal_get_calendar_list_entry(
        calendar_id: str,
    ) -> str:
        """Get a specific calendar list entry.
        Args:
            calendar_id: Calendar ID to retrieve
        """
        data = await _req(
            "GET",
            f"/users/me/calendarList/{calendar_id}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_insert_calendar_list_entry(
        calendar_id: str,
        color_rgb_format: bool = False,
        background_color: str | None = None,
        foreground_color: str | None = None,
        color_id: str | None = None,
        hidden: bool | None = None,
        selected: bool | None = None,
        default_reminders: list[dict] | None = None,
        notification_settings: dict | None = None,
        summary_override: str | None = None,
    ) -> str:
        """Add an existing calendar to the user's list.
        Args:
            calendar_id: ID of the calendar to add
            color_rgb_format: Use RGB colors in response
            background_color: Background color hex
            foreground_color: Foreground color hex
            color_id: Color ID from gcal_get_colors
            hidden: Whether calendar is hidden
            selected: Whether calendar is selected
            default_reminders: Default reminders list
            notification_settings: Notification settings
            summary_override: Override display name
        """
        body: dict = {"id": calendar_id}
        if background_color is not None:
            body["backgroundColor"] = background_color
        if foreground_color is not None:
            body["foregroundColor"] = foreground_color
        if color_id is not None:
            body["colorId"] = color_id
        if hidden is not None:
            body["hidden"] = hidden
        if selected is not None:
            body["selected"] = selected
        if default_reminders is not None:
            body["defaultReminders"] = default_reminders
        if notification_settings is not None:
            body["notificationSettings"] = (
                notification_settings
            )
        if summary_override is not None:
            body["summaryOverride"] = summary_override
        p: dict = {}
        if color_rgb_format:
            p["colorRgbFormat"] = "true"
        data = await _req(
            "POST",
            "/users/me/calendarList",
            json_body=body,
            params=p or None,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_update_calendar_list_entry(
        calendar_id: str,
        color_rgb_format: bool = False,
        background_color: str | None = None,
        foreground_color: str | None = None,
        color_id: str | None = None,
        hidden: bool | None = None,
        selected: bool | None = None,
        default_reminders: list[dict] | None = None,
        notification_settings: dict | None = None,
        summary_override: str | None = None,
    ) -> str:
        """Update a calendar list entry (colors, etc.).
        Args:
            calendar_id: Calendar ID to update
            color_rgb_format: Use RGB colors in response
            background_color: Background color hex
            foreground_color: Foreground color hex
            color_id: Color ID from gcal_get_colors
            hidden: Whether calendar is hidden
            selected: Whether calendar is selected
            default_reminders: Default reminders list
            notification_settings: Notification settings
            summary_override: Override display name
        """
        body: dict = {}
        if background_color is not None:
            body["backgroundColor"] = background_color
        if foreground_color is not None:
            body["foregroundColor"] = foreground_color
        if color_id is not None:
            body["colorId"] = color_id
        if hidden is not None:
            body["hidden"] = hidden
        if selected is not None:
            body["selected"] = selected
        if default_reminders is not None:
            body["defaultReminders"] = default_reminders
        if notification_settings is not None:
            body["notificationSettings"] = (
                notification_settings
            )
        if summary_override is not None:
            body["summaryOverride"] = summary_override
        p: dict = {}
        if color_rgb_format:
            p["colorRgbFormat"] = "true"
        data = await _req(
            "PATCH",
            f"/users/me/calendarList/{calendar_id}",
            json_body=body,
            params=p or None,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_delete_calendar_list_entry(
        calendar_id: str,
    ) -> str:
        """Remove a calendar from the user's calendar list.
        Args:
            calendar_id: Calendar ID to remove
        """
        await _req(
            "DELETE",
            f"/users/me/calendarList/{calendar_id}",
        )
        return _success(
            204, message="Calendar list entry deleted."
        )

    # ===================================================
    # TIER 2: CALENDARS (5 tools)
    # ===================================================

    @mcp.tool()
    async def gcal_get_calendar(
        calendar_id: str | None = None,
    ) -> str:
        """Get calendar metadata.
        Args:
            calendar_id: Calendar ID (default: primary)
        """
        cid = _cid(calendar_id)
        data = await _req("GET", f"/calendars/{cid}")
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_create_calendar(
        summary: str,
        description: str | None = None,
        location: str | None = None,
        time_zone: str | None = None,
    ) -> str:
        """Create a new secondary calendar.
        Args:
            summary: Calendar title
            description: Calendar description
            location: Geographic location
            time_zone: IANA time zone (e.g. America/New_York)
        """
        body: dict = {"summary": summary}
        if description is not None:
            body["description"] = description
        if location is not None:
            body["location"] = location
        if time_zone is not None:
            body["timeZone"] = time_zone
        data = await _req(
            "POST", "/calendars", json_body=body
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_update_calendar(
        calendar_id: str | None = None,
        summary: str | None = None,
        description: str | None = None,
        location: str | None = None,
        time_zone: str | None = None,
    ) -> str:
        """Update calendar metadata (partial).
        Args:
            calendar_id: Calendar ID (default: primary)
            summary: Calendar title
            description: Calendar description
            location: Geographic location
            time_zone: IANA time zone
        """
        cid = _cid(calendar_id)
        body: dict = {}
        if summary is not None:
            body["summary"] = summary
        if description is not None:
            body["description"] = description
        if location is not None:
            body["location"] = location
        if time_zone is not None:
            body["timeZone"] = time_zone
        data = await _req(
            "PATCH",
            f"/calendars/{cid}",
            json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_delete_calendar(
        calendar_id: str,
    ) -> str:
        """Delete a secondary calendar.
        Args:
            calendar_id: Calendar ID to delete
                (cannot delete primary)
        """
        await _req("DELETE", f"/calendars/{calendar_id}")
        return _success(204, message="Calendar deleted.")

    @mcp.tool()
    async def gcal_clear_calendar(
        calendar_id: str | None = None,
    ) -> str:
        """Clear all events from a primary calendar.
        Args:
            calendar_id: Calendar ID (default: primary)
        """
        cid = _cid(calendar_id)
        await _req("POST", f"/calendars/{cid}/clear")
        return _success(
            204, message="Calendar cleared."
        )

    # ===================================================
    # TIER 3: EVENTS (9 tools)
    # ===================================================

    @mcp.tool()
    async def gcal_list_events(
        calendar_id: str | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        q: str | None = None,
        max_results: int = 250,
        order_by: str | None = None,
        single_events: bool = True,
        show_deleted: bool = False,
        show_hidden_invitations: bool = False,
        time_zone: str | None = None,
        page_token: str | None = None,
        sync_token: str | None = None,
        updated_min: str | None = None,
        i_cal_uid: str | None = None,
        private_extended_property: str | None = None,
        shared_extended_property: str | None = None,
    ) -> str:
        """List events with optional filters.
        Args:
            calendar_id: Calendar ID (default: primary)
            time_min: Lower bound (RFC 3339)
            time_max: Upper bound (RFC 3339)
            q: Free-text search
            max_results: Max events per page (default 250)
            order_by: startTime or updated
            single_events: Expand recurring (default true)
            show_deleted: Include cancelled events
            show_hidden_invitations: Show hidden invitations
            time_zone: Response time zone
            page_token: Pagination token
            sync_token: Incremental sync token
            updated_min: Lower bound on last modified
            i_cal_uid: Filter by iCalendar UID
            private_extended_property: Filter private prop
            shared_extended_property: Filter shared prop
        """
        cid = _cid(calendar_id)
        p: dict = {
            "maxResults": max_results,
            "singleEvents": str(single_events).lower(),
        }
        if time_min is not None:
            p["timeMin"] = time_min
        if time_max is not None:
            p["timeMax"] = time_max
        if q is not None:
            p["q"] = q
        if order_by is not None:
            p["orderBy"] = order_by
        if show_deleted:
            p["showDeleted"] = "true"
        if show_hidden_invitations:
            p["showHiddenInvitations"] = "true"
        if time_zone is not None:
            p["timeZone"] = time_zone
        if page_token is not None:
            p["pageToken"] = page_token
        if sync_token is not None:
            p["syncToken"] = sync_token
        if updated_min is not None:
            p["updatedMin"] = updated_min
        if i_cal_uid is not None:
            p["iCalUID"] = i_cal_uid
        if private_extended_property is not None:
            p["privateExtendedProperty"] = (
                private_extended_property
            )
        if shared_extended_property is not None:
            p["sharedExtendedProperty"] = (
                shared_extended_property
            )
        data = await _req(
            "GET",
            f"/calendars/{cid}/events",
            params=p,
        )
        items = (
            data.get("items", [])
            if isinstance(data, dict)
            else data
        )
        npt = (
            data.get("nextPageToken")
            if isinstance(data, dict)
            else None
        )
        return _success(
            200,
            data=items,
            count=len(items),
            next_page_token=npt,
        )

    @mcp.tool()
    async def gcal_get_event(
        event_id: str,
        calendar_id: str | None = None,
        time_zone: str | None = None,
        max_attendees: int | None = None,
    ) -> str:
        """Get a single event by ID.
        Args:
            event_id: Event ID
            calendar_id: Calendar ID (default: primary)
            time_zone: Response time zone
            max_attendees: Max attendees to include
        """
        cid = _cid(calendar_id)
        p: dict = {}
        if time_zone is not None:
            p["timeZone"] = time_zone
        if max_attendees is not None:
            p["maxAttendees"] = max_attendees
        data = await _req(
            "GET",
            f"/calendars/{cid}/events/{event_id}",
            params=p or None,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_create_event(
        summary: str,
        start_datetime: str | None = None,
        start_date: str | None = None,
        end_datetime: str | None = None,
        end_date: str | None = None,
        time_zone: str = "UTC",
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        recurrence: list[str] | None = None,
        reminders: dict | None = None,
        color_id: str | None = None,
        visibility: str | None = None,
        transparency: str | None = None,
        status: str | None = None,
        conference_data: dict | None = None,
        conference_data_version: int | None = None,
        source: dict | None = None,
        extended_properties: dict | None = None,
        guests_can_modify: bool | None = None,
        guests_can_invite_others: bool | None = None,
        guests_can_see_other_guests: bool | None = None,
        send_updates: str = "none",
        calendar_id: str | None = None,
    ) -> str:
        """Create a new calendar event.

        For timed events provide start_datetime + end_datetime
        (RFC 3339). For all-day events provide start_date +
        end_date (YYYY-MM-DD).

        Args:
            summary: Event title
            start_datetime: Start (RFC 3339) for timed events
            start_date: Start (YYYY-MM-DD) for all-day events
            end_datetime: End (RFC 3339) for timed events
            end_date: End (YYYY-MM-DD) for all-day events
            time_zone: IANA time zone (default UTC)
            description: Event description
            location: Location string
            attendees: List of attendee email addresses
            recurrence: RRULE strings list
            reminders: Reminders override dict
            color_id: Color ID from gcal_get_colors
            visibility: default/public/private/confidential
            transparency: opaque or transparent
            status: confirmed/tentative/cancelled
            conference_data: Conference data dict
            conference_data_version: 0 or 1 for conf support
            source: Source dict (url, title)
            extended_properties: Extended properties dict
            guests_can_modify: Allow guests to modify
            guests_can_invite_others: Allow guest invites
            guests_can_see_other_guests: Guest list visible
            send_updates: all/externalOnly/none (default none)
            calendar_id: Calendar ID (default: primary)
        """
        cid = _cid(calendar_id)
        body = _build_event_body(
            summary=summary,
            description=description,
            location=location,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            start_date=start_date,
            end_date=end_date,
            time_zone=time_zone,
            attendees=attendees,
            recurrence=recurrence,
            reminders=reminders,
            color_id=color_id,
            visibility=visibility,
            transparency=transparency,
            status=status,
            conference_data=conference_data,
            source=source,
            extended_properties=extended_properties,
            guests_can_modify=guests_can_modify,
            guests_can_invite_others=guests_can_invite_others,
            guests_can_see_other_guests=guests_can_see_other_guests,
        )
        p: dict = {"sendUpdates": send_updates}
        if conference_data_version is not None:
            p["conferenceDataVersion"] = (
                conference_data_version
            )
        data = await _req(
            "POST",
            f"/calendars/{cid}/events",
            json_body=body,
            params=p,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_update_event(
        event_id: str,
        calendar_id: str | None = None,
        summary: str | None = None,
        start_datetime: str | None = None,
        start_date: str | None = None,
        end_datetime: str | None = None,
        end_date: str | None = None,
        time_zone: str | None = None,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        recurrence: list[str] | None = None,
        reminders: dict | None = None,
        color_id: str | None = None,
        visibility: str | None = None,
        transparency: str | None = None,
        status: str | None = None,
        send_updates: str = "none",
        extended_properties: dict | None = None,
        guests_can_modify: bool | None = None,
        guests_can_invite_others: bool | None = None,
        guests_can_see_other_guests: bool | None = None,
    ) -> str:
        """Update event fields (PATCH — partial update).
        Args:
            event_id: Event ID
            calendar_id: Calendar ID (default: primary)
            summary: Event title
            start_datetime: Start (RFC 3339) for timed
            start_date: Start (YYYY-MM-DD) for all-day
            end_datetime: End (RFC 3339) for timed
            end_date: End (YYYY-MM-DD) for all-day
            time_zone: IANA time zone
            description: Event description
            location: Location string
            attendees: Full attendee email list (replaces)
            recurrence: RRULE strings list
            reminders: Reminders override dict
            color_id: Color ID
            visibility: default/public/private/confidential
            transparency: opaque or transparent
            status: confirmed/tentative/cancelled
            send_updates: all/externalOnly/none (default none)
            extended_properties: Extended properties dict
            guests_can_modify: Allow guests to modify
            guests_can_invite_others: Allow guest invites
            guests_can_see_other_guests: Guest list visible
        """
        cid = _cid(calendar_id)
        body = _build_event_body(
            summary=summary,
            description=description,
            location=location,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            start_date=start_date,
            end_date=end_date,
            time_zone=time_zone,
            attendees=attendees,
            recurrence=recurrence,
            reminders=reminders,
            color_id=color_id,
            visibility=visibility,
            transparency=transparency,
            status=status,
            extended_properties=extended_properties,
            guests_can_modify=guests_can_modify,
            guests_can_invite_others=guests_can_invite_others,
            guests_can_see_other_guests=guests_can_see_other_guests,
        )
        p: dict = {"sendUpdates": send_updates}
        data = await _req(
            "PATCH",
            f"/calendars/{cid}/events/{event_id}",
            json_body=body,
            params=p,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_delete_event(
        event_id: str,
        calendar_id: str | None = None,
        send_updates: str = "none",
    ) -> str:
        """Delete an event.
        Args:
            event_id: Event ID
            calendar_id: Calendar ID (default: primary)
            send_updates: all/externalOnly/none (default none)
        """
        cid = _cid(calendar_id)
        p: dict = {"sendUpdates": send_updates}
        await _req(
            "DELETE",
            f"/calendars/{cid}/events/{event_id}",
            params=p,
        )
        return _success(204, message="Event deleted.")

    @mcp.tool()
    async def gcal_quick_add_event(
        text: str,
        calendar_id: str | None = None,
        send_updates: str = "none",
    ) -> str:
        """Create event from natural language text.
        Args:
            text: Natural language event description
                (e.g. "Lunch with Bob tomorrow at noon")
            calendar_id: Calendar ID (default: primary)
            send_updates: all/externalOnly/none (default none)
        """
        cid = _cid(calendar_id)
        p: dict = {
            "text": text,
            "sendUpdates": send_updates,
        }
        data = await _req(
            "POST",
            f"/calendars/{cid}/events/quickAdd",
            params=p,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_move_event(
        event_id: str,
        destination_calendar_id: str,
        calendar_id: str | None = None,
        send_updates: str = "none",
    ) -> str:
        """Move an event to another calendar.
        Args:
            event_id: Event ID to move
            destination_calendar_id: Target calendar ID
            calendar_id: Source calendar ID (default: primary)
            send_updates: all/externalOnly/none (default none)
        """
        cid = _cid(calendar_id)
        p: dict = {
            "destination": destination_calendar_id,
            "sendUpdates": send_updates,
        }
        data = await _req(
            "POST",
            f"/calendars/{cid}/events/{event_id}/move",
            params=p,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_import_event(
        i_cal_uid: str,
        summary: str,
        start_datetime: str | None = None,
        start_date: str | None = None,
        end_datetime: str | None = None,
        end_date: str | None = None,
        time_zone: str = "UTC",
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        status: str | None = None,
        organizer: dict | None = None,
        calendar_id: str | None = None,
    ) -> str:
        """Import an event (iCalendar UID-based, idempotent).
        Args:
            i_cal_uid: iCalendar UID for deduplication
            summary: Event title
            start_datetime: Start (RFC 3339) for timed
            start_date: Start (YYYY-MM-DD) for all-day
            end_datetime: End (RFC 3339) for timed
            end_date: End (YYYY-MM-DD) for all-day
            time_zone: IANA time zone (default UTC)
            description: Event description
            location: Location string
            attendees: Attendee email addresses
            status: confirmed/tentative/cancelled
            organizer: Organizer dict (email, displayName)
            calendar_id: Calendar ID (default: primary)
        """
        cid = _cid(calendar_id)
        body = _build_event_body(
            summary=summary,
            description=description,
            location=location,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            start_date=start_date,
            end_date=end_date,
            time_zone=time_zone,
            attendees=attendees,
            status=status,
        )
        body["iCalUID"] = i_cal_uid
        if organizer is not None:
            body["organizer"] = organizer
        data = await _req(
            "POST",
            f"/calendars/{cid}/events/import",
            json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_list_event_instances(
        event_id: str,
        calendar_id: str | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 25,
        page_token: str | None = None,
        time_zone: str | None = None,
        show_deleted: bool = False,
    ) -> str:
        """List instances of a recurring event.
        Args:
            event_id: Recurring event ID
            calendar_id: Calendar ID (default: primary)
            time_min: Lower bound (RFC 3339)
            time_max: Upper bound (RFC 3339)
            max_results: Max per page (default 25)
            page_token: Pagination token
            time_zone: Response time zone
            show_deleted: Include cancelled instances
        """
        cid = _cid(calendar_id)
        p: dict = {"maxResults": max_results}
        if time_min is not None:
            p["timeMin"] = time_min
        if time_max is not None:
            p["timeMax"] = time_max
        if page_token is not None:
            p["pageToken"] = page_token
        if time_zone is not None:
            p["timeZone"] = time_zone
        if show_deleted:
            p["showDeleted"] = "true"
        data = await _req(
            "GET",
            f"/calendars/{cid}/events/{event_id}/instances",
            params=p,
        )
        items = (
            data.get("items", [])
            if isinstance(data, dict)
            else data
        )
        npt = (
            data.get("nextPageToken")
            if isinstance(data, dict)
            else None
        )
        return _success(
            200,
            data=items,
            count=len(items),
            next_page_token=npt,
        )

    # ===================================================
    # TIER 4: ATTENDEES (3 tools)
    # ===================================================

    @mcp.tool()
    async def gcal_add_attendees(
        event_id: str,
        attendee_emails: list[str],
        calendar_id: str | None = None,
        send_updates: str = "all",
    ) -> str:
        """Add attendees to an existing event.
        Args:
            event_id: Event ID
            attendee_emails: Email addresses to add
            calendar_id: Calendar ID (default: primary)
            send_updates: all/externalOnly/none (default all)
        """
        cid = _cid(calendar_id)
        # Fetch current event to get existing attendees
        event = await _req(
            "GET",
            f"/calendars/{cid}/events/{event_id}",
        )
        current: list[dict] = []
        if isinstance(event, dict):
            current = event.get("attendees", [])
        existing_emails = {
            a.get("email", "").lower() for a in current
        }
        for email in attendee_emails:
            if email.lower() not in existing_emails:
                current.append({"email": email})
        body: dict = {"attendees": current}
        p: dict = {"sendUpdates": send_updates}
        data = await _req(
            "PATCH",
            f"/calendars/{cid}/events/{event_id}",
            json_body=body,
            params=p,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_remove_attendees(
        event_id: str,
        attendee_emails: list[str],
        calendar_id: str | None = None,
        send_updates: str = "all",
    ) -> str:
        """Remove attendees from an event.
        Args:
            event_id: Event ID
            attendee_emails: Email addresses to remove
            calendar_id: Calendar ID (default: primary)
            send_updates: all/externalOnly/none (default all)
        """
        cid = _cid(calendar_id)
        event = await _req(
            "GET",
            f"/calendars/{cid}/events/{event_id}",
        )
        current: list[dict] = []
        if isinstance(event, dict):
            current = event.get("attendees", [])
        remove_set = {e.lower() for e in attendee_emails}
        filtered = [
            a
            for a in current
            if a.get("email", "").lower() not in remove_set
        ]
        body: dict = {"attendees": filtered}
        p: dict = {"sendUpdates": send_updates}
        data = await _req(
            "PATCH",
            f"/calendars/{cid}/events/{event_id}",
            json_body=body,
            params=p,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_set_attendee_response(
        event_id: str,
        attendee_email: str,
        response_status: str,
        calendar_id: str | None = None,
        send_updates: str = "none",
    ) -> str:
        """Set RSVP response status for an attendee.
        Args:
            event_id: Event ID
            attendee_email: Attendee email address
            response_status: needsAction/declined/
                tentative/accepted
            calendar_id: Calendar ID (default: primary)
            send_updates: all/externalOnly/none (default none)
        """
        cid = _cid(calendar_id)
        event = await _req(
            "GET",
            f"/calendars/{cid}/events/{event_id}",
        )
        current: list[dict] = []
        if isinstance(event, dict):
            current = event.get("attendees", [])
        found = False
        target = attendee_email.lower()
        for attendee in current:
            if attendee.get("email", "").lower() == target:
                attendee["responseStatus"] = response_status
                found = True
                break
        if not found:
            raise ToolError(
                f"Attendee {attendee_email} not found "
                f"on event {event_id}."
            )
        body: dict = {"attendees": current}
        p: dict = {"sendUpdates": send_updates}
        data = await _req(
            "PATCH",
            f"/calendars/{cid}/events/{event_id}",
            json_body=body,
            params=p,
        )
        return _success(200, data=data)

    # ===================================================
    # TIER 5: FREEBUSY (1 tool)
    # ===================================================

    @mcp.tool()
    async def gcal_freebusy_query(
        time_min: str,
        time_max: str,
        items: list[str],
        time_zone: str | None = None,
        calendar_expansion_max: int | None = None,
        group_expansion_max: int | None = None,
    ) -> str:
        """Query free/busy info for calendars.
        Args:
            time_min: Start of window (RFC 3339)
            time_max: End of window (RFC 3339)
            items: Calendar IDs to query
            time_zone: Time zone for the response
            calendar_expansion_max: Max calendars in group
                expansion (1-50)
            group_expansion_max: Max members in group
                expansion (1-100)
        """
        body: dict = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": i} for i in items],
        }
        if time_zone is not None:
            body["timeZone"] = time_zone
        if calendar_expansion_max is not None:
            body["calendarExpansionMax"] = (
                calendar_expansion_max
            )
        if group_expansion_max is not None:
            body["groupExpansionMax"] = group_expansion_max
        data = await _req(
            "POST", "/freeBusy", json_body=body
        )
        return _success(200, data=data)

    # ===================================================
    # TIER 6: ACLs (5 tools)
    # ===================================================

    @mcp.tool()
    async def gcal_list_acl(
        calendar_id: str | None = None,
        page_token: str | None = None,
        max_results: int | None = None,
        show_deleted: bool = False,
        sync_token: str | None = None,
    ) -> str:
        """List ACL rules for a calendar.
        Args:
            calendar_id: Calendar ID (default: primary)
            page_token: Pagination token
            max_results: Max results per page
            show_deleted: Include deleted rules
            sync_token: Incremental sync token
        """
        cid = _cid(calendar_id)
        p: dict = {}
        if max_results is not None:
            p["maxResults"] = max_results
        if page_token is not None:
            p["pageToken"] = page_token
        if show_deleted:
            p["showDeleted"] = "true"
        if sync_token is not None:
            p["syncToken"] = sync_token
        data = await _req(
            "GET",
            f"/calendars/{cid}/acl",
            params=p or None,
        )
        items = (
            data.get("items", [])
            if isinstance(data, dict)
            else data
        )
        npt = (
            data.get("nextPageToken")
            if isinstance(data, dict)
            else None
        )
        return _success(
            200,
            data=items,
            count=len(items),
            next_page_token=npt,
        )

    @mcp.tool()
    async def gcal_get_acl_rule(
        rule_id: str,
        calendar_id: str | None = None,
    ) -> str:
        """Get a specific ACL rule.
        Args:
            rule_id: Rule ID (e.g. user:email@example.com)
            calendar_id: Calendar ID (default: primary)
        """
        cid = _cid(calendar_id)
        data = await _req(
            "GET", f"/calendars/{cid}/acl/{rule_id}"
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_insert_acl_rule(
        role: str,
        scope_type: str,
        scope_value: str | None = None,
        calendar_id: str | None = None,
        send_notifications: bool = True,
    ) -> str:
        """Create an ACL rule (share a calendar).
        Args:
            role: Permission level
                (none/freeBusyReader/reader/writer/owner)
            scope_type: Scope type
                (default/user/group/domain)
            scope_value: Email or domain (required unless
                scope_type is default)
            calendar_id: Calendar ID (default: primary)
            send_notifications: Send sharing notification
        """
        cid = _cid(calendar_id)
        scope: dict = {"type": scope_type}
        if scope_value is not None:
            scope["value"] = scope_value
        body: dict = {"role": role, "scope": scope}
        p: dict = {}
        if not send_notifications:
            p["sendNotifications"] = "false"
        data = await _req(
            "POST",
            f"/calendars/{cid}/acl",
            json_body=body,
            params=p or None,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_update_acl_rule(
        rule_id: str,
        role: str,
        calendar_id: str | None = None,
        send_notifications: bool = True,
    ) -> str:
        """Update an ACL rule's role.
        Args:
            rule_id: Rule ID to update
            role: New role
                (none/freeBusyReader/reader/writer/owner)
            calendar_id: Calendar ID (default: primary)
            send_notifications: Send sharing notification
        """
        cid = _cid(calendar_id)
        body: dict = {"role": role}
        p: dict = {}
        if not send_notifications:
            p["sendNotifications"] = "false"
        data = await _req(
            "PATCH",
            f"/calendars/{cid}/acl/{rule_id}",
            json_body=body,
            params=p or None,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_delete_acl_rule(
        rule_id: str,
        calendar_id: str | None = None,
    ) -> str:
        """Delete an ACL rule (revoke access).
        Args:
            rule_id: Rule ID to delete
            calendar_id: Calendar ID (default: primary)
        """
        cid = _cid(calendar_id)
        await _req(
            "DELETE", f"/calendars/{cid}/acl/{rule_id}"
        )
        return _success(204, message="ACL rule deleted.")

    # ===================================================
    # TIER 7: SETTINGS (2 tools)
    # ===================================================

    @mcp.tool()
    async def gcal_list_settings(
        page_token: str | None = None,
        max_results: int | None = None,
        sync_token: str | None = None,
    ) -> str:
        """List all user calendar settings (read-only).
        Args:
            page_token: Pagination token
            max_results: Max results per page
            sync_token: Incremental sync token
        """
        p: dict = {}
        if max_results is not None:
            p["maxResults"] = max_results
        if page_token is not None:
            p["pageToken"] = page_token
        if sync_token is not None:
            p["syncToken"] = sync_token
        data = await _req(
            "GET",
            "/users/me/settings",
            params=p or None,
        )
        items = (
            data.get("items", [])
            if isinstance(data, dict)
            else data
        )
        npt = (
            data.get("nextPageToken")
            if isinstance(data, dict)
            else None
        )
        return _success(
            200,
            data=items,
            count=len(items),
            next_page_token=npt,
        )

    @mcp.tool()
    async def gcal_get_setting(
        setting_id: str,
    ) -> str:
        """Get a specific calendar setting value.
        Args:
            setting_id: Setting key (e.g. timezone,
                locale, dateFieldOrder, weekStart)
        """
        data = await _req(
            "GET",
            f"/users/me/settings/{setting_id}",
        )
        return _success(200, data=data)

    # ===================================================
    # TIER 8: COLORS (1 tool)
    # ===================================================

    @mcp.tool()
    async def gcal_get_colors() -> str:
        """Get available calendar and event color defs.

        Returns color IDs mapped to background/foreground
        hex values for both calendar and event colors.
        """
        data = await _req("GET", "/colors")
        return _success(200, data=data)

    # ===================================================
    # TIER 9-11: CHANNELS / WATCH (3 tools)
    # ===================================================

    @mcp.tool()
    async def gcal_watch_events(
        channel_id: str,
        address: str,
        calendar_id: str | None = None,
        channel_type: str = "web_hook",
        token: str | None = None,
        expiration: int | None = None,
        params: dict | None = None,
    ) -> str:
        """Subscribe to push notifications for events.

        Requires a publicly accessible HTTPS callback URL.

        Args:
            channel_id: Unique channel UUID
            address: HTTPS callback URL
            calendar_id: Calendar ID (default: primary)
            channel_type: Channel type (default web_hook)
            token: Optional verification token
            expiration: Channel expiry (Unix ms timestamp)
            params: Optional params dict (e.g. {"ttl":"3600"})
        """
        cid = _cid(calendar_id)
        body: dict = {
            "id": channel_id,
            "type": channel_type,
            "address": address,
        }
        if token is not None:
            body["token"] = token
        if expiration is not None:
            body["expiration"] = expiration
        if params is not None:
            body["params"] = params
        data = await _req(
            "POST",
            f"/calendars/{cid}/events/watch",
            json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_watch_calendar_list(
        channel_id: str,
        address: str,
        channel_type: str = "web_hook",
        token: str | None = None,
        expiration: int | None = None,
        params: dict | None = None,
    ) -> str:
        """Subscribe to push notifications for calendar list.

        Requires a publicly accessible HTTPS callback URL.

        Args:
            channel_id: Unique channel UUID
            address: HTTPS callback URL
            channel_type: Channel type (default web_hook)
            token: Optional verification token
            expiration: Channel expiry (Unix ms timestamp)
            params: Optional params dict
        """
        body: dict = {
            "id": channel_id,
            "type": channel_type,
            "address": address,
        }
        if token is not None:
            body["token"] = token
        if expiration is not None:
            body["expiration"] = expiration
        if params is not None:
            body["params"] = params
        data = await _req(
            "POST",
            "/users/me/calendarList/watch",
            json_body=body,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def gcal_stop_channel(
        channel_id: str,
        resource_id: str,
    ) -> str:
        """Stop receiving push notifications for a channel.
        Args:
            channel_id: Channel ID to stop
            resource_id: Resource ID from watch response
        """
        body: dict = {
            "id": channel_id,
            "resourceId": resource_id,
        }
        await _req(
            "POST", "/channels/stop", json_body=body
        )
        return _success(
            204, message="Channel stopped."
        )
