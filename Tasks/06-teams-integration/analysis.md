# Task 06: Microsoft Teams Integration - Analysis & Requirements

## Objective
Add Microsoft Teams capabilities via Microsoft Graph API as a tool integration in mcp-toolbox, reusing the existing O365 auth infrastructure.

---

## API Technical Details

### Same Microsoft Graph API v1.0
- **Base URL:** `https://graph.microsoft.com/v1.0` (same as O365 email)
- **Auth:** Same OAuth2 client credentials flow via `msal`
- **Token sharing:** A single access token works for both email and Teams — no new auth code needed
- **Additional permissions required:** Teams-specific permissions must be added to the existing Azure app registration (requires admin re-consent)

### App-Only Auth Limitations (Critical)

| Capability | App-Only | Notes |
|-----------|----------|-------|
| Read teams/channels/members | YES | Standard permissions |
| Manage teams/channels/members | YES | Standard permissions |
| Read channel messages | YES | `ChannelMessage.Read.All` |
| **Send channel messages** | **NO** | No application permission exists for this |
| Read chat messages | YES | `Chat.Read.All` |
| **Send chat messages** | **NO** | Impossible with app-only auth |
| **Create chats** | **NO** | Impossible with app-only auth |
| Create meetings | YES | Requires application access policy (admin setup) |
| Read/set presence | YES | Standard permissions |

**Important:** There is no application permission to send channel messages via Graph API. `ChannelMessage.Send` is delegated-only. `Teamwork.Migrate.All` exists but is exclusively for data migration (importing historical messages into locked channels), not live messaging.

### Channel Messaging — Power Automate Workflows
Since app-only auth cannot send channel messages via Graph API, the only viable approach is **Power Automate Workflows**:
- Admin creates a Workflow in Teams using the "When a Teams webhook request is received" trigger
- The workflow generates a unique webhook URL
- POST JSON payloads (Adaptive Cards) to the webhook URL
- No Graph API auth needed — the URL itself is the authentication
- **Note:** Legacy O365 Connector incoming webhooks were retired at end of 2025. Power Automate Workflows are the official replacement.

### Required Permissions (Application)

| Permission | Description | Admin Consent |
|-----------|-------------|---------------|
| `Team.ReadBasic.All` | Read teams | Required |
| `TeamMember.ReadWrite.All` | Manage team members | Required |
| `Channel.ReadBasic.All` | Read channels | Required |
| `Channel.Create` | Create channels | Required |
| `Channel.Delete.All` | Delete channels | Required |
| `ChannelMessage.Read.All` | Read channel messages | Required |
| `Chat.Read.All` | Read chats | Required |
| `OnlineMeetings.ReadWrite.All` | Manage meetings | Required |
| `Presence.Read.All` | Read presence | Required |

**Meetings prerequisite:** For app-only auth, a tenant admin must configure an **Application Access Policy** via `New-CsApplicationAccessPolicy` in Exchange Online PowerShell and grant it to the organizer user. Without this, all meeting API calls fail.

### Rate Limits (Teams-Specific)

| Resource | Limit | Per |
|----------|-------|-----|
| Channel messages (create) | 2 requests/second | Per app per channel |
| Chat messages (create) | 2 requests/second | Per app per chat |
| Team creation | 15 teams/15 seconds | Per app |
| Channel creation | 30 channels/15 seconds | Per app |
| Get channel messages | 5 requests/second | Per app per channel |
| General Graph API | 10,000 requests/10 min | Per app per tenant |

---

## Architecture Decisions

### A1: Reuse O365 Auth Infrastructure
The existing `o365_tool.py` already has `_get_token()`, `_get_http_client()`, `_get_user_id()`, and `_request()`. Since Teams uses the same Graph API and same token, we can:

**Option A (Shared module):** Extract common Graph helpers into a shared module and import from both o365_tool and teams_tool.

**Option B (Duplicate with import):** Import the helpers directly from o365_tool.

**Option C (Independent):** Copy the pattern into teams_tool.py with its own helpers. Simplest, no coupling, consistent with how sendgrid and clickup are independent.

**Decision: Option C — Independent module.** Keeps integrations decoupled. The helpers are small (~50 lines). If we refactor later, it's a simple extraction. This matches the existing pattern where each tool module is self-contained.

**Note:** The same Azure app registration and credentials are shared. If O365 is configured, Teams will work with the same `O365_TENANT_ID`, `O365_CLIENT_ID`, `O365_CLIENT_SECRET`. We add `TEAMS_` config variables that **default to the O365 values** if not set separately.

### A2: Config Variable Strategy
```python
# Teams can reuse O365 credentials or have its own
TEAMS_TENANT_ID: str | None = os.getenv("TEAMS_TENANT_ID") or O365_TENANT_ID
TEAMS_CLIENT_ID: str | None = os.getenv("TEAMS_CLIENT_ID") or O365_CLIENT_ID
TEAMS_CLIENT_SECRET: str | None = os.getenv("TEAMS_CLIENT_SECRET") or O365_CLIENT_SECRET
```

This means: if user has O365 configured, Teams works automatically. If they want separate credentials, they can set `TEAMS_*` vars.

### A3: Channel Messaging Strategy
Given the protected API limitation, we provide **two approaches:**
1. **Graph API tools** (`teams_send_channel_message`) — works if the org has `ChannelMessage.Send.All` approved. Raises clear ToolError if permission is denied.
2. **Webhook tool** (`teams_send_webhook_message`) — simple alternative using incoming webhook URLs, no special permissions needed.

### A4: Scope — What to Implement
Focus on capabilities that **work with app-only auth**:
- Teams/channels/members management
- Reading messages
- Channel messaging (Graph API + webhook fallback)
- Meetings
- Presence
- Tabs

**Exclude** (requires delegated auth):
- Sending chat messages (1:1 or group)
- Creating chats
- These would need a different auth flow (interactive user login)

---

## Configuration Requirements

### Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `TEAMS_TENANT_ID` | Entra ID tenant ID | No | Falls back to `O365_TENANT_ID` |
| `TEAMS_CLIENT_ID` | App client ID | No | Falls back to `O365_CLIENT_ID` |
| `TEAMS_CLIENT_SECRET` | App client secret | No | Falls back to `O365_CLIENT_SECRET` |

No new required config if O365 is already configured.

---

## Tool Specifications

### Teams Management (9 tools)

#### `teams_list_teams`
List teams in the organization.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `top` | int | No | Max results (default 50) |

**Returns:** List of teams with IDs, names, descriptions.
**Endpoint:** `GET /teams`

#### `teams_get_team`
Get team details.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |

**Returns:** Team details.
**Endpoint:** `GET /teams/{team_id}`

#### `teams_create_team`
Create a new team. With app-only auth, an owner must be specified.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `display_name` | str | Yes | Team name |
| `owner_id` | str | Yes | Azure AD user ID for the team owner |
| `description` | str | No | Team description |
| `visibility` | str | No | `public` or `private` (default `private`) |

**Returns:** Team creation response (async operation — returns location header).
**Endpoint:** `POST /teams`
**Note:** App-only auth requires at least one owner in the `members` array. The `owner_id` is included as an `aadUserConversationMember` with role `["owner"]`.

#### `teams_archive_team`
Archive a team (read-only mode).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |

**Returns:** Confirmation.
**Endpoint:** `POST /teams/{team_id}/archive`

#### `teams_list_members`
List team members.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |

**Returns:** List of members with IDs, names, roles.
**Endpoint:** `GET /teams/{team_id}/members`

#### `teams_add_member`
Add a member to a team.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |
| `user_id` | str | Yes | User ID (Azure AD object ID) |
| `role` | str | No | `member` or `owner` (default `member`) |

**Returns:** Added member details.
**Endpoint:** `POST /teams/{team_id}/members`

#### `teams_remove_member`
Remove a member from a team.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |
| `membership_id` | str | Yes | Membership ID (from list_members) |

**Returns:** Confirmation.
**Endpoint:** `DELETE /teams/{team_id}/members/{membership_id}`

#### `teams_update_team`
Update team settings.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |
| `display_name` | str | No | New team name |
| `description` | str | No | New description |
| `visibility` | str | No | `public` or `private` |

**Returns:** Updated team.
**Endpoint:** `PATCH /teams/{team_id}`

#### `teams_unarchive_team`
Unarchive a team (restore from read-only).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |

**Returns:** Confirmation.
**Endpoint:** `POST /teams/{team_id}/unarchive`

---

### Channel Management (5 tools)

#### `teams_list_channels`
List channels in a team.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |

**Returns:** List of channels with IDs, names, types.
**Endpoint:** `GET /teams/{team_id}/channels`

#### `teams_get_channel`
Get channel details.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |
| `channel_id` | str | Yes | Channel ID |

**Returns:** Channel details.
**Endpoint:** `GET /teams/{team_id}/channels/{channel_id}`

#### `teams_create_channel`
Create a channel in a team.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |
| `display_name` | str | Yes | Channel name |
| `description` | str | No | Channel description |
| `membership_type` | str | No | `standard`, `private`, or `shared` (default `standard`) |

**Returns:** Created channel.
**Endpoint:** `POST /teams/{team_id}/channels`

#### `teams_update_channel`
Update a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |
| `channel_id` | str | Yes | Channel ID |
| `display_name` | str | No | New channel name |
| `description` | str | No | New description |

**Returns:** Updated channel.
**Endpoint:** `PATCH /teams/{team_id}/channels/{channel_id}`

#### `teams_delete_channel`
Delete a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |
| `channel_id` | str | Yes | Channel ID |

**Returns:** Confirmation.
**Endpoint:** `DELETE /teams/{team_id}/channels/{channel_id}`

---

### Messaging (5 tools)

#### `teams_list_channel_messages`
List messages in a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |
| `channel_id` | str | Yes | Channel ID |
| `top` | int | No | Max results (default 20) |

**Returns:** List of messages.
**Endpoint:** `GET /teams/{team_id}/channels/{channel_id}/messages`

#### `teams_get_message`
Get a specific channel message.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |
| `channel_id` | str | Yes | Channel ID |
| `message_id` | str | Yes | Message ID |

**Returns:** Message details with body, sender, timestamp.
**Endpoint:** `GET /teams/{team_id}/channels/{channel_id}/messages/{message_id}`

#### `teams_list_message_replies`
List replies to a channel message.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |
| `channel_id` | str | Yes | Channel ID |
| `message_id` | str | Yes | Parent message ID |
| `top` | int | No | Max results (default 20) |

**Returns:** List of reply messages.
**Endpoint:** `GET /teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies`

#### `teams_send_webhook_message`
Send a message to a Teams channel via Power Automate Workflow webhook.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `webhook_url` | str | Yes | Power Automate Workflow webhook URL |
| `title` | str | No | Message title |
| `text` | str | No | Message text |
| `adaptive_card` | dict | No | Adaptive Card JSON payload |

One of `text` or `adaptive_card` required.
**Returns:** Confirmation.
**Note:** This does NOT use Graph API — it's a direct POST to the Workflow webhook URL. No Graph auth needed. Uses a separate httpx client (not the shared Graph API client) since the URL is a different domain.

**Important:** Legacy O365 Connector incoming webhooks were retired at end of 2025. This tool targets Power Automate Workflows, which are the official replacement. Admins must create a Workflow using the "When a Teams webhook request is received" trigger to obtain the webhook URL.

#### `teams_send_channel_message_delegated`
Send a message to a Teams channel (requires delegated auth — NOT supported with app-only client credentials).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `team_id` | str | Yes | Team ID |
| `channel_id` | str | Yes | Channel ID |
| `content` | str | Yes | Message body |
| `content_type` | str | No | `html` or `text` (default `html`) |

**Returns:** Created message.
**Endpoint:** `POST /teams/{team_id}/channels/{channel_id}/messages`
**Auth:** Requires `ChannelMessage.Send` **delegated** permission. This tool will return a clear ToolError explaining that delegated auth is required if called with app-only credentials. Included for completeness — functional only when the auth model is extended to support delegated flows in the future.

---

### Meetings (4 tools)

#### `teams_create_meeting`
Create an online meeting.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | str | Yes | Meeting subject |
| `start_time` | str | Yes | Start time (ISO datetime) |
| `end_time` | str | Yes | End time (ISO datetime) |
| `user_id` | str | No | Organizer (falls back to O365_USER_ID) |

**Returns:** Meeting details with join URL.
**Endpoint:** `POST /users/{user_id}/onlineMeetings`

#### `teams_list_meetings`
List online meetings for a user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | str | No | User (falls back to O365_USER_ID) |

**Returns:** List of meetings.
**Endpoint:** `GET /users/{user_id}/onlineMeetings`

#### `teams_get_meeting`
Get meeting details.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `meeting_id` | str | Yes | Meeting ID |
| `user_id` | str | No | Organizer |

**Returns:** Meeting details with participants, join info.
**Endpoint:** `GET /users/{user_id}/onlineMeetings/{meeting_id}`

#### `teams_delete_meeting`
Delete an online meeting.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `meeting_id` | str | Yes | Meeting ID |
| `user_id` | str | No | Organizer |

**Returns:** Confirmation.
**Endpoint:** `DELETE /users/{user_id}/onlineMeetings/{meeting_id}`

---

### Presence (2 tools)

#### `teams_get_presence`
Get a user's presence status.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | str | Yes | User ID |

**Returns:** Presence with availability (Available, Busy, DoNotDisturb, Away, Offline) and activity.
**Endpoint:** `GET /users/{user_id}/presence`

#### `teams_get_presence_bulk`
Get presence for multiple users.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_ids` | list[str] | Yes | User IDs |

**Returns:** List of presence statuses.
**Endpoint:** `POST /communications/getPresencesByUserId`

---

### Chat Reading (3 tools)

#### `teams_list_chats`
List chats for a user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | str | Yes | User ID |
| `top` | int | No | Max results (default 20) |

**Returns:** List of chats.
**Endpoint:** `GET /users/{user_id}/chats`

#### `teams_get_chat`
Get chat details.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `chat_id` | str | Yes | Chat ID |

**Returns:** Chat details with members.
**Endpoint:** `GET /chats/{chat_id}`

#### `teams_list_chat_messages`
List messages in a chat (read-only with app-only auth).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `chat_id` | str | Yes | Chat ID |
| `top` | int | No | Max results (default 20) |

**Returns:** List of messages.
**Endpoint:** `GET /chats/{chat_id}/messages`

---

## Tool Summary (28 tools total)

### Teams Management (9 tools)
1. `teams_list_teams` — List teams
2. `teams_get_team` — Get team details
3. `teams_create_team` — Create team (requires owner_id)
4. `teams_update_team` — Update team settings
5. `teams_archive_team` — Archive team
6. `teams_unarchive_team` — Unarchive team
7. `teams_list_members` — List team members
8. `teams_add_member` — Add team member
9. `teams_remove_member` — Remove team member

### Channel Management (5 tools)
10. `teams_list_channels` — List channels
11. `teams_get_channel` — Get channel details
12. `teams_create_channel` — Create channel
13. `teams_update_channel` — Update channel
14. `teams_delete_channel` — Delete channel

### Messaging (5 tools)
15. `teams_list_channel_messages` — List channel messages (read)
16. `teams_get_message` — Get specific message (read)
17. `teams_list_message_replies` — List message replies (read)
18. `teams_send_webhook_message` — Send via Power Automate Workflow webhook
19. `teams_send_channel_message_delegated` — Send via Graph API (delegated auth only — placeholder)

### Meetings (4 tools)
20. `teams_create_meeting` — Create online meeting (requires access policy)
21. `teams_list_meetings` — List meetings
22. `teams_get_meeting` — Get meeting details
23. `teams_delete_meeting` — Delete meeting

### Presence (2 tools)
24. `teams_get_presence` — Get user presence
25. `teams_get_presence_bulk` — Get multiple users' presence

### Chat Reading (3 tools)
26. `teams_list_chats` — List user's chats
27. `teams_get_chat` — Get chat details
28. `teams_list_chat_messages` — List chat messages (read-only)

---

## Dependencies

No new runtime dependencies — `msal` and `httpx` are already installed from the O365 integration. The webhook tool uses a plain `httpx` POST (no auth).

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/config.py` | Modify | Add TEAMS config with O365 fallbacks |
| `.env.example` | Modify | Add optional Teams variables |
| `src/mcp_toolbox/tools/teams_tool.py` | **New** | All Teams tools |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register teams_tool |
| `tests/test_teams_tool.py` | **New** | Tests for all 28 tools |
| `tests/test_server.py` | Modify | Update tool count to 144 |
| `CLAUDE.md` | Modify | Document Teams integration |
| `pyproject.toml` | Modify | Add teams_tool.py to pyright exclude (shares msal) |

---

## Testing Strategy

Same as O365:
- `respx` for Graph API HTTP mocking
- `unittest.mock.patch` for msal token mocking
- Webhook tool tested with `respx` against arbitrary URLs
- Happy path for every tool + auth/error tests

---

## Success Criteria

1. All 28 Teams tools register and are discoverable
2. Tools work with existing O365 credentials (no new config needed if O365 is set up)
3. Webhook messaging works without Graph API auth
4. Channel messaging via Graph API returns clear error if permission not granted
5. New tests pass and full regression suite remains green
6. Total toolbox: 116 existing + 28 new = **144 tools**
