"""Tests for Microsoft Graph Calendar tool integration."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.calendar_tool import register_tools

GRAPH = "https://graph.microsoft.com/v1.0"
U = "user@example.com"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_msal = MagicMock()
    mock_msal.acquire_token_for_client.return_value = {"access_token": "t"}
    with patch("mcp_toolbox.tools.calendar_tool.O365_TENANT_ID", "t"), \
         patch("mcp_toolbox.tools.calendar_tool.O365_CLIENT_ID", "c"), \
         patch("mcp_toolbox.tools.calendar_tool.O365_CLIENT_SECRET", "s"), \
         patch("mcp_toolbox.tools.calendar_tool.O365_USER_ID", U), \
         patch("mcp_toolbox.tools.calendar_tool._msal_app", mock_msal), \
         patch("mcp_toolbox.tools.calendar_tool._http_client", None):
        register_tools(mcp)
        yield mcp


# --- Auth ---

@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    mock_msal = MagicMock()
    mock_msal.acquire_token_for_client.return_value = {"access_token": "t"}
    with patch("mcp_toolbox.tools.calendar_tool.O365_TENANT_ID", None), \
         patch("mcp_toolbox.tools.calendar_tool.O365_CLIENT_ID", None), \
         patch("mcp_toolbox.tools.calendar_tool.O365_CLIENT_SECRET", None), \
         patch("mcp_toolbox.tools.calendar_tool.O365_USER_ID", U), \
         patch("mcp_toolbox.tools.calendar_tool._msal_app", None), \
         patch("mcp_toolbox.tools.calendar_tool._http_client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="O365 credentials"):
            await mcp.call_tool("calendar_list_calendars", {})


@pytest.mark.asyncio
@respx.mock
async def test_api_error_429(server):
    respx.get(f"{GRAPH}/users/{U}/calendars").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "5"})
    )
    with pytest.raises(Exception, match="Rate limit"):
        await server.call_tool("calendar_list_calendars", {})


# --- Calendar Management ---

@pytest.mark.asyncio
@respx.mock
async def test_list_calendars(server):
    respx.get(f"{GRAPH}/users/{U}/calendars").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "c1"}]})
    )
    assert _r(await server.call_tool("calendar_list_calendars", {}))["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_calendar(server):
    respx.get(f"{GRAPH}/users/{U}/calendars/c1").mock(
        return_value=httpx.Response(200, json={"id": "c1"})
    )
    assert _r(await server.call_tool("calendar_get_calendar", {
        "calendar_id": "c1",
    }))["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_create_calendar(server):
    route = respx.post(f"{GRAPH}/users/{U}/calendars").mock(
        return_value=httpx.Response(201, json={"id": "c_new"})
    )
    assert _r(await server.call_tool("calendar_create_calendar", {
        "name": "Work",
    }))["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["name"] == "Work"


@pytest.mark.asyncio
@respx.mock
async def test_delete_calendar(server):
    respx.delete(f"{GRAPH}/users/{U}/calendars/c1").mock(
        return_value=httpx.Response(204)
    )
    assert _r(await server.call_tool("calendar_delete_calendar", {
        "calendar_id": "c1",
    }))["status"] == "success"


# --- Event CRUD ---

@pytest.mark.asyncio
@respx.mock
async def test_create_event(server):
    route = respx.post(f"{GRAPH}/users/{U}/calendar/events").mock(
        return_value=httpx.Response(201, json={"id": "e1"})
    )
    assert _r(await server.call_tool("calendar_create_event", {
        "subject": "Standup",
        "start_datetime": "2026-04-15T09:00:00",
        "end_datetime": "2026-04-15T09:30:00",
    }))["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["subject"] == "Standup"
    assert body["start"] == {"dateTime": "2026-04-15T09:00:00", "timeZone": "UTC"}
    assert body["end"] == {"dateTime": "2026-04-15T09:30:00", "timeZone": "UTC"}
    assert body["isAllDay"] is False
    assert body["isOnlineMeeting"] is False


@pytest.mark.asyncio
@respx.mock
async def test_get_event(server):
    respx.get(f"{GRAPH}/users/{U}/events/e1").mock(
        return_value=httpx.Response(200, json={"id": "e1"})
    )
    assert _r(await server.call_tool("calendar_get_event", {
        "event_id": "e1",
    }))["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_update_event(server):
    route = respx.patch(f"{GRAPH}/users/{U}/events/e1").mock(
        return_value=httpx.Response(200, json={"id": "e1"})
    )
    assert _r(await server.call_tool("calendar_update_event", {
        "event_id": "e1", "subject": "Updated",
    }))["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["subject"] == "Updated"


@pytest.mark.asyncio
@respx.mock
async def test_delete_event(server):
    respx.delete(f"{GRAPH}/users/{U}/events/e1").mock(
        return_value=httpx.Response(204)
    )
    assert _r(await server.call_tool("calendar_delete_event", {
        "event_id": "e1",
    }))["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_events(server):
    respx.get(f"{GRAPH}/users/{U}/calendarView").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "e1"}]})
    )
    assert _r(await server.call_tool("calendar_list_events", {
        "start_datetime": "2026-04-01T00:00:00",
        "end_datetime": "2026-04-30T23:59:59",
    }))["count"] == 1


# --- Event Responses ---

@pytest.mark.asyncio
@respx.mock
async def test_accept_event(server):
    route = respx.post(f"{GRAPH}/users/{U}/events/e1/accept").mock(
        return_value=httpx.Response(202)
    )
    assert _r(await server.call_tool("calendar_accept_event", {
        "event_id": "e1",
    }))["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["sendResponse"] is True


@pytest.mark.asyncio
@respx.mock
async def test_decline_event(server):
    route = respx.post(f"{GRAPH}/users/{U}/events/e1/decline").mock(
        return_value=httpx.Response(202)
    )
    assert _r(await server.call_tool("calendar_decline_event", {
        "event_id": "e1",
    }))["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["sendResponse"] is True


@pytest.mark.asyncio
@respx.mock
async def test_tentatively_accept_event(server):
    route = respx.post(f"{GRAPH}/users/{U}/events/e1/tentativelyAccept").mock(
        return_value=httpx.Response(202)
    )
    assert _r(await server.call_tool("calendar_tentatively_accept_event", {
        "event_id": "e1",
    }))["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["sendResponse"] is True


# --- Scheduling ---

@pytest.mark.asyncio
@respx.mock
async def test_get_schedule(server):
    route = respx.post(f"{GRAPH}/users/{U}/calendar/getSchedule").mock(
        return_value=httpx.Response(200, json={"value": [{"scheduleId": "u1"}]})
    )
    assert _r(await server.call_tool("calendar_get_schedule", {
        "schedules": "u1@example.com",
        "start_datetime": "2026-04-15T08:00:00",
        "end_datetime": "2026-04-15T18:00:00",
    }))["count"] == 1
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["schedules"] == ["u1@example.com"]
    assert body["startTime"] == {"dateTime": "2026-04-15T08:00:00", "timeZone": "UTC"}
    assert body["endTime"] == {"dateTime": "2026-04-15T18:00:00", "timeZone": "UTC"}
    assert body["availabilityViewInterval"] == 30


@pytest.mark.asyncio
@respx.mock
async def test_find_meeting_times(server):
    route = respx.post(f"{GRAPH}/users/{U}/findMeetingTimes").mock(
        return_value=httpx.Response(200, json={
            "meetingTimeSuggestions": [{"confidence": 100}],
        })
    )
    assert _r(await server.call_tool("calendar_find_meeting_times", {
        "attendees": [{"emailAddress": {"address": "a@e.com"}}],
    }))["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["attendees"] == [{"emailAddress": {"address": "a@e.com"}}]


# --- Recurring Events ---

@pytest.mark.asyncio
@respx.mock
async def test_list_event_instances(server):
    respx.get(f"{GRAPH}/users/{U}/events/e1/instances").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "i1"}]})
    )
    assert _r(await server.call_tool("calendar_list_event_instances", {
        "event_id": "e1",
        "start_datetime": "2026-04-01",
        "end_datetime": "2026-04-30",
    }))["count"] == 1


# --- Event Actions ---

@pytest.mark.asyncio
@respx.mock
async def test_forward_event(server):
    route = respx.post(f"{GRAPH}/users/{U}/events/e1/forward").mock(
        return_value=httpx.Response(202)
    )
    assert _r(await server.call_tool("calendar_forward_event", {
        "event_id": "e1", "to": "other@example.com",
    }))["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["toRecipients"] == [
        {"emailAddress": {"address": "other@example.com"}}
    ]


@pytest.mark.asyncio
@respx.mock
async def test_cancel_event(server):
    route = respx.post(f"{GRAPH}/users/{U}/events/e1/cancel").mock(
        return_value=httpx.Response(202)
    )
    assert _r(await server.call_tool("calendar_cancel_event", {
        "event_id": "e1",
    }))["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body == {}


# --- Event Attachments ---

@pytest.mark.asyncio
@respx.mock
async def test_add_event_attachment(server, tmp_path):
    test_file = tmp_path / "agenda.pdf"
    test_file.write_bytes(b"PDF content")
    route = respx.post(f"{GRAPH}/users/{U}/events/e1/attachments").mock(
        return_value=httpx.Response(201, json={"id": "att1"})
    )
    assert _r(await server.call_tool("calendar_add_event_attachment", {
        "event_id": "e1", "file_path": str(test_file),
    }))["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert body["name"] == "agenda.pdf"
    assert body["contentType"] == "application/octet-stream"
    assert "contentBytes" in body


@pytest.mark.asyncio
@respx.mock
async def test_list_event_attachments(server):
    respx.get(f"{GRAPH}/users/{U}/events/e1/attachments").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "att1"}]})
    )
    assert _r(await server.call_tool("calendar_list_event_attachments", {
        "event_id": "e1",
    }))["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_event_attachment(server):
    respx.get(f"{GRAPH}/users/{U}/events/e1/attachments/att1").mock(
        return_value=httpx.Response(200, json={"id": "att1"})
    )
    assert _r(await server.call_tool("calendar_get_event_attachment", {
        "event_id": "e1", "attachment_id": "att1",
    }))["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_delete_event_attachment(server):
    respx.delete(f"{GRAPH}/users/{U}/events/e1/attachments/att1").mock(
        return_value=httpx.Response(204)
    )
    assert _r(await server.call_tool("calendar_delete_event_attachment", {
        "event_id": "e1", "attachment_id": "att1",
    }))["status"] == "success"


# --- Event Reminders ---

@pytest.mark.asyncio
@respx.mock
async def test_snooze_reminder(server):
    route = respx.post(f"{GRAPH}/users/{U}/events/e1/snoozeReminder").mock(
        return_value=httpx.Response(200, json={})
    )
    assert _r(await server.call_tool("calendar_snooze_reminder", {
        "event_id": "e1", "new_reminder_time": "2026-04-15T08:45:00",
    }))["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["newReminderTime"] == {
        "dateTime": "2026-04-15T08:45:00", "timeZone": "UTC",
    }


@pytest.mark.asyncio
@respx.mock
async def test_dismiss_reminder(server):
    respx.post(f"{GRAPH}/users/{U}/events/e1/dismissReminder").mock(
        return_value=httpx.Response(200, json={})
    )
    assert _r(await server.call_tool("calendar_dismiss_reminder", {
        "event_id": "e1",
    }))["status"] == "success"
