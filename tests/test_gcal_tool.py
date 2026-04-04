"""Tests for Google Calendar tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.gcal_tool import register_tools

BASE = "https://www.googleapis.com/calendar/v3"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


def _ok(result) -> None:
    assert _r(result)["status"] == "success"


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_creds = type("C", (), {
        "valid": True, "token": "tok",
        "refresh": lambda self, r: None,
    })()
    with patch(
        "mcp_toolbox.tools.gcal_tool.GOOGLE_SERVICE_ACCOUNT_JSON",
        "/fake/key.json",
    ), patch(
        "mcp_toolbox.tools.gcal_tool.GCAL_DEFAULT_CALENDAR_ID",
        "cal1",
    ), patch(
        "mcp_toolbox.tools.gcal_tool._credentials", mock_creds,
    ), patch(
        "mcp_toolbox.tools.gcal_tool._client", None,
    ):
        register_tools(mcp)
        yield mcp


# --- Auth/Error ---


@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with patch(
        "mcp_toolbox.tools.gcal_tool.GOOGLE_SERVICE_ACCOUNT_JSON",
        None,
    ), patch(
        "mcp_toolbox.tools.gcal_tool.GCAL_DEFAULT_CALENDAR_ID",
        None,
    ), patch(
        "mcp_toolbox.tools.gcal_tool._credentials", None,
    ), patch(
        "mcp_toolbox.tools.gcal_tool._client", None,
    ):
        register_tools(mcp)
        with pytest.raises(
            Exception, match="GOOGLE_SERVICE_ACCOUNT_JSON"
        ):
            await mcp.call_tool(
                "gcal_list_calendar_list", {},
            )


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit(server):
    respx.get(f"{BASE}/users/me/calendarList").mock(
        return_value=httpx.Response(429),
    )
    with pytest.raises(Exception, match="rate limit"):
        await server.call_tool(
            "gcal_list_calendar_list", {},
        )


# --- Calendar List (5 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_calendar_list(server):
    respx.get(f"{BASE}/users/me/calendarList").mock(
        return_value=httpx.Response(200, json={
            "items": [{"id": "c1", "summary": "My Cal"}],
        }),
    )
    r = _r(await server.call_tool(
        "gcal_list_calendar_list", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_calendar_list_entry(server):
    respx.get(
        f"{BASE}/users/me/calendarList/c1",
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "c1"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_get_calendar_list_entry",
        {"calendar_id": "c1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_insert_calendar_list_entry(server):
    respx.post(f"{BASE}/users/me/calendarList").mock(
        return_value=httpx.Response(
            200, json={"id": "c2"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_insert_calendar_list_entry",
        {"calendar_id": "c2"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_calendar_list_entry(server):
    respx.patch(
        f"{BASE}/users/me/calendarList/c1",
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "c1"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_update_calendar_list_entry",
        {"calendar_id": "c1", "color_id": "3"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_calendar_list_entry(server):
    respx.delete(
        f"{BASE}/users/me/calendarList/c1",
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gcal_delete_calendar_list_entry",
        {"calendar_id": "c1"},
    ))


# --- Calendars (5 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_get_calendar(server):
    respx.get(f"{BASE}/calendars/cal1").mock(
        return_value=httpx.Response(
            200, json={"id": "cal1"},
        ),
    )
    _ok(await server.call_tool("gcal_get_calendar", {}))


@pytest.mark.asyncio
@respx.mock
async def test_create_calendar(server):
    respx.post(f"{BASE}/calendars").mock(
        return_value=httpx.Response(
            200, json={"id": "new1", "summary": "Work"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_create_calendar", {"summary": "Work"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_calendar(server):
    respx.patch(f"{BASE}/calendars/cal1").mock(
        return_value=httpx.Response(
            200, json={"id": "cal1"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_update_calendar",
        {"summary": "Updated Cal"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_calendar(server):
    respx.delete(f"{BASE}/calendars/c2").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gcal_delete_calendar", {"calendar_id": "c2"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_clear_calendar(server):
    respx.post(f"{BASE}/calendars/cal1/clear").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gcal_clear_calendar", {},
    ))


# --- Events (9 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_events(server):
    respx.get(f"{BASE}/calendars/cal1/events").mock(
        return_value=httpx.Response(200, json={
            "items": [{"id": "e1", "summary": "Mtg"}],
        }),
    )
    r = _r(await server.call_tool(
        "gcal_list_events", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_event(server):
    respx.get(
        f"{BASE}/calendars/cal1/events/e1",
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "e1"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_get_event", {"event_id": "e1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_create_event(server):
    respx.post(f"{BASE}/calendars/cal1/events").mock(
        return_value=httpx.Response(
            200, json={"id": "e2"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_create_event", {
            "summary": "Lunch",
            "start_datetime": "2026-04-05T12:00:00Z",
            "end_datetime": "2026-04-05T13:00:00Z",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_event(server):
    respx.patch(
        f"{BASE}/calendars/cal1/events/e1",
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "e1"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_update_event", {
            "event_id": "e1",
            "summary": "Updated Lunch",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_event(server):
    respx.delete(
        f"{BASE}/calendars/cal1/events/e1",
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gcal_delete_event", {"event_id": "e1"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_quick_add_event(server):
    respx.post(
        f"{BASE}/calendars/cal1/events/quickAdd",
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "e3", "summary": "Lunch"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_quick_add_event",
        {"text": "Lunch tomorrow at noon"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_move_event(server):
    respx.post(
        f"{BASE}/calendars/cal1/events/e1/move",
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "e1"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_move_event", {
            "event_id": "e1",
            "destination_calendar_id": "cal2",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_import_event(server):
    respx.post(
        f"{BASE}/calendars/cal1/events/import",
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "e4"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_import_event", {
            "i_cal_uid": "uid-123@example.com",
            "summary": "Imported Event",
            "start_datetime": "2026-04-05T10:00:00Z",
            "end_datetime": "2026-04-05T11:00:00Z",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_list_event_instances(server):
    respx.get(
        f"{BASE}/calendars/cal1/events/e1/instances",
    ).mock(
        return_value=httpx.Response(200, json={
            "items": [
                {"id": "e1_20260405"},
                {"id": "e1_20260412"},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gcal_list_event_instances",
        {"event_id": "e1"},
    ))
    assert r["count"] == 2


# --- Attendees (3 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_add_attendees(server):
    respx.get(
        f"{BASE}/calendars/cal1/events/e1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "e1",
            "attendees": [
                {"email": "a@test.com"},
            ],
        }),
    )
    respx.patch(
        f"{BASE}/calendars/cal1/events/e1",
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "e1"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_add_attendees", {
            "event_id": "e1",
            "attendee_emails": ["b@test.com"],
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_remove_attendees(server):
    respx.get(
        f"{BASE}/calendars/cal1/events/e1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "e1",
            "attendees": [
                {"email": "a@test.com"},
                {"email": "b@test.com"},
            ],
        }),
    )
    respx.patch(
        f"{BASE}/calendars/cal1/events/e1",
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "e1"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_remove_attendees", {
            "event_id": "e1",
            "attendee_emails": ["b@test.com"],
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_set_attendee_response(server):
    respx.get(
        f"{BASE}/calendars/cal1/events/e1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "e1",
            "attendees": [
                {
                    "email": "a@test.com",
                    "responseStatus": "needsAction",
                },
            ],
        }),
    )
    respx.patch(
        f"{BASE}/calendars/cal1/events/e1",
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "e1"},
        ),
    )
    _ok(await server.call_tool(
        "gcal_set_attendee_response", {
            "event_id": "e1",
            "attendee_email": "a@test.com",
            "response_status": "accepted",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_set_attendee_response_not_found(server):
    respx.get(
        f"{BASE}/calendars/cal1/events/e1",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "e1", "attendees": [],
        }),
    )
    with pytest.raises(Exception, match="not found"):
        await server.call_tool(
            "gcal_set_attendee_response", {
                "event_id": "e1",
                "attendee_email": "nobody@test.com",
                "response_status": "accepted",
            },
        )


# --- FreeBusy (1 tool) ---


@pytest.mark.asyncio
@respx.mock
async def test_freebusy_query(server):
    respx.post(f"{BASE}/freeBusy").mock(
        return_value=httpx.Response(200, json={
            "calendars": {
                "cal1": {
                    "busy": [
                        {
                            "start": "2026-04-05T10:00:00Z",
                            "end": "2026-04-05T11:00:00Z",
                        },
                    ],
                },
            },
        }),
    )
    _ok(await server.call_tool(
        "gcal_freebusy_query", {
            "time_min": "2026-04-05T00:00:00Z",
            "time_max": "2026-04-06T00:00:00Z",
            "items": ["cal1"],
        },
    ))


# --- ACLs (5 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_acl(server):
    respx.get(f"{BASE}/calendars/cal1/acl").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {"id": "user:a@test.com", "role": "owner"},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gcal_list_acl", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_acl_rule(server):
    respx.get(
        f"{BASE}/calendars/cal1/acl/user:a@test.com",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "user:a@test.com", "role": "owner",
        }),
    )
    _ok(await server.call_tool(
        "gcal_get_acl_rule",
        {"rule_id": "user:a@test.com"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_insert_acl_rule(server):
    respx.post(f"{BASE}/calendars/cal1/acl").mock(
        return_value=httpx.Response(200, json={
            "id": "user:b@test.com", "role": "reader",
        }),
    )
    _ok(await server.call_tool(
        "gcal_insert_acl_rule", {
            "role": "reader",
            "scope_type": "user",
            "scope_value": "b@test.com",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_update_acl_rule(server):
    respx.patch(
        f"{BASE}/calendars/cal1/acl/user:b@test.com",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "user:b@test.com", "role": "writer",
        }),
    )
    _ok(await server.call_tool(
        "gcal_update_acl_rule", {
            "rule_id": "user:b@test.com",
            "role": "writer",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_delete_acl_rule(server):
    respx.delete(
        f"{BASE}/calendars/cal1/acl/user:b@test.com",
    ).mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gcal_delete_acl_rule",
        {"rule_id": "user:b@test.com"},
    ))


# --- Settings (2 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_list_settings(server):
    respx.get(f"{BASE}/users/me/settings").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {"id": "timezone", "value": "UTC"},
            ],
        }),
    )
    r = _r(await server.call_tool(
        "gcal_list_settings", {},
    ))
    assert r["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_setting(server):
    respx.get(
        f"{BASE}/users/me/settings/timezone",
    ).mock(
        return_value=httpx.Response(200, json={
            "id": "timezone", "value": "America/New_York",
        }),
    )
    _ok(await server.call_tool(
        "gcal_get_setting", {"setting_id": "timezone"},
    ))


# --- Colors (1 tool) ---


@pytest.mark.asyncio
@respx.mock
async def test_get_colors(server):
    respx.get(f"{BASE}/colors").mock(
        return_value=httpx.Response(200, json={
            "calendar": {
                "1": {
                    "background": "#ac725e",
                    "foreground": "#1d1d1d",
                },
            },
            "event": {
                "1": {
                    "background": "#a4bdfc",
                    "foreground": "#1d1d1d",
                },
            },
        }),
    )
    _ok(await server.call_tool("gcal_get_colors", {}))


# --- Channels / Watch (3 tools) ---


@pytest.mark.asyncio
@respx.mock
async def test_watch_events(server):
    respx.post(
        f"{BASE}/calendars/cal1/events/watch",
    ).mock(
        return_value=httpx.Response(200, json={
            "kind": "api#channel",
            "id": "ch1",
            "resourceId": "res1",
        }),
    )
    _ok(await server.call_tool(
        "gcal_watch_events", {
            "channel_id": "ch1",
            "address": "https://example.com/hook",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_watch_calendar_list(server):
    respx.post(
        f"{BASE}/users/me/calendarList/watch",
    ).mock(
        return_value=httpx.Response(200, json={
            "kind": "api#channel",
            "id": "ch2",
            "resourceId": "res2",
        }),
    )
    _ok(await server.call_tool(
        "gcal_watch_calendar_list", {
            "channel_id": "ch2",
            "address": "https://example.com/hook2",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_stop_channel(server):
    respx.post(f"{BASE}/channels/stop").mock(
        return_value=httpx.Response(204),
    )
    _ok(await server.call_tool(
        "gcal_stop_channel", {
            "channel_id": "ch1",
            "resource_id": "res1",
        },
    ))
