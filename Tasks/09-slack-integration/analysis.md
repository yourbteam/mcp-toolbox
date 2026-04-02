# Task 09: Slack Integration - Analysis & Requirements

## Objective
Add Slack messaging and workspace management as a tool integration in mcp-toolbox.

---

## API Technical Details

### Slack Web API
- **Base URL:** `https://slack.com/api/{method_name}`
- **Style:** RPC-style POST requests (all methods are POST)
- **Auth:** Bot token via `Authorization: Bearer xoxb-...`
- **Format:** JSON request/response

### Authentication — Bot Token (Simplest)
For a single-workspace MCP server, a bot token (`xoxb-...`) is all that's needed:
1. Create app at https://api.slack.com/apps
2. Add bot scopes under "OAuth & Permissions"
3. Install to workspace
4. Copy `xoxb-...` token

No OAuth2 flow needed. Token does not expire (unless revoked).

### Rate Limits

| Tier | Requests/Minute | Typical Methods |
|------|-----------------|-----------------|
| Tier 1 | 1+ | Infrequent methods |
| Tier 2 | 20+ | Most read methods |
| Tier 3 | 50+ | Paginated collections (history, users.list) |
| Tier 4 | 100+ | Generous burst |
| Special | ~1 msg/sec/channel | chat.postMessage |

HTTP 429 with `Retry-After` header on throttle. Internal (non-Marketplace) apps get Tier 3 rates.

### Pagination
Cursor-based. Response includes `response_metadata.next_cursor`. Pass as `cursor` param. Single page per tool call — consistent with our other integrations.

### Key Limitation
`search.messages` requires a **user token** (`xoxp-`), not a bot token. We exclude search from this integration since we use bot tokens.

---

## Architecture Decisions

### A1: slack_sdk with asyncio.to_thread (no AsyncWebClient)
The official `slack_sdk` package provides `WebClient` (sync) and `AsyncWebClient` (async, requires `aiohttp`). To avoid adding `aiohttp` as a dependency alongside `httpx`, we use the sync `WebClient` wrapped in `asyncio.to_thread()` — same pattern as boto3 and msal.

### A2: Simple Bot Token Config
Single environment variable:
```python
SLACK_BOT_TOKEN: str | None = os.getenv("SLACK_BOT_TOKEN")
```

### A3: WebClient as Singleton
```python
from slack_sdk import WebClient

_slack_client: WebClient | None = None

def _get_client() -> WebClient:
    if not SLACK_BOT_TOKEN:
        raise ToolError("SLACK_BOT_TOKEN not configured.")
    global _slack_client
    if _slack_client is None:
        _slack_client = WebClient(token=SLACK_BOT_TOKEN)
    return _slack_client
```

### A4: Error Handling
`slack_sdk` raises `SlackApiError` with a parsed response. Convert to `ToolError`:
```python
from slack_sdk.errors import SlackApiError

try:
    result = await asyncio.to_thread(client.chat_postMessage, channel=channel, text=text)
except SlackApiError as e:
    raise ToolError(f"Slack error ({e.response['error']}): {e.response.get('message', '')}") from e
```

### A5: Response Format
Same JSON convention. Slack responses include metadata we can pass through.

### A6: Pagination
Tools return single page. Include `next_cursor` in response when available so callers can paginate.

---

## Configuration Requirements

### Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `SLACK_BOT_TOKEN` | Bot token (`xoxb-...`) | Yes (at invocation) | `None` |

---

## Tool Specifications

### Messaging (7 tools)

#### `slack_send_message`
Send a message to a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID or name |
| `text` | str | Yes | Message text (mrkdwn supported) |
| `blocks` | list[dict] | No | Block Kit blocks (rich formatting) |
| `thread_ts` | str | No | Thread timestamp (reply to thread) |
| `unfurl_links` | bool | No | Unfurl URLs (default true) |

**Returns:** Message timestamp (`ts`), channel.
**API:** `chat.postMessage`

#### `slack_send_dm`
Send a direct message to a user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | str | Yes | User ID (e.g., U12345) |
| `text` | str | Yes | Message text |
| `blocks` | list[dict] | No | Block Kit blocks |

**Returns:** Message timestamp, channel.
**API:** `conversations.open` + `chat.postMessage`

#### `slack_update_message`
Update an existing message.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `ts` | str | Yes | Message timestamp to update |
| `text` | str | Yes | New message text |
| `blocks` | list[dict] | No | New blocks |

**Returns:** Updated message timestamp.
**API:** `chat.update`

#### `slack_delete_message`
Delete a message (bot can only delete its own).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `ts` | str | Yes | Message timestamp to delete |

**Returns:** Confirmation.
**API:** `chat.delete`

#### `slack_schedule_message`
Schedule a message for future delivery.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `text` | str | Yes | Message text |
| `post_at` | int | Yes | Unix timestamp for delivery |
| `blocks` | list[dict] | No | Block Kit blocks |

**Returns:** Scheduled message ID.
**API:** `chat.scheduleMessage`

#### `slack_get_channel_history`
List messages in a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `limit` | int | No | Max results (default 20, max 1000) |
| `cursor` | str | No | Pagination cursor |
| `oldest` | str | No | Start of time range (Unix ts) |
| `latest` | str | No | End of time range (Unix ts) |

**Returns:** List of messages, `next_cursor`.
**API:** `conversations.history`

#### `slack_get_thread_replies`
List replies in a thread.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `ts` | str | Yes | Thread parent timestamp |
| `limit` | int | No | Max results (default 20) |
| `cursor` | str | No | Pagination cursor |

**Returns:** List of reply messages, `next_cursor`.
**API:** `conversations.replies`

---

### Channel Management (9 tools)

#### `slack_list_channels`
List channels in the workspace.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `types` | str | No | Channel types: `public_channel,private_channel` (default `public_channel`) |
| `limit` | int | No | Max results (default 100) |
| `cursor` | str | No | Pagination cursor |

**Returns:** List of channels, `next_cursor`.
**API:** `conversations.list`

#### `slack_get_channel_info`
Get channel details.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |

**Returns:** Channel info (name, topic, purpose, members count).
**API:** `conversations.info`

#### `slack_create_channel`
Create a new channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Channel name (lowercase, no spaces) |
| `is_private` | bool | No | Create as private channel (default false) |

**Returns:** Created channel.
**API:** `conversations.create`

#### `slack_archive_channel`
Archive a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |

**Returns:** Confirmation.
**API:** `conversations.archive`

#### `slack_unarchive_channel`
Unarchive a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |

**Returns:** Confirmation.
**API:** `conversations.unarchive`

#### `slack_invite_to_channel`
Invite users to a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `users` | str | Yes | Comma-separated user IDs |

**Returns:** Channel info.
**API:** `conversations.invite`

#### `slack_set_channel_topic`
Set a channel's topic.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `topic` | str | Yes | New topic text |

**Returns:** Updated topic.
**API:** `conversations.setTopic`

#### `slack_list_channel_members`
List members of a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `limit` | int | No | Max results (default 100) |
| `cursor` | str | No | Pagination cursor |

**Returns:** List of user IDs, `next_cursor`.
**API:** `conversations.members`

#### `slack_set_channel_purpose`
Set a channel's purpose.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `purpose` | str | Yes | New purpose text |

**Returns:** Updated purpose.
**API:** `conversations.setPurpose`

---

### Users (4 tools)

#### `slack_list_users`
List workspace members.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Max results (default 100) |
| `cursor` | str | No | Pagination cursor |

**Returns:** List of users, `next_cursor`.
**API:** `users.list`

#### `slack_get_user_info`
Get user details.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user` | str | Yes | User ID |

**Returns:** User profile (name, email, status, avatar).
**API:** `users.info`

#### `slack_find_user_by_email`
Look up a user by email address.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | str | Yes | Email address |

**Returns:** User profile.
**API:** `users.lookupByEmail`

#### `slack_get_user_presence`
Get a user's presence status.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user` | str | Yes | User ID |

**Returns:** Presence (active/away), online status.
**API:** `users.getPresence`

---

### Reactions (3 tools)

#### `slack_add_reaction`
Add an emoji reaction to a message.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `timestamp` | str | Yes | Message timestamp |
| `name` | str | Yes | Emoji name (without colons, e.g., `thumbsup`) |

**Returns:** Confirmation.
**API:** `reactions.add`

#### `slack_remove_reaction`
Remove an emoji reaction.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `timestamp` | str | Yes | Message timestamp |
| `name` | str | Yes | Emoji name |

**Returns:** Confirmation.
**API:** `reactions.remove`

#### `slack_get_reactions`
Get reactions on a message.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `timestamp` | str | Yes | Message timestamp |

**Returns:** List of reactions with counts and users.
**API:** `reactions.get`

---

### Pins (3 tools)

#### `slack_pin_message`
Pin a message in a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `timestamp` | str | Yes | Message timestamp |

**Returns:** Confirmation.
**API:** `pins.add`

#### `slack_unpin_message`
Unpin a message.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |
| `timestamp` | str | Yes | Message timestamp |

**Returns:** Confirmation.
**API:** `pins.remove`

#### `slack_list_pins`
List pinned items in a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID |

**Returns:** List of pinned items.
**API:** `pins.list`

---

### Files (2 tools)

#### `slack_upload_file`
Upload a file to a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel` | str | Yes | Channel ID to share in |
| `file_path` | str | Yes | Local file path |
| `title` | str | No | File title |
| `initial_comment` | str | No | Comment with the file |

**Returns:** File details.
**API:** `files_upload_v2` (SDK convenience method)

#### `slack_delete_file`
Delete a file.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | File ID |

**Returns:** Confirmation.
**API:** `files.delete`

---

## Tool Summary (28 tools total)

### Messaging (7 tools)
1. `slack_send_message` — Send to channel
2. `slack_send_dm` — Send DM to user
3. `slack_update_message` — Update message
4. `slack_delete_message` — Delete message
5. `slack_schedule_message` — Schedule message
6. `slack_get_channel_history` — List channel messages
7. `slack_get_thread_replies` — List thread replies

### Channel Management (9 tools)
8. `slack_list_channels` — List channels
9. `slack_get_channel_info` — Get channel details
10. `slack_create_channel` — Create channel
11. `slack_archive_channel` — Archive channel
12. `slack_unarchive_channel` — Unarchive channel
13. `slack_invite_to_channel` — Invite users
14. `slack_list_channel_members` — List channel members
15. `slack_set_channel_topic` — Set topic
16. `slack_set_channel_purpose` — Set purpose

### Users (4 tools)
17. `slack_list_users` — List workspace members
18. `slack_get_user_info` — Get user details
19. `slack_find_user_by_email` — Lookup by email
20. `slack_get_user_presence` — Get presence

### Reactions (3 tools)
21. `slack_add_reaction` — Add emoji reaction
22. `slack_remove_reaction` — Remove reaction
23. `slack_get_reactions` — Get reactions on message

### Pins (3 tools)
24. `slack_pin_message` — Pin message
25. `slack_unpin_message` — Unpin message
26. `slack_list_pins` — List pinned items

### Files (2 tools)
27. `slack_upload_file` — Upload file
28. `slack_delete_file` — Delete file

---

## Dependencies

| Package | Purpose | Already in project? |
|---------|---------|-------------------|
| `slack-sdk` | Official Slack Python SDK | **New** — add to runtime deps |

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Modify | Add `slack-sdk>=3.30.0` to deps, add to pyright exclude |
| `src/mcp_toolbox/config.py` | Modify | Add `SLACK_BOT_TOKEN` |
| `.env.example` | Modify | Add Slack token |
| `src/mcp_toolbox/tools/slack_tool.py` | **New** | All Slack tools |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register slack_tool |
| `tests/test_slack_tool.py` | **New** | Tests for all 28 tools |
| `tests/test_server.py` | Modify | Update tool count to 224 |
| `CLAUDE.md` | Modify | Document Slack integration |

---

## Testing Strategy

Mock the `slack_sdk.WebClient` methods via `unittest.mock.patch`. No respx needed — SDK handles HTTP internally.

```python
@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_client = MagicMock()
    with patch("mcp_toolbox.tools.slack_tool.SLACK_BOT_TOKEN", "xoxb-test"), \
         patch("mcp_toolbox.tools.slack_tool._slack_client", mock_client):
        register_tools(mcp)
        yield mcp, mock_client
```

### Test Coverage
1. Happy path for every tool
2. Missing token → ToolError
3. SlackApiError handling
4. File upload with tmp_path

---

## Success Criteria

1. `uv sync` installs `slack-sdk` without errors
2. All 28 Slack tools register and are discoverable
3. Tools return meaningful errors when token is missing
4. SlackApiError properly converted to ToolError
5. New tests pass and full regression suite remains green
6. Total toolbox: 196 existing + 28 new = **224 tools**
