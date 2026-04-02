# Task 10: Microsoft Graph Calendar Integration - Analysis & Requirements

## Objective
Add Microsoft 365 calendar management via Microsoft Graph API as a tool integration in mcp-toolbox. This builds on the existing O365 email integration, reusing the same authentication, HTTP client, and configuration infrastructure.

---

## API Technical Details

### Microsoft Graph API v1.0
- **Base URL:** `https://graph.microsoft.com/v1.0`
- **Calendar endpoints:** `/users/{user-id}/calendars`, `/users/{user-id}/events`, `/users/{user-id}/calendar/calendarView`
- **Format:** JSON request/response
- **Auth:** OAuth2 Bearer token (same token as O365 email tools)

### Authentication — Reuse Existing O365 Client Credentials Flow
The calendar tools use the **exact same** MSAL client credentials flow already implemented in `o365_tool.py`. The token acquired via `_get_token()` with scope `https://graph.microsoft.com/.default` covers all Graph API resources including Calendar. No new auth code is needed.

### Required Permissions (Application)

| Permission | Type | Description | Admin Consent |
|-----------|------|-------------|---------------|
| `Calendars.ReadWrite` | Application | Read/write calendars and events for all users | Required |

**Note:** The existing O365 app registration needs `Calendars.ReadWrite` added as an application permission in Microsoft Entra ID. The `Mail.Send`, `Mail.Read`, and `Mail.ReadWrite` permissions already granted are separate from calendar permissions.

**Security note:** Application Access Policy can restrict the app to specific mailboxes/calendars instead of the entire tenant, same as email.

### Rate Limits

| Limit | Value |
|-------|-------|
| Requests per 10 min per mailbox | 10,000 |
| Concurrent requests per app per mailbox | 4 |
| getSchedule max entities per request | 20 |
| calendarView max date range | 2 years |
| Event instances page size (default) | 10 |

HTTP 429 with `Retry-After` header on throttle (already handled by existing `_request()` helper).

---

## Available Capabilities

| Capability | Endpoint Pattern | Method | Notes |
|-----------|-----------------|--------|-------|
| **List calendars** | `/users/{id}/calendars` | GET | All user calendars with OData query support |
| **Get calendar** | `/users/{id}/calendars/{cal-id}` | GET | Single calendar details |
| **Create event** | `/users/{id}/calendar/events` | POST | With attendees, recurrence, location, reminders |
| **Get event** | `/users/{id}/events/{event-id}` | GET | Full event details |
| **Update event** | `/users/{id}/events/{event-id}` | PATCH | Modify any event property |
| **Delete event** | `/users/{id}/events/{event-id}` | DELETE | Remove event from calendar |
| **List events** | `/users/{id}/calendar/calendarView` | GET | Date-range filtered, expands recurring events |
| **Accept event** | `/users/{id}/events/{event-id}/accept` | POST | Accept meeting invitation |
| **Decline event** | `/users/{id}/events/{event-id}/decline` | POST | Decline meeting invitation |
| **Tentatively accept** | `/users/{id}/events/{event-id}/tentativelyAccept` | POST | Tentatively accept invitation |
| **Get free/busy** | `/users/{id}/calendar/getSchedule` | POST | Availability for multiple users/rooms |
| **List instances** | `/users/{id}/events/{event-id}/instances` | GET | Occurrences of a recurring event |
| **Forward event** | `/users/{id}/events/{event-id}/forward` | POST | Forward event as email with .ics |
| **Cancel event** | `/users/{id}/events/{event-id}/cancel` | POST | Organizer cancels meeting, notifies attendees |
| **Create calendar** | `/users/{id}/calendars` | POST | Create a new calendar |
| **Delete calendar** | `/users/{id}/calendars/{cal-id}` | DELETE | Remove a calendar |
| **Find meeting times** | `/users/{id}/findMeetingTimes` | POST | Suggest meeting times based on attendee availability |
| **Add event attachment** | `/users/{id}/events/{event-id}/attachments` | POST | Attach a file to an event |
| **List event attachments** | `/users/{id}/events/{event-id}/attachments` | GET | List all attachments on an event |
| **Get event attachment** | `/users/{id}/events/{event-id}/attachments/{att-id}` | GET | Get a specific attachment |
| **Delete event attachment** | `/users/{id}/events/{event-id}/attachments/{att-id}` | DELETE | Remove an attachment from an event |
| **Snooze reminder** | `/users/{id}/events/{event-id}/snoozeReminder` | POST | Snooze event reminder to new time |
| **Dismiss reminder** | `/users/{id}/events/{event-id}/dismissReminder` | POST | Dismiss event reminder |

---

## Architecture Decisions

### A1: Reuse Existing O365 Auth Infrastructure
The calendar tools will import and reuse `_get_token()`, `_get_http_client()`, `_request()`, `_get_user_id()`, and `_success()` from `o365_tool.py`. These helpers will be extracted into a shared module (`o365_helpers.py`) or imported directly. The MSAL app, httpx client, and token cache are singletons that serve both email and calendar tools.

### A2: Shared Helper Module
Extract common Graph API helpers (`_get_token`, `_get_http_client`, `_request`, `_get_user_id`, `_success`) into `src/mcp_toolbox/tools/o365_helpers.py`. Both `o365_tool.py` and the new `calendar_tool.py` import from it. This avoids code duplication and ensures a single MSAL app / httpx client instance.

### A3: Tool Naming Convention
All calendar tools are prefixed with `calendar_` to distinguish them from `o365_` email tools while keeping them discoverable. Examples: `calendar_list_events`, `calendar_create_event`.

### A4: Date/Time Handling
Microsoft Graph Calendar API uses ISO 8601 date-time strings with timezone. Tools accept `start_datetime` and `end_datetime` as ISO 8601 strings (e.g., `2026-04-01T09:00:00`) and `timezone` as an IANA timezone string (e.g., `America/New_York`). The API wraps these in `{"dateTime": "...", "timeZone": "..."}` objects.

### A5: Attendee Format
Attendees are passed as a list of email strings and converted to the Graph API format: `[{"emailAddress": {"address": "...", "name": "..."}, "type": "required"}]`. Reuses the `_recipients()` pattern from email tools.

### A6: Error Handling
Identical to email tools -- the shared `_request()` already handles 429 rate limits, 4xx/5xx error parsing, and Graph API error body extraction.

### A7: Response Format
Same JSON convention: `{"status": "success", "status_code": ..., "data": ...}`.

---

## Configuration Requirements

### No New Configuration Needed
Calendar tools reuse the existing O365 configuration variables. If O365 email is already set up, calendar works with the same credentials and token.

| Variable | Description | Already Exists |
|----------|-------------|----------------|
| `O365_TENANT_ID` | Entra ID tenant ID | Yes |
| `O365_CLIENT_ID` | App registration client ID | Yes |
| `O365_CLIENT_SECRET` | App client secret | Yes |
| `O365_USER_ID` | Default user email/ID for calendar operations | Yes |

**Only action required:** Add `Calendars.ReadWrite` application permission to the existing app registration in Microsoft Entra ID and grant admin consent.

---

## Tool Specifications

### Calendar Management Tools (4 tools)

#### 1. `calendar_list_calendars`
List all calendars for a user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | str | No | User email or ID (falls back to O365_USER_ID config) |

**Returns:** List of calendars with id, name, color, owner, canEdit, canShare, default online meeting provider.
**Endpoint:** `GET /users/{user_id}/calendars`

#### 2. `calendar_get_calendar`
Get details of a specific calendar.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `calendar_id` | str | Yes | Calendar ID |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** Calendar object with id, name, color, hexColor, canEdit, canShare, canViewPrivateItems, owner, allowedOnlineMeetingProviders, defaultOnlineMeetingProvider, isRemovable.
**Endpoint:** `GET /users/{user_id}/calendars/{calendar_id}`

#### 3. `calendar_create_calendar`
Create a new calendar for a user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Display name for the new calendar |
| `user_id` | str | No | User email or ID (falls back to O365_USER_ID config) |

**Returns:** Created calendar object with id, name, color, owner.
**Endpoint:** `POST /users/{user_id}/calendars`

#### 4. `calendar_delete_calendar`
Delete a calendar from a user's mailbox.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `calendar_id` | str | Yes | Calendar ID to delete |
| `user_id` | str | No | User email or ID (falls back to O365_USER_ID config) |

**Returns:** Confirmation with deleted calendar ID.
**Endpoint:** `DELETE /users/{user_id}/calendars/{calendar_id}`

---

### Event CRUD Tools (5 tools)

#### 5. `calendar_create_event`
Create a calendar event with optional attendees, location, recurrence, and online meeting.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | str | Yes | Event title/subject |
| `start_datetime` | str | Yes | Start time in ISO 8601 format (e.g., `2026-04-15T09:00:00`) |
| `end_datetime` | str | Yes | End time in ISO 8601 format (e.g., `2026-04-15T10:00:00`) |
| `timezone` | str | No | IANA timezone (default `UTC`). E.g., `America/New_York`, `Europe/London` |
| `body` | str | No | Event body/description |
| `body_content_type` | str | No | `HTML` or `Text` (default `HTML`) |
| `location` | str | No | Location display name (e.g., `Conference Room A`) |
| `attendees` | str or list[str] | No | Attendee email address(es) |
| `is_all_day` | bool | No | All-day event flag (default false) |
| `is_online_meeting` | bool | No | Create as online meeting (default false) |
| `online_meeting_provider` | str | No | `teamsForBusiness`, `skypeForBusiness`, `skypeForConsumer` (default `teamsForBusiness`) |
| `importance` | str | No | `low`, `normal`, or `high` |
| `sensitivity` | str | No | `normal`, `personal`, `private`, or `confidential` |
| `show_as` | str | No | `free`, `tentative`, `busy`, `oof`, `workingElsewhere`, `unknown` |
| `is_reminder_on` | bool | No | Enable reminder (default true) |
| `reminder_minutes` | int | No | Minutes before event to trigger reminder (default 15) |
| `categories` | list[str] | No | Category labels |
| `recurrence` | dict | No | Recurrence pattern object (Graph API recurrence format) |
| `calendar_id` | str | No | Specific calendar ID (default calendar if omitted) |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** Created event object with id, iCalUId, webLink, onlineMeeting join URL.
**Endpoint:** `POST /users/{user_id}/calendar/events` or `POST /users/{user_id}/calendars/{calendar_id}/events`

**Recurrence format example:**
```json
{
  "pattern": {
    "type": "weekly",
    "interval": 1,
    "daysOfWeek": ["monday", "wednesday", "friday"]
  },
  "range": {
    "type": "endDate",
    "startDate": "2026-04-15",
    "endDate": "2026-06-15"
  }
}
```

#### 6. `calendar_get_event`
Get full details of a specific event.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID |
| `select` | str | No | Comma-separated fields to return (e.g., `subject,start,end,attendees`) |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** Full event object with subject, body, start, end, location, attendees, organizer, recurrence, onlineMeeting, webLink.
**Endpoint:** `GET /users/{user_id}/events/{event_id}`

#### 7. `calendar_update_event`
Update properties of an existing event.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID to update |
| `subject` | str | No | New subject |
| `start_datetime` | str | No | New start time (ISO 8601) |
| `end_datetime` | str | No | New end time (ISO 8601) |
| `timezone` | str | No | IANA timezone for start/end times |
| `body` | str | No | New body/description |
| `body_content_type` | str | No | `HTML` or `Text` (default `HTML`) |
| `location` | str | No | New location display name |
| `attendees` | str or list[str] | No | New attendee list (replaces existing) |
| `is_all_day` | bool | No | All-day event flag |
| `is_online_meeting` | bool | No | Online meeting flag |
| `importance` | str | No | `low`, `normal`, or `high` |
| `sensitivity` | str | No | `normal`, `personal`, `private`, or `confidential` |
| `show_as` | str | No | Free/busy status |
| `is_reminder_on` | bool | No | Enable/disable reminder |
| `reminder_minutes` | int | No | Minutes before event for reminder |
| `categories` | list[str] | No | Category labels |
| `recurrence` | dict | No | Updated recurrence pattern |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** Updated event object.
**Endpoint:** `PATCH /users/{user_id}/events/{event_id}`

**Note:** At least one field must be provided for update. Attendee updates send notifications automatically.

#### 8. `calendar_delete_event`
Delete an event from a user's calendar.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID to delete |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** Confirmation with deleted event ID.
**Endpoint:** `DELETE /users/{user_id}/events/{event_id}`

#### 9. `calendar_list_events`
List events in a calendar view (date-range filtered). This uses the calendarView endpoint which automatically expands recurring event instances within the date range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `start_datetime` | str | Yes | Range start in ISO 8601 (e.g., `2026-04-01T00:00:00`) |
| `end_datetime` | str | Yes | Range end in ISO 8601 (e.g., `2026-04-30T23:59:59`) |
| `top` | int | No | Max results (default 25, max 1000) |
| `select` | str | No | Comma-separated fields to return |
| `filter` | str | No | OData filter expression |
| `order_by` | str | No | Sort field (e.g., `start/dateTime asc`) |
| `calendar_id` | str | No | Specific calendar ID (default calendar if omitted) |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** List of events (including expanded recurring instances) with count.
**Endpoint:** `GET /users/{user_id}/calendarView?startDateTime={start}&endDateTime={end}` or `GET /users/{user_id}/calendars/{calendar_id}/calendarView?startDateTime={start}&endDateTime={end}`

**Note:** The `startDateTime` and `endDateTime` query parameters are required by the Graph API for calendarView. Max date range is 2 years.

---

### Event Response Tools (3 tools)

#### 10. `calendar_accept_event`
Accept a meeting invitation.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID to accept |
| `comment` | str | No | Optional response comment |
| `send_response` | bool | No | Send response to organizer (default true) |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** Confirmation (202 Accepted).
**Endpoint:** `POST /users/{user_id}/events/{event_id}/accept`

#### 11. `calendar_decline_event`
Decline a meeting invitation.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID to decline |
| `comment` | str | No | Optional response comment |
| `send_response` | bool | No | Send response to organizer (default true) |
| `proposed_new_time` | dict | No | Propose alternative time: `{"start": {"dateTime": "...", "timeZone": "..."}, "end": {"dateTime": "...", "timeZone": "..."}}` |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** Confirmation (202 Accepted).
**Endpoint:** `POST /users/{user_id}/events/{event_id}/decline`

#### 12. `calendar_tentatively_accept_event`
Tentatively accept a meeting invitation.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID to tentatively accept |
| `comment` | str | No | Optional response comment |
| `send_response` | bool | No | Send response to organizer (default true) |
| `proposed_new_time` | dict | No | Propose alternative time: `{"start": {"dateTime": "...", "timeZone": "..."}, "end": {"dateTime": "...", "timeZone": "..."}}` |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** Confirmation (202 Accepted).
**Endpoint:** `POST /users/{user_id}/events/{event_id}/tentativelyAccept`

---

### Scheduling & Availability Tools (2 tools)

#### 13. `calendar_get_schedule`
Get free/busy availability information for one or more users, distribution lists, or resources (rooms/equipment).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `schedules` | str or list[str] | Yes | Email address(es) to check availability for (max 20) |
| `start_datetime` | str | Yes | Start of time range in ISO 8601 (e.g., `2026-04-15T08:00:00`) |
| `end_datetime` | str | Yes | End of time range in ISO 8601 (e.g., `2026-04-15T18:00:00`) |
| `timezone` | str | No | IANA timezone (default `UTC`) |
| `availability_view_interval` | int | No | Duration of each time slot in minutes (default 30, min 5, max 1440) |
| `user_id` | str | No | User email or ID making the request (falls back to config) |

**Returns:** List of scheduleInformation objects per requested user, each containing: availabilityView (string of availability codes: 0=free, 1=tentative, 2=busy, 3=oof, 4=workingElsewhere), scheduleItems (array of individual events with subject, status, start, end, location).
**Endpoint:** `POST /users/{user_id}/calendar/getSchedule`

**Request body format:**
```json
{
  "schedules": ["user1@example.com", "room1@example.com"],
  "startTime": {"dateTime": "2026-04-15T08:00:00", "timeZone": "America/New_York"},
  "endTime": {"dateTime": "2026-04-15T18:00:00", "timeZone": "America/New_York"},
  "availabilityViewInterval": 30
}
```

**Note:** Maximum 20 entities per request. Available for user calendars only.

#### 14. `calendar_find_meeting_times`
Suggest meeting times based on attendee availability, organizer constraints, and time preferences.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `attendees` | list[dict] | Yes | List of attendee objects, e.g., `[{"emailAddress": {"address": "user@example.com"}}]` |
| `duration` | str | No | ISO 8601 duration for the meeting (e.g., `PT1H` for 1 hour, `PT30M` for 30 minutes) |
| `time_constraint` | dict | No | Time constraint object: `{"activityDomain": "work", "timeSlots": [{"start": {"dateTime": "...", "timeZone": "..."}, "end": {"dateTime": "...", "timeZone": "..."}}]}` |
| `user_id` | str | No | User email or ID (falls back to O365_USER_ID config) |

**Returns:** Meeting time suggestions with confidence ratings, attendee availability per suggestion, and organizer availability.
**Endpoint:** `POST /users/{user_id}/findMeetingTimes`

---

### Recurring Event Tools (1 tool)

#### 15. `calendar_list_event_instances`
List occurrences (instances) of a recurring event within a time range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Series master event ID |
| `start_datetime` | str | Yes | Range start in ISO 8601 |
| `end_datetime` | str | Yes | Range end in ISO 8601 |
| `top` | int | No | Max results per page (default 10) |
| `select` | str | No | Comma-separated fields to return |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** List of event instance objects (each with its own id, start, end, subject, etc.) with count.
**Endpoint:** `GET /users/{user_id}/events/{event_id}/instances?startDateTime={start}&endDateTime={end}`

**Note:** The event must be of type `seriesMaster`. The `startDateTime` and `endDateTime` query parameters are required. Default page size is 10; use `$top` to adjust. Use `@odata.nextLink` for pagination.

---

### Event Action Tools (2 tools)

#### 16. `calendar_forward_event`
Forward a calendar event to specified recipients as an email with .ics attachment.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID to forward |
| `to` | str or list[str] | Yes | Recipient email address(es) |
| `comment` | str | No | Optional comment to include in the forwarding email |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** Confirmation (202 Accepted).
**Endpoint:** `POST /users/{user_id}/events/{event_id}/forward`

**Request body format:**
```json
{
  "toRecipients": [
    {"emailAddress": {"address": "user@example.com", "name": "User Name"}}
  ],
  "comment": "Please see this event"
}
```

**Note:** The recipient receives the event as an email with an .ics attachment. To directly invite someone, use `calendar_update_event` to add them as an attendee instead.

#### 17. `calendar_cancel_event`
Cancel a meeting event and send a cancellation notification to all attendees. Only the organizer can cancel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID to cancel (must be organizer) |
| `comment` | str | No | Cancellation message to attendees |
| `user_id` | str | No | User email or ID (falls back to config) |

**Returns:** Confirmation (202 Accepted).
**Endpoint:** `POST /users/{user_id}/events/{event_id}/cancel`

**Note:** Only the organizer of the meeting can cancel it. Cancelling sends a notification to all attendees.

---

### Event Attachment Tools (4 tools)

#### 18. `calendar_add_event_attachment`
Add a file attachment to an event.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID to attach the file to |
| `file_path` | str | Yes | Local file path to the attachment |
| `file_name` | str | No | Display name for the attachment (defaults to the file name from file_path) |
| `content_type` | str | No | MIME content type (e.g., `application/pdf`, `image/png`) |
| `user_id` | str | No | User email or ID (falls back to O365_USER_ID config) |

**Returns:** Created attachment object with id, name, contentType, size.
**Endpoint:** `POST /users/{user_id}/events/{event_id}/attachments`

#### 19. `calendar_list_event_attachments`
List all attachments on an event.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID to list attachments for |
| `user_id` | str | No | User email or ID (falls back to O365_USER_ID config) |

**Returns:** List of attachment objects with id, name, contentType, size.
**Endpoint:** `GET /users/{user_id}/events/{event_id}/attachments`

#### 20. `calendar_get_event_attachment`
Get a specific attachment from an event.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID the attachment belongs to |
| `attachment_id` | str | Yes | Attachment ID to retrieve |
| `user_id` | str | No | User email or ID (falls back to O365_USER_ID config) |

**Returns:** Attachment object with id, name, contentType, size, contentBytes (base64-encoded).
**Endpoint:** `GET /users/{user_id}/events/{event_id}/attachments/{attachment_id}`

#### 21. `calendar_delete_event_attachment`
Delete an attachment from an event.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID the attachment belongs to |
| `attachment_id` | str | Yes | Attachment ID to delete |
| `user_id` | str | No | User email or ID (falls back to O365_USER_ID config) |

**Returns:** Confirmation with deleted attachment ID.
**Endpoint:** `DELETE /users/{user_id}/events/{event_id}/attachments/{attachment_id}`

---

### Event Reminder Tools (2 tools)

#### 22. `calendar_snooze_reminder`
Snooze an event reminder to a new time.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID to snooze the reminder for |
| `new_reminder_time` | str | Yes | New reminder time in ISO 8601 datetime format (e.g., `2026-04-15T08:45:00`) |
| `user_id` | str | No | User email or ID (falls back to O365_USER_ID config) |

**Returns:** Confirmation (200 OK).
**Endpoint:** `POST /users/{user_id}/events/{event_id}/snoozeReminder`

#### 23. `calendar_dismiss_reminder`
Dismiss an event reminder.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID to dismiss the reminder for |
| `user_id` | str | No | User email or ID (falls back to O365_USER_ID config) |

**Returns:** Confirmation (200 OK).
**Endpoint:** `POST /users/{user_id}/events/{event_id}/dismissReminder`

---

## Tool Summary (23 tools total)

### Calendar Management (4 tools)
1. `calendar_list_calendars` -- List all user calendars
2. `calendar_get_calendar` -- Get calendar details
3. `calendar_create_calendar` -- Create a new calendar
4. `calendar_delete_calendar` -- Delete a calendar

### Event CRUD (5 tools)
5. `calendar_create_event` -- Create event with attendees, recurrence, online meeting
6. `calendar_get_event` -- Get event details
7. `calendar_update_event` -- Update event properties
8. `calendar_delete_event` -- Delete event
9. `calendar_list_events` -- List events in date range (calendarView)

### Event Responses (3 tools)
10. `calendar_accept_event` -- Accept meeting invitation
11. `calendar_decline_event` -- Decline meeting invitation
12. `calendar_tentatively_accept_event` -- Tentatively accept invitation

### Scheduling & Availability (2 tools)
13. `calendar_get_schedule` -- Get free/busy availability for users/rooms
14. `calendar_find_meeting_times` -- Suggest meeting times based on attendee availability

### Recurring Events (1 tool)
15. `calendar_list_event_instances` -- List instances of recurring event

### Event Actions (2 tools)
16. `calendar_forward_event` -- Forward event to recipients
17. `calendar_cancel_event` -- Cancel meeting and notify attendees

### Event Attachments (4 tools)
18. `calendar_add_event_attachment` -- Add file attachment to event
19. `calendar_list_event_attachments` -- List event attachments
20. `calendar_get_event_attachment` -- Get specific event attachment
21. `calendar_delete_event_attachment` -- Delete event attachment

### Event Reminders (2 tools)
22. `calendar_snooze_reminder` -- Snooze event reminder to new time
23. `calendar_dismiss_reminder` -- Dismiss event reminder

---

## Dependencies

| Package | Purpose | Already in project? |
|---------|---------|-------------------|
| `msal` | Microsoft authentication library (token management) | Yes (used by o365_tool) |
| `httpx` | Async HTTP client | Yes |

**No new dependencies required.** Calendar tools reuse the same `msal` + `httpx` stack as the existing O365 email integration.

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/tools/o365_helpers.py` | **New** | Extract shared Graph API helpers (_get_token, _get_http_client, _request, _get_user_id, _success, _recipients, _ensure_list) from o365_tool.py |
| `src/mcp_toolbox/tools/o365_tool.py` | Modify | Import helpers from o365_helpers.py instead of defining them locally; remove duplicated code |
| `src/mcp_toolbox/tools/calendar_tool.py` | **New** | All 23 calendar tools, importing shared helpers from o365_helpers.py |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Import and register calendar_tool |
| `tests/test_calendar_tool.py` | **New** | Tests for all 23 calendar tools |
| `tests/test_o365_tool.py` | Modify | Update imports to use shared helpers (ensure no regressions) |
| `tests/test_server.py` | Modify | Update tool count (224 + 23 = 247) and tool name list |
| `CLAUDE.md` | Modify | Document calendar integration |

---

## Testing Strategy

### Approach
Same pattern as O365 email tests -- mock both `msal` token acquisition and `httpx` HTTP calls:
- Use `unittest.mock.patch` for `msal.ConfidentialClientApplication.acquire_token_for_client`
- Use `respx` for Graph API HTTP mocking (already a dev dependency)

### Test Coverage
1. **Happy path for every tool** (23 tests minimum)
2. **Missing config** (tenant_id, client_id, etc.) raises ToolError
3. **Token acquisition failure** raises ToolError
4. **API errors** (401 Unauthorized, 403 Forbidden, 404 Not Found, 429 Rate Limited)
5. **Input normalization** (single string vs list for attendees/schedules)
6. **Date/time formatting** (ISO 8601 with timezone wrapping)
7. **Optional parameters** (create event with minimal vs full parameters)
8. **Calendar ID routing** (default calendar vs specific calendar_id)
9. **Event response tools** (accept/decline/tentative with and without comments)
10. **getSchedule validation** (max 20 entities, required time range)

### Test Structure
```
tests/test_calendar_tool.py
  TestCalendarManagement
    test_list_calendars
    test_get_calendar
    test_create_calendar
    test_delete_calendar
  TestEventCRUD
    test_create_event_minimal
    test_create_event_full
    test_create_event_with_recurrence
    test_get_event
    test_update_event
    test_delete_event
    test_list_events
    test_list_events_specific_calendar
  TestEventResponses
    test_accept_event
    test_decline_event
    test_decline_event_with_proposed_time
    test_tentatively_accept_event
  TestScheduling
    test_get_schedule
    test_get_schedule_single_user
    test_get_schedule_max_entities
    test_find_meeting_times
  TestRecurring
    test_list_event_instances
  TestEventActions
    test_forward_event
    test_cancel_event
  TestEventAttachments
    test_add_event_attachment
    test_list_event_attachments
    test_get_event_attachment
    test_delete_event_attachment
  TestEventReminders
    test_snooze_reminder
    test_dismiss_reminder
  TestErrorHandling
    test_missing_config
    test_token_failure
    test_api_error_404
    test_api_error_429
    test_update_no_fields
```

---

## Success Criteria

1. `uv sync` succeeds with no new dependency additions required
2. All **23 calendar tools** register and are discoverable via MCP
3. Shared O365 helpers extracted cleanly; existing O365 email tests still pass
4. Tools return meaningful ToolError when config is missing
5. Token management works via shared MSAL singleton (no duplicate token requests)
6. All new tests pass and full regression suite remains green
7. Total toolbox: **224 existing + 23 new = 247 tools**
