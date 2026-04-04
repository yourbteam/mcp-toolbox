# Task 18: Google Calendar Integration — Analysis

## Overview

Add a Google Calendar API v3 integration to MCP Toolbox, providing full coverage of calendar management, event CRUD, scheduling, ACLs, settings, and colors. This integration reuses the existing Google service account authentication pattern from the Sheets integration (`sheets_tool.py`), with a Calendar-specific scope.

**API Base URL:** `https://www.googleapis.com/calendar/v3`

---

## Authentication & Configuration

### Auth Pattern (mirrors `sheets_tool.py` exactly)

```python
from google.oauth2 import service_account

_credentials = None

def _get_token() -> str:
    global _credentials
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ToolError("GOOGLE_SERVICE_ACCOUNT_JSON not configured.")
    if _credentials is None:
        _credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
    if not _credentials.valid:
        import google.auth.transport.requests
        _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token
```

- **Scope:** `https://www.googleapis.com/auth/calendar` (full read/write)
- **Token refresh:** `google.auth.transport.requests.Request()` — sync call wrapped with `asyncio.to_thread(_get_token)`
- **Singleton credentials:** Module-level `_credentials` object, refreshed on expiry
- **Singleton httpx client:** Module-level `_client: httpx.AsyncClient` with `base_url` set to the Calendar API base

### Config Variables

| Variable | Source | Required | Notes |
|----------|--------|----------|-------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | `config.py` (existing) | Yes | Path to service account JSON key file |
| `GCAL_DEFAULT_CALENDAR_ID` | `config.py` (new) | No | Optional default calendar ID; falls back to `"primary"` |

**Config change:** Add `GCAL_DEFAULT_CALENDAR_ID` to `config.py`:
```python
GCAL_DEFAULT_CALENDAR_ID: str | None = os.getenv("GCAL_DEFAULT_CALENDAR_ID")
```

### Service Account Setup Requirements

- The service account must have **Google Calendar API** enabled in the GCP project
- For accessing user calendars: the service account needs **domain-wide delegation** enabled, and the admin must authorize the scopes in the Google Workspace admin console
- For service-account-owned calendars: no delegation needed; the service account has its own calendar
- Calendars must be explicitly shared with the service account email (`xxx@project.iam.gserviceaccount.com`) for the account to access them

### Domain-Wide Delegation (important quirk)

When using domain-wide delegation to impersonate a user, the credentials must be created with a `subject` parameter:
```python
_credentials = _credentials.with_subject(user_email)
```
For the initial implementation, we will NOT implement impersonation — the service account accesses only calendars shared with it or its own calendar. Impersonation support can be added later as an enhancement.

---

## Architecture Decisions

### HTTP Client
- **Singleton `httpx.AsyncClient`** with `base_url="https://www.googleapis.com/calendar/v3"` and `timeout=30.0`
- Token refreshed per-request via `_get_client()` (same as Sheets pattern)
- Headers set on client: `Authorization: Bearer {token}`

### Helper Functions
| Helper | Purpose |
|--------|---------|
| `_get_token()` | Sync token acquisition/refresh, called via `asyncio.to_thread` |
| `_get_client()` | Returns singleton httpx client with fresh token |
| `_req(method, url, json_body, params)` | Central request handler with error handling, 429 detection |
| `_success(sc, **kw)` | Standard JSON success response |
| `_cid(override)` | Returns `override or GCAL_DEFAULT_CALENDAR_ID or "primary"` |

### Error Handling
- 429 responses: raise `ToolError` with retry guidance
- 4xx/5xx: parse `error.message` from Google's JSON error format and raise `ToolError`
- Network errors: catch `httpx.HTTPError` and wrap in `ToolError`

### Response Format
All tools return `json.dumps({"status": "success", "status_code": ..., ...})` — consistent with every other integration.

---

## Rate Limits

Google Calendar API quotas (per project):

| Quota | Limit |
|-------|-------|
| Queries per day | 1,000,000 |
| Queries per 100 seconds per user | 500 |
| Queries per 100 seconds (project) | 10,000 |

For service accounts without domain-wide delegation, the "per user" quota applies to the service account itself.

---

## Key API Quirks

1. **DateTime format:** Google Calendar uses RFC 3339 (`2024-01-15T09:00:00-05:00` or `2024-01-15T14:00:00Z`). All-day events use `date` field (YYYY-MM-DD) instead of `dateTime`.
2. **Calendar ID:** `"primary"` is an alias for the authenticated user's primary calendar. Service accounts have their own primary calendar.
3. **Recurring events:** The API returns individual instances or the series master depending on the endpoint. `events.list` returns single events and recurring event masters; `events.instances` returns expanded instances.
4. **Pagination:** List endpoints return `nextPageToken`; pass as `pageToken` to get next page. Default `maxResults` varies by endpoint (250 for events).
5. **ETag / If-Match:** Update and delete operations support conditional requests via `If-Match` header with the event's `etag`. Not required but prevents race conditions.
6. **Time zones:** Event times include timezone info. The `timeZone` parameter on list requests controls the timezone of the response.
7. **sendUpdates parameter:** On event create/update/delete, controls whether notification emails are sent to attendees. Values: `all`, `externalOnly`, `none`.
8. **Colors:** The Colors API returns a fixed set of event and calendar color definitions (IDs map to hex values).
9. **FreeBusy:** The freeBusy.query endpoint accepts a POST body with time range and calendar IDs, not individual calendar endpoints.
10. **Settings:** User settings are read-only via the API (no write endpoint).
11. **Watch/Channels:** Push notification channels require a publicly accessible HTTPS endpoint. We will include `watch` and `stop` tools but note the webhook requirement.

---

## Tool Inventory — Complete Endpoint Coverage

### Tier 1: CalendarList (user's list of visible calendars) — 5 tools

The CalendarList resource represents a user's collection of calendars that appear in their UI. This is distinct from the Calendars resource (which is the calendar metadata itself).

| # | Tool Name | HTTP | Endpoint | Description |
|---|-----------|------|----------|-------------|
| 1 | `gcal_list_calendar_list` | GET | `/users/me/calendarList` | List all calendars in the user's calendar list |
| 2 | `gcal_get_calendar_list_entry` | GET | `/users/me/calendarList/{calendarId}` | Get a specific calendar list entry |
| 3 | `gcal_insert_calendar_list_entry` | POST | `/users/me/calendarList` | Add an existing calendar to the user's calendar list |
| 4 | `gcal_update_calendar_list_entry` | PATCH | `/users/me/calendarList/{calendarId}` | Update a calendar list entry (color, visibility, etc.) |
| 5 | `gcal_delete_calendar_list_entry` | DELETE | `/users/me/calendarList/{calendarId}` | Remove a calendar from the user's calendar list |

#### Tool Details

**gcal_list_calendar_list**
- Params: `min_access_role: str | None` (optional, freeBusyReader/owner/reader/writer), `show_deleted: bool = False`, `show_hidden: bool = False`, `page_token: str | None`, `max_results: int = 100`, `sync_token: str | None`
- Returns: list of CalendarListEntry resources

**gcal_get_calendar_list_entry**
- Params: `calendar_id: str` (required)
- Returns: single CalendarListEntry resource

**gcal_insert_calendar_list_entry**
- Params: `calendar_id: str` (required — ID of the calendar to add), `color_rgb_format: bool = False`, `background_color: str | None`, `foreground_color: str | None`, `color_id: str | None`, `hidden: bool | None`, `selected: bool | None`, `default_reminders: list[dict] | None`, `notification_settings: dict | None`, `summary_override: str | None`
- Returns: created CalendarListEntry

**gcal_update_calendar_list_entry**
- Params: `calendar_id: str` (required), `color_rgb_format: bool = False`, `background_color: str | None`, `foreground_color: str | None`, `color_id: str | None`, `hidden: bool | None`, `selected: bool | None`, `default_reminders: list[dict] | None`, `notification_settings: dict | None`, `summary_override: str | None`
- Note: Uses PATCH (partial update) rather than PUT (full replace) for better usability
- Returns: updated CalendarListEntry

**gcal_delete_calendar_list_entry**
- Params: `calendar_id: str` (required)
- Returns: success confirmation

---

### Tier 2: Calendars (calendar metadata CRUD) — 5 tools

The Calendars resource represents the calendar itself (title, description, timezone). Distinct from CalendarList (which is per-user view settings).

| # | Tool Name | HTTP | Endpoint | Description |
|---|-----------|------|----------|-------------|
| 6 | `gcal_get_calendar` | GET | `/calendars/{calendarId}` | Get calendar metadata |
| 7 | `gcal_create_calendar` | POST | `/calendars` | Create a new secondary calendar |
| 8 | `gcal_update_calendar` | PATCH | `/calendars/{calendarId}` | Update calendar metadata |
| 9 | `gcal_delete_calendar` | DELETE | `/calendars/{calendarId}` | Delete a secondary calendar |
| 10 | `gcal_clear_calendar` | POST | `/calendars/{calendarId}/clear` | Clear all events from a primary calendar |

#### Tool Details

**gcal_get_calendar**
- Params: `calendar_id: str | None` (defaults to `_cid()`)
- Returns: Calendar resource (id, summary, description, timeZone, location)

**gcal_create_calendar**
- Params: `summary: str` (required), `description: str | None`, `location: str | None`, `time_zone: str | None`
- Returns: created Calendar resource

**gcal_update_calendar**
- Params: `calendar_id: str | None`, `summary: str | None`, `description: str | None`, `location: str | None`, `time_zone: str | None`
- Note: Uses PATCH for partial update
- Returns: updated Calendar resource

**gcal_delete_calendar**
- Params: `calendar_id: str` (required — cannot delete "primary")
- Returns: success confirmation

**gcal_clear_calendar**
- Params: `calendar_id: str | None` (defaults to `_cid()`)
- Note: Only works on the primary calendar. Deletes all events.
- Returns: success confirmation

---

### Tier 3: Events (core CRUD + query) — 10 tools

| # | Tool Name | HTTP | Endpoint | Description |
|---|-----------|------|----------|-------------|
| 11 | `gcal_list_events` | GET | `/calendars/{calendarId}/events` | List events with optional filters |
| 12 | `gcal_get_event` | GET | `/calendars/{calendarId}/events/{eventId}` | Get a single event by ID |
| 13 | `gcal_create_event` | POST | `/calendars/{calendarId}/events` | Create a new event |
| 14 | `gcal_update_event` | PATCH | `/calendars/{calendarId}/events/{eventId}` | Update event fields |
| 15 | `gcal_delete_event` | DELETE | `/calendars/{calendarId}/events/{eventId}` | Delete an event |
| 16 | `gcal_quick_add_event` | POST | `/calendars/{calendarId}/events/quickAdd` | Create event from natural language text |
| 17 | `gcal_move_event` | POST | `/calendars/{calendarId}/events/{eventId}/move` | Move event to another calendar |
| 18 | `gcal_import_event` | POST | `/calendars/{calendarId}/events/import` | Import an event (iCalendar UID-based) |
| 19 | `gcal_list_event_instances` | GET | `/calendars/{calendarId}/events/{eventId}/instances` | List instances of a recurring event |
| 20 | `gcal_patch_event` | PATCH | `/calendars/{calendarId}/events/{eventId}` | Alias for update (kept for API completeness if full PUT is needed) |

**Note:** Tool #20 (`gcal_patch_event`) is redundant with `gcal_update_event`. We will implement only `gcal_update_event` using PATCH, and skip the separate PUT-based full update. Total for this tier: **9 tools**.

#### Tool Details

**gcal_list_events**
- Params: `calendar_id: str | None`, `time_min: str | None` (RFC 3339), `time_max: str | None` (RFC 3339), `q: str | None` (free-text search), `max_results: int = 250`, `order_by: str | None` (startTime/updated), `single_events: bool = True`, `show_deleted: bool = False`, `show_hidden_invitations: bool = False`, `time_zone: str | None`, `page_token: str | None`, `sync_token: str | None`, `updated_min: str | None`, `i_cal_uid: str | None`, `private_extended_property: str | None`, `shared_extended_property: str | None`
- Note: `single_events=True` expands recurring events; `order_by=startTime` only valid when `single_events=True`
- Returns: list of Event resources with `nextPageToken`

**gcal_get_event**
- Params: `event_id: str` (required), `calendar_id: str | None`, `time_zone: str | None`, `max_attendees: int | None`
- Returns: single Event resource

**gcal_create_event**
- Params: `summary: str` (required), `start_datetime: str | None`, `start_date: str | None` (for all-day), `end_datetime: str | None`, `end_date: str | None` (for all-day), `time_zone: str = "UTC"`, `description: str | None`, `location: str | None`, `attendees: list[str] | None` (email addresses), `recurrence: list[str] | None` (RRULE strings), `reminders: dict | None`, `color_id: str | None`, `visibility: str | None` (default/public/private/confidential), `transparency: str | None` (opaque/transparent), `status: str | None` (confirmed/tentative/cancelled), `conference_data: dict | None`, `conference_data_version: int | None` (0 or 1), `source: dict | None`, `extended_properties: dict | None`, `guests_can_modify: bool | None`, `guests_can_invite_others: bool | None`, `guests_can_see_other_guests: bool | None`, `send_updates: str = "none"` (all/externalOnly/none), `calendar_id: str | None`
- Note: Either `start_datetime`+`end_datetime` OR `start_date`+`end_date` must be provided
- Returns: created Event resource

**gcal_update_event**
- Params: `event_id: str` (required), `calendar_id: str | None`, `summary: str | None`, `start_datetime: str | None`, `start_date: str | None`, `end_datetime: str | None`, `end_date: str | None`, `time_zone: str | None`, `description: str | None`, `location: str | None`, `attendees: list[str] | None`, `recurrence: list[str] | None`, `reminders: dict | None`, `color_id: str | None`, `visibility: str | None`, `transparency: str | None`, `status: str | None`, `send_updates: str = "none"`, `extended_properties: dict | None`, `guests_can_modify: bool | None`, `guests_can_invite_others: bool | None`, `guests_can_see_other_guests: bool | None`
- Note: Uses PATCH — only provided fields are updated
- Returns: updated Event resource

**gcal_delete_event**
- Params: `event_id: str` (required), `calendar_id: str | None`, `send_updates: str = "none"`
- Returns: success confirmation

**gcal_quick_add_event**
- Params: `text: str` (required — e.g., "Lunch with Bob tomorrow at noon"), `calendar_id: str | None`, `send_updates: str = "none"`
- Note: Google parses the natural-language string into an event
- Returns: created Event resource

**gcal_move_event**
- Params: `event_id: str` (required), `destination_calendar_id: str` (required), `calendar_id: str | None` (source), `send_updates: str = "none"`
- Returns: moved Event resource

**gcal_import_event**
- Params: `calendar_id: str | None`, `i_cal_uid: str` (required), `summary: str` (required), `start_datetime: str | None`, `start_date: str | None`, `end_datetime: str | None`, `end_date: str | None`, `time_zone: str = "UTC"`, `description: str | None`, `location: str | None`, `attendees: list[str] | None`, `status: str | None`, `organizer: dict | None`
- Note: Uses iCalendar UID for deduplication; idempotent
- Returns: imported Event resource

**gcal_list_event_instances**
- Params: `event_id: str` (required), `calendar_id: str | None`, `time_min: str | None`, `time_max: str | None`, `max_results: int = 25`, `page_token: str | None`, `time_zone: str | None`, `show_deleted: bool = False`
- Returns: list of Event instance resources

---

### Tier 4: Event Attendees & Responses — 3 tools

Google Calendar API does not have separate attendee endpoints. Attendee management is done by updating the event's `attendees` array. However, there are dedicated response/RSVP patterns worth exposing as tools for convenience.

| # | Tool Name | HTTP | Endpoint | Description |
|---|-----------|------|----------|-------------|
| 20 | `gcal_add_attendees` | PATCH | `/calendars/{calendarId}/events/{eventId}` | Add attendees to an existing event |
| 21 | `gcal_remove_attendees` | PATCH | `/calendars/{calendarId}/events/{eventId}` | Remove attendees from an event |
| 22 | `gcal_set_attendee_response` | PATCH | `/calendars/{calendarId}/events/{eventId}` | Set responseStatus for an attendee |

#### Tool Details

**gcal_add_attendees**
- Params: `event_id: str` (required), `attendee_emails: list[str]` (required), `calendar_id: str | None`, `send_updates: str = "all"`
- Logic: GET event, append to `attendees` array, PATCH back
- Returns: updated Event resource

**gcal_remove_attendees**
- Params: `event_id: str` (required), `attendee_emails: list[str]` (required), `calendar_id: str | None`, `send_updates: str = "all"`
- Logic: GET event, filter `attendees` array, PATCH back
- Returns: updated Event resource

**gcal_set_attendee_response**
- Params: `event_id: str` (required), `attendee_email: str` (required), `response_status: str` (required — needsAction/declined/tentative/accepted), `calendar_id: str | None`, `send_updates: str = "none"`
- Logic: GET event, find attendee, set `responseStatus`, PATCH back
- Returns: updated Event resource

---

### Tier 5: FreeBusy — 1 tool

| # | Tool Name | HTTP | Endpoint | Description |
|---|-----------|------|----------|-------------|
| 23 | `gcal_freebusy_query` | POST | `/freeBusy` | Query free/busy information for calendars |

#### Tool Details

**gcal_freebusy_query**
- Params: `time_min: str` (required, RFC 3339), `time_max: str` (required, RFC 3339), `items: list[str]` (required — calendar IDs to query), `time_zone: str | None`, `calendar_expansion_max: int | None` (max calendars in group expansion, 1-50), `group_expansion_max: int | None` (max members in group expansion, 1-100)
- Returns: FreeBusy response with `calendars` dict mapping calendar IDs to busy intervals

---

### Tier 6: ACLs (Access Control Lists) — 5 tools

ACL rules control who can access a calendar and at what permission level.

| # | Tool Name | HTTP | Endpoint | Description |
|---|-----------|------|----------|-------------|
| 24 | `gcal_list_acl` | GET | `/calendars/{calendarId}/acl` | List ACL rules for a calendar |
| 25 | `gcal_get_acl_rule` | GET | `/calendars/{calendarId}/acl/{ruleId}` | Get a specific ACL rule |
| 26 | `gcal_insert_acl_rule` | POST | `/calendars/{calendarId}/acl` | Create an ACL rule (share calendar) |
| 27 | `gcal_update_acl_rule` | PATCH | `/calendars/{calendarId}/acl/{ruleId}` | Update an ACL rule's role |
| 28 | `gcal_delete_acl_rule` | DELETE | `/calendars/{calendarId}/acl/{ruleId}` | Delete an ACL rule (revoke access) |

#### Tool Details

**gcal_list_acl**
- Params: `calendar_id: str | None`, `page_token: str | None`, `max_results: int | None`, `show_deleted: bool = False`, `sync_token: str | None`
- Returns: list of ACL rule resources

**gcal_get_acl_rule**
- Params: `calendar_id: str | None`, `rule_id: str` (required — format: `user:email@example.com`)
- Returns: single ACL rule resource

**gcal_insert_acl_rule**
- Params: `calendar_id: str | None`, `role: str` (required — none/freeBusyReader/reader/writer/owner), `scope_type: str` (required — default/user/group/domain), `scope_value: str | None` (email or domain — required unless scope_type is "default"), `send_notifications: bool = True`
- Returns: created ACL rule

**gcal_update_acl_rule**
- Params: `calendar_id: str | None`, `rule_id: str` (required), `role: str` (required — new role), `send_notifications: bool = True`
- Returns: updated ACL rule

**gcal_delete_acl_rule**
- Params: `calendar_id: str | None`, `rule_id: str` (required)
- Returns: success confirmation

---

### Tier 7: Settings (read-only) — 2 tools

Calendar settings are read-only via the API.

| # | Tool Name | HTTP | Endpoint | Description |
|---|-----------|------|----------|-------------|
| 29 | `gcal_list_settings` | GET | `/users/me/settings` | List all user settings |
| 30 | `gcal_get_setting` | GET | `/users/me/settings/{settingId}` | Get a specific setting value |

#### Tool Details

**gcal_list_settings**
- Params: `page_token: str | None`, `max_results: int | None`, `sync_token: str | None`
- Returns: list of Setting resources (id, value pairs)

**gcal_get_setting**
- Params: `setting_id: str` (required — e.g., `timezone`, `locale`, `dateFieldOrder`, `defaultEventLength`, `weekStart`, `showDeclinedEvents`, `format24HourTime`, `autoAddHangouts`, `useKeyboardShortcuts`)
- Returns: single Setting resource

---

### Tier 8: Colors — 1 tool

| # | Tool Name | HTTP | Endpoint | Description |
|---|-----------|------|----------|-------------|
| 31 | `gcal_get_colors` | GET | `/colors` | Get available calendar and event color definitions |

#### Tool Details

**gcal_get_colors**
- Params: none
- Returns: Colors resource with `calendar` and `event` dicts mapping color IDs to `{background, foreground}` hex values

---

### Tier 9: Channels (push notifications) — 1 tool

| # | Tool Name | HTTP | Endpoint | Description |
|---|-----------|------|----------|-------------|
| 32 | `gcal_stop_channel` | POST | `/channels/stop` | Stop receiving push notifications for a channel |

**Note:** Watch (subscribe) operations are done per-resource (e.g., `POST /calendars/{calendarId}/events/watch`). We include event watch below.

#### Tool Details

**gcal_stop_channel**
- Params: `channel_id: str` (required), `resource_id: str` (required)
- Returns: success confirmation (204)

---

### Tier 10: Event Watch (push notifications) — 1 tool

| # | Tool Name | HTTP | Endpoint | Description |
|---|-----------|------|----------|-------------|
| 33 | `gcal_watch_events` | POST | `/calendars/{calendarId}/events/watch` | Subscribe to push notifications for event changes |

#### Tool Details

**gcal_watch_events**
- Params: `calendar_id: str | None`, `channel_id: str` (required — unique UUID), `channel_type: str = "web_hook"`, `address: str` (required — HTTPS callback URL), `token: str | None` (optional verification token), `expiration: int | None` (Unix timestamp ms for channel expiry), `params: dict | None` (optional — e.g., `{"ttl": "3600"}`)
- Note: Requires a publicly accessible HTTPS endpoint to receive notifications
- Returns: Channel resource with `resourceId`, `expiration`

---

### Tier 11: CalendarList Watch — 1 tool

| # | Tool Name | HTTP | Endpoint | Description |
|---|-----------|------|----------|-------------|
| 34 | `gcal_watch_calendar_list` | POST | `/users/me/calendarList/watch` | Subscribe to push notifications for calendar list changes |

#### Tool Details

**gcal_watch_calendar_list**
- Params: `channel_id: str` (required), `channel_type: str = "web_hook"`, `address: str` (required — HTTPS callback URL), `token: str | None`, `expiration: int | None`, `params: dict | None`
- Returns: Channel resource

---

## Tool Count Summary

| Tier | Resource | Tools |
|------|----------|-------|
| 1 | CalendarList | 5 |
| 2 | Calendars | 5 |
| 3 | Events | 9 |
| 4 | Attendees (convenience) | 3 |
| 5 | FreeBusy | 1 |
| 6 | ACLs | 5 |
| 7 | Settings | 2 |
| 8 | Colors | 1 |
| 9 | Channels (stop) | 1 |
| 10 | Event Watch | 1 |
| 11 | CalendarList Watch | 1 |
| **Total** | | **34** |

---

## Dependencies

### Existing (no new packages needed)
- `httpx` — async HTTP client (already in project)
- `google-auth[requests]` — service account auth (already installed for Sheets)

### No new dependencies required
The Calendar API is a standard REST API; we use direct httpx calls with Bearer token auth, same as Sheets.

---

## File Structure

```
src/mcp_toolbox/tools/gcal_tool.py    # All 34 tools + helpers
```

**Filename:** `gcal_tool.py` (not `google_calendar_tool.py`) — keeps names concise and follows the pattern of short prefixes (`gcal_` on tool names).

### Registration

Add to `src/mcp_toolbox/tools/__init__.py`:
```python
from .gcal_tool import register_tools as register_gcal_tools
```

And include `register_gcal_tools(mcp)` in `register_all_tools()`.

---

## Testing Strategy

### Test file: `tests/test_gcal_tool.py`

1. **Auth tests:** Mock `service_account.Credentials.from_service_account_file`, verify scope and token refresh
2. **Request helper tests:** Mock httpx responses for success, 429, 4xx, 5xx, network errors
3. **Tool-level tests:** For each tool, mock `_req` and verify:
   - Correct HTTP method and path
   - Request body construction from parameters
   - Default parameter handling (calendar_id fallback to `_cid()`)
   - Response formatting
4. **Edge cases:** All-day events (date vs dateTime), empty attendee lists, pagination tokens

### pyright
This file should be **included** in pyright checks (no dynamic SDK — pure httpx + google-auth, both well-typed).

---

## Implementation Notes

1. **Tool prefix:** All tools prefixed `gcal_` to avoid collision with the existing MS Graph `calendar_` tools
2. **Calendar ID helper:** `_cid(override)` returns `override or GCAL_DEFAULT_CALENDAR_ID or "primary"`
3. **All-day event handling:** Create/update tools accept both `start_datetime`/`end_datetime` and `start_date`/`end_date`; the helper constructs the appropriate `{"dateTime": ...}` or `{"date": ...}` object
4. **Attendee format:** Tools accept plain email strings and convert to Google's `{"email": "..."}` attendee objects internally
5. **sendUpdates:** Defaults to `"none"` to avoid surprise emails; user can override to `"all"` or `"externalOnly"`
6. **Recurrence:** Accepts RRULE strings as `list[str]` (e.g., `["RRULE:FREQ=WEEKLY;COUNT=10"]`)
7. **Pagination:** All list tools expose `page_token` and `max_results` params; they do NOT auto-paginate (consistent with other integrations)
8. **Watch tools:** Included for completeness but documented as requiring a publicly accessible HTTPS endpoint
