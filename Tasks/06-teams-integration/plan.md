# Task 06: Microsoft Teams Integration - Implementation Plan

## Overview
Implement 28 Teams tools using Microsoft Graph API, reusing the same `msal` + `httpx` pattern from O365 email. Self-contained module with O365 config fallbacks.

**Final state:** 144 tools total (116 existing + 28 new).

---

## Step 1: Configuration

### 1a. Add Teams config to `src/mcp_toolbox/config.py`
Append after O365 variables:
```python
# Microsoft Teams (reuses O365 credentials if not set separately)
TEAMS_TENANT_ID: str | None = os.getenv("TEAMS_TENANT_ID") or O365_TENANT_ID
TEAMS_CLIENT_ID: str | None = os.getenv("TEAMS_CLIENT_ID") or O365_CLIENT_ID
TEAMS_CLIENT_SECRET: str | None = os.getenv("TEAMS_CLIENT_SECRET") or O365_CLIENT_SECRET
```

### 1b. Update `.env.example`
```env
# Microsoft Teams Integration (optional — falls back to O365 credentials)
# TEAMS_TENANT_ID=your-tenant-id
# TEAMS_CLIENT_ID=your-client-id
# TEAMS_CLIENT_SECRET=your-client-secret
```

### 1c. Add pyright exclusion in `pyproject.toml`
```toml
exclude = ["src/mcp_toolbox/tools/sendgrid_tool.py", "src/mcp_toolbox/tools/o365_tool.py", "src/mcp_toolbox/tools/teams_tool.py"]
```

---

## Step 2: Tool Module Foundation

Create `src/mcp_toolbox/tools/teams_tool.py`:

```python
"""Microsoft Teams integration — teams, channels, messages, meetings, presence via Graph."""

import asyncio
import json
import logging

import httpx
import msal
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import (
    TEAMS_CLIENT_ID,
    TEAMS_CLIENT_SECRET,
    TEAMS_TENANT_ID,
)
from mcp_toolbox.config import O365_USER_ID

logger = logging.getLogger(__name__)

_msal_app: msal.ConfidentialClientApplication | None = None
_http_client: httpx.AsyncClient | None = None


def _get_token() -> str:
    """Acquire an OAuth2 token via client credentials. Sync — call via asyncio.to_thread."""
    global _msal_app
    if not TEAMS_TENANT_ID or not TEAMS_CLIENT_ID or not TEAMS_CLIENT_SECRET:
        raise ToolError(
            "Teams credentials not configured. Set TEAMS_TENANT_ID, "
            "TEAMS_CLIENT_ID, TEAMS_CLIENT_SECRET (or O365 equivalents) "
            "in your environment."
        )
    if _msal_app is None:
        _msal_app = msal.ConfidentialClientApplication(
            client_id=TEAMS_CLIENT_ID,
            client_credential=TEAMS_CLIENT_SECRET,
            authority=f"https://login.microsoftonline.com/{TEAMS_TENANT_ID}",
        )
    result = _msal_app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        raise ToolError(
            f"Failed to acquire Teams token: "
            f"{result.get('error_description', result.get('error', 'unknown error'))}"
        )
    return result["access_token"]


def _get_http_client() -> httpx.AsyncClient:
    """Get or create the singleton httpx client for Graph API."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url="https://graph.microsoft.com/v1.0",
            timeout=30.0,
        )
    return _http_client


def _get_user_id(override: str | None = None) -> str:
    """Resolve user ID: override > O365_USER_ID > error."""
    user_id = override or O365_USER_ID
    if not user_id:
        raise ToolError(
            "No user_id provided. Either pass user_id or set "
            "O365_USER_ID in your environment."
        )
    return user_id


def _success(status_code: int, **kwargs) -> str:
    """Build a success JSON response."""
    return json.dumps({"status": "success", "status_code": status_code, **kwargs})


async def _request(method: str, path: str, **kwargs) -> dict | list:
    """Make an authenticated Graph API request with error handling."""
    token = await asyncio.to_thread(_get_token)
    client = _get_http_client()
    try:
        response = await client.request(
            method, path,
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
    except httpx.HTTPError as e:
        raise ToolError(f"Teams Graph API request failed: {e}") from e

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        raise ToolError(
            f"Teams rate limit exceeded. Retry after {retry_after} seconds."
        )

    if response.status_code >= 400:
        try:
            error_body = response.json()
            error_info = error_body.get("error", {})
            error_msg = error_info.get("message", response.text)
            error_code = error_info.get("code", "")
        except Exception:
            error_msg = response.text
            error_code = ""
        raise ToolError(
            f"Teams Graph API error ({response.status_code}"
            f"{f' {error_code}' if error_code else ''}): {error_msg}"
        )

    if response.status_code in (202, 204):
        return {}

    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def register_tools(mcp: FastMCP) -> None:
    """Register all Teams tools with the MCP server."""

    if not TEAMS_CLIENT_ID:
        logger.warning(
            "Teams credentials not set — Teams tools will be registered "
            "but will fail at invocation until configured."
        )

    # --- Teams Management (Step 3) ---
    # --- Channel Management (Step 4) ---
    # --- Messaging (Step 5) ---
    # --- Meetings (Step 6) ---
    # --- Presence (Step 7) ---
    # --- Chat Reading (Step 8) ---
```

---

## Step 3: Teams Management (9 tools)

```python
    @mcp.tool()
    async def teams_list_teams(top: int = 50) -> str:
        """List teams in the organization.

        Args:
            top: Max results (default 50)
        """
        data = await _request("GET", "/teams", params={"$top": str(top)})
        teams = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=teams, count=len(teams))

    @mcp.tool()
    async def teams_get_team(team_id: str) -> str:
        """Get team details.

        Args:
            team_id: Team ID
        """
        data = await _request("GET", f"/teams/{team_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def teams_create_team(
        display_name: str,
        owner_id: str,
        description: str | None = None,
        visibility: str = "private",
    ) -> str:
        """Create a new team. Requires an owner with app-only auth.

        Args:
            display_name: Team name
            owner_id: Azure AD user ID for the team owner
            description: Team description
            visibility: 'public' or 'private' (default private)
        """
        body: dict = {
            "template@odata.bind":
                "https://graph.microsoft.com/v1.0/teamsTemplates('standard')",
            "displayName": display_name,
            "visibility": visibility,
            "members": [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind":
                        f"https://graph.microsoft.com/v1.0/users('{owner_id}')",
                }
            ],
        }
        if description is not None:
            body["description"] = description

        logger.info("Creating team '%s' with owner %s", display_name, owner_id)
        data = await _request("POST", "/teams", json=body)
        return _success(202, message="Team creation initiated", data=data)

    @mcp.tool()
    async def teams_update_team(
        team_id: str,
        display_name: str | None = None,
        description: str | None = None,
        visibility: str | None = None,
    ) -> str:
        """Update team settings.

        Args:
            team_id: Team ID
            display_name: New team name
            description: New description
            visibility: 'public' or 'private'
        """
        body: dict = {}
        if display_name is not None:
            body["displayName"] = display_name
        if description is not None:
            body["description"] = description
        if visibility is not None:
            body["visibility"] = visibility
        if not body:
            raise ToolError("At least one field to update must be provided.")
        await _request("PATCH", f"/teams/{team_id}", json=body)
        return _success(204, message="Team updated")

    @mcp.tool()
    async def teams_archive_team(team_id: str) -> str:
        """Archive a team (set to read-only).

        Args:
            team_id: Team ID
        """
        await _request("POST", f"/teams/{team_id}/archive", json={})
        return _success(202, message="Team archive initiated")

    @mcp.tool()
    async def teams_unarchive_team(team_id: str) -> str:
        """Unarchive a team (restore from read-only).

        Args:
            team_id: Team ID
        """
        await _request("POST", f"/teams/{team_id}/unarchive", json={})
        return _success(202, message="Team unarchive initiated")

    @mcp.tool()
    async def teams_list_members(team_id: str) -> str:
        """List team members.

        Args:
            team_id: Team ID
        """
        data = await _request("GET", f"/teams/{team_id}/members")
        members = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=members, count=len(members))

    @mcp.tool()
    async def teams_add_member(
        team_id: str,
        user_id: str,
        role: str = "member",
    ) -> str:
        """Add a member to a team.

        Args:
            team_id: Team ID
            user_id: Azure AD user ID
            role: 'member' or 'owner' (default member)
        """
        body = {
            "@odata.type": "#microsoft.graph.aadUserConversationMember",
            "roles": [role] if role == "owner" else [],
            "user@odata.bind":
                f"https://graph.microsoft.com/v1.0/users('{user_id}')",
        }
        data = await _request("POST", f"/teams/{team_id}/members", json=body)
        return _success(201, data=data)

    @mcp.tool()
    async def teams_remove_member(team_id: str, membership_id: str) -> str:
        """Remove a member from a team.

        Args:
            team_id: Team ID
            membership_id: Membership ID (from teams_list_members)
        """
        await _request("DELETE", f"/teams/{team_id}/members/{membership_id}")
        return _success(204, message="Member removed")
```

---

## Step 4: Channel Management (5 tools)

```python
    @mcp.tool()
    async def teams_list_channels(team_id: str) -> str:
        """List channels in a team.

        Args:
            team_id: Team ID
        """
        data = await _request("GET", f"/teams/{team_id}/channels")
        channels = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=channels, count=len(channels))

    @mcp.tool()
    async def teams_get_channel(team_id: str, channel_id: str) -> str:
        """Get channel details.

        Args:
            team_id: Team ID
            channel_id: Channel ID
        """
        data = await _request("GET", f"/teams/{team_id}/channels/{channel_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def teams_create_channel(
        team_id: str,
        display_name: str,
        description: str | None = None,
        membership_type: str = "standard",
    ) -> str:
        """Create a channel in a team.

        Args:
            team_id: Team ID
            display_name: Channel name
            description: Channel description
            membership_type: 'standard', 'private', or 'shared' (default standard)
        """
        body: dict = {
            "displayName": display_name,
            "membershipType": membership_type,
        }
        if description is not None:
            body["description"] = description
        data = await _request("POST", f"/teams/{team_id}/channels", json=body)
        return _success(201, data=data)

    @mcp.tool()
    async def teams_update_channel(
        team_id: str,
        channel_id: str,
        display_name: str | None = None,
        description: str | None = None,
    ) -> str:
        """Update a channel.

        Args:
            team_id: Team ID
            channel_id: Channel ID
            display_name: New channel name
            description: New description
        """
        body: dict = {}
        if display_name is not None:
            body["displayName"] = display_name
        if description is not None:
            body["description"] = description
        if not body:
            raise ToolError("At least one field to update must be provided.")
        await _request(
            "PATCH", f"/teams/{team_id}/channels/{channel_id}", json=body
        )
        return _success(204, message="Channel updated")

    @mcp.tool()
    async def teams_delete_channel(team_id: str, channel_id: str) -> str:
        """Delete a channel.

        Args:
            team_id: Team ID
            channel_id: Channel ID
        """
        await _request("DELETE", f"/teams/{team_id}/channels/{channel_id}")
        return _success(204, message="Channel deleted")
```

---

## Step 5: Messaging (5 tools)

```python
    @mcp.tool()
    async def teams_list_channel_messages(
        team_id: str,
        channel_id: str,
        top: int = 20,
    ) -> str:
        """List messages in a Teams channel.

        Args:
            team_id: Team ID
            channel_id: Channel ID
            top: Max results (default 20)
        """
        data = await _request(
            "GET", f"/teams/{team_id}/channels/{channel_id}/messages",
            params={"$top": str(top)},
        )
        messages = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=messages, count=len(messages))

    @mcp.tool()
    async def teams_get_message(
        team_id: str,
        channel_id: str,
        message_id: str,
    ) -> str:
        """Get a specific channel message.

        Args:
            team_id: Team ID
            channel_id: Channel ID
            message_id: Message ID
        """
        data = await _request(
            "GET",
            f"/teams/{team_id}/channels/{channel_id}/messages/{message_id}",
        )
        return _success(200, data=data)

    @mcp.tool()
    async def teams_list_message_replies(
        team_id: str,
        channel_id: str,
        message_id: str,
        top: int = 20,
    ) -> str:
        """List replies to a channel message.

        Args:
            team_id: Team ID
            channel_id: Channel ID
            message_id: Parent message ID
            top: Max results (default 20)
        """
        data = await _request(
            "GET",
            f"/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies",
            params={"$top": str(top)},
        )
        replies = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=replies, count=len(replies))

    @mcp.tool()
    async def teams_send_webhook_message(
        webhook_url: str,
        title: str | None = None,
        text: str | None = None,
        adaptive_card: dict | None = None,
    ) -> str:
        """Send a message to a Teams channel via Power Automate Workflow webhook.

        Args:
            webhook_url: Power Automate Workflow webhook URL
            title: Message title (for simple text messages)
            text: Message text (for simple text messages)
            adaptive_card: Adaptive Card JSON payload (alternative to text)
        """
        if not text and not adaptive_card:
            raise ToolError("Either 'text' or 'adaptive_card' must be provided.")

        if adaptive_card:
            payload = {
                "type": "message",
                "attachments": [
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "contentUrl": None,
                        "content": adaptive_card,
                    }
                ],
            }
        else:
            payload: dict = {}
            if title:
                payload["title"] = title
            if text:
                payload["text"] = text

        # Use a separate client — webhook URLs are NOT graph.microsoft.com
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(webhook_url, json=payload)
            except httpx.HTTPError as e:
                raise ToolError(f"Webhook request failed: {e}") from e

        if response.status_code >= 400:
            raise ToolError(
                f"Webhook error ({response.status_code}): {response.text}"
            )
        return _success(response.status_code, message="Webhook message sent")

    @mcp.tool()
    async def teams_send_channel_message_delegated(
        team_id: str,
        channel_id: str,
        content: str,
        content_type: str = "html",
    ) -> str:
        """Send a message to a Teams channel (requires delegated auth).

        NOTE: This tool requires ChannelMessage.Send delegated permission.
        It will NOT work with app-only client credentials. It is included
        as a placeholder for future delegated auth support.

        Args:
            team_id: Team ID
            channel_id: Channel ID
            content: Message body
            content_type: 'html' or 'text' (default html)
        """
        raise ToolError(
            "teams_send_channel_message_delegated requires delegated "
            "(user-interactive) authentication. App-only client credentials "
            "cannot send channel messages via Graph API. Use "
            "teams_send_webhook_message with a Power Automate Workflow "
            "webhook URL instead."
        )
```

---

## Step 6: Meetings (4 tools)

```python
    @mcp.tool()
    async def teams_create_meeting(
        subject: str,
        start_time: str,
        end_time: str,
        user_id: str | None = None,
    ) -> str:
        """Create an online Teams meeting.

        Requires an Application Access Policy configured by a tenant admin.

        Args:
            subject: Meeting subject
            start_time: Start time (ISO datetime, e.g., '2025-06-15T10:00:00Z')
            end_time: End time (ISO datetime)
            user_id: Organizer (falls back to O365_USER_ID)
        """
        uid = _get_user_id(user_id)
        body = {
            "subject": subject,
            "startDateTime": start_time,
            "endDateTime": end_time,
        }
        data = await _request("POST", f"/users/{uid}/onlineMeetings", json=body)
        return _success(201, data=data)

    @mcp.tool()
    async def teams_list_meetings(user_id: str | None = None) -> str:
        """List online meetings for a user.

        Args:
            user_id: User (falls back to O365_USER_ID)
        """
        uid = _get_user_id(user_id)
        data = await _request("GET", f"/users/{uid}/onlineMeetings")
        meetings = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=meetings, count=len(meetings))

    @mcp.tool()
    async def teams_get_meeting(
        meeting_id: str,
        user_id: str | None = None,
    ) -> str:
        """Get Teams meeting details.

        Args:
            meeting_id: Meeting ID
            user_id: Organizer (falls back to O365_USER_ID)
        """
        uid = _get_user_id(user_id)
        data = await _request(
            "GET", f"/users/{uid}/onlineMeetings/{meeting_id}"
        )
        return _success(200, data=data)

    @mcp.tool()
    async def teams_delete_meeting(
        meeting_id: str,
        user_id: str | None = None,
    ) -> str:
        """Delete a Teams online meeting.

        Args:
            meeting_id: Meeting ID
            user_id: Organizer (falls back to O365_USER_ID)
        """
        uid = _get_user_id(user_id)
        await _request("DELETE", f"/users/{uid}/onlineMeetings/{meeting_id}")
        return _success(204, message="Meeting deleted")
```

---

## Step 7: Presence (2 tools)

```python
    @mcp.tool()
    async def teams_get_presence(user_id: str) -> str:
        """Get a user's Teams presence status.

        Args:
            user_id: User ID
        """
        data = await _request("GET", f"/users/{user_id}/presence")
        return _success(200, data=data)

    @mcp.tool()
    async def teams_get_presence_bulk(user_ids: list[str]) -> str:
        """Get Teams presence for multiple users.

        Args:
            user_ids: List of user IDs
        """
        data = await _request(
            "POST", "/communications/getPresencesByUserId",
            json={"ids": user_ids},
        )
        presences = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=presences, count=len(presences))
```

---

## Step 8: Chat Reading (3 tools)

```python
    @mcp.tool()
    async def teams_list_chats(user_id: str, top: int = 20) -> str:
        """List chats for a user (read-only with app-only auth).

        Args:
            user_id: User ID
            top: Max results (default 20)
        """
        data = await _request(
            "GET", f"/users/{user_id}/chats", params={"$top": str(top)}
        )
        chats = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=chats, count=len(chats))

    @mcp.tool()
    async def teams_get_chat(chat_id: str) -> str:
        """Get chat details.

        Args:
            chat_id: Chat ID
        """
        data = await _request("GET", f"/chats/{chat_id}")
        return _success(200, data=data)

    @mcp.tool()
    async def teams_list_chat_messages(chat_id: str, top: int = 20) -> str:
        """List messages in a chat (read-only with app-only auth).

        Args:
            chat_id: Chat ID
            top: Max results (default 20)
        """
        data = await _request(
            "GET", f"/chats/{chat_id}/messages", params={"$top": str(top)}
        )
        messages = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=messages, count=len(messages))
```

---

## Step 9: Registration

### 9a. Update `src/mcp_toolbox/tools/__init__.py`
```python
from mcp_toolbox.tools import clickup_tool, example_tool, o365_tool, sendgrid_tool, teams_tool


def register_all_tools(mcp: FastMCP) -> None:
    """Register all tool modules with the MCP server."""
    example_tool.register_tools(mcp)
    sendgrid_tool.register_tools(mcp)
    clickup_tool.register_tools(mcp)
    o365_tool.register_tools(mcp)
    teams_tool.register_tools(mcp)
```

---

## Step 10: Tests

Create `tests/test_teams_tool.py`. Same pattern as O365 — mock msal + respx for Graph, separate respx for webhooks.

### 10a. Fixtures

```python
"""Tests for Microsoft Teams tool integration."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.teams_tool import register_tools

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _get_result_data(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_msal = MagicMock()
    mock_msal.acquire_token_for_client.return_value = {"access_token": "test-token"}
    with patch("mcp_toolbox.tools.teams_tool.TEAMS_TENANT_ID", "tenant_t"), \
         patch("mcp_toolbox.tools.teams_tool.TEAMS_CLIENT_ID", "client_t"), \
         patch("mcp_toolbox.tools.teams_tool.TEAMS_CLIENT_SECRET", "secret_t"), \
         patch("mcp_toolbox.tools.teams_tool.O365_USER_ID", "user@example.com"), \
         patch("mcp_toolbox.tools.teams_tool._msal_app", mock_msal), \
         patch("mcp_toolbox.tools.teams_tool._http_client", None):
        register_tools(mcp)
        yield mcp
```

### 10b. Auth & Error Tests

```python
@pytest.mark.asyncio
async def test_missing_credentials():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.teams_tool.TEAMS_TENANT_ID", None), \
         patch("mcp_toolbox.tools.teams_tool.TEAMS_CLIENT_ID", None), \
         patch("mcp_toolbox.tools.teams_tool.TEAMS_CLIENT_SECRET", None), \
         patch("mcp_toolbox.tools.teams_tool.O365_USER_ID", "u@e.com"), \
         patch("mcp_toolbox.tools.teams_tool._msal_app", None), \
         patch("mcp_toolbox.tools.teams_tool._http_client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="Teams credentials not configured"):
            await mcp.call_tool("teams_list_teams", {})


@pytest.mark.asyncio
@respx.mock
async def test_api_error_401(server):
    respx.get(f"{GRAPH_BASE}/teams").mock(
        return_value=httpx.Response(401, json={
            "error": {"code": "Unauthorized", "message": "Invalid token"}
        })
    )
    with pytest.raises(Exception, match="Teams Graph API error.*401"):
        await server.call_tool("teams_list_teams", {})


@pytest.mark.asyncio
@respx.mock
async def test_api_error_429(server):
    respx.get(f"{GRAPH_BASE}/teams").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "10"})
    )
    with pytest.raises(Exception, match="rate limit.*10 seconds"):
        await server.call_tool("teams_list_teams", {})
```

### 10c. Teams Management Tests (9 tools)

```python
@pytest.mark.asyncio
@respx.mock
async def test_list_teams(server):
    respx.get(f"{GRAPH_BASE}/teams").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "t1"}]})
    )
    result = await server.call_tool("teams_list_teams", {})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_get_team(server):
    respx.get(f"{GRAPH_BASE}/teams/t1").mock(
        return_value=httpx.Response(200, json={"id": "t1", "displayName": "Eng"})
    )
    result = await server.call_tool("teams_get_team", {"team_id": "t1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_create_team(server):
    respx.post(f"{GRAPH_BASE}/teams").mock(return_value=httpx.Response(202))
    result = await server.call_tool("teams_create_team", {
        "display_name": "New Team", "owner_id": "user_1",
    })
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_update_team(server):
    respx.patch(f"{GRAPH_BASE}/teams/t1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("teams_update_team", {
        "team_id": "t1", "display_name": "Renamed",
    })
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_archive_team(server):
    respx.post(f"{GRAPH_BASE}/teams/t1/archive").mock(return_value=httpx.Response(202))
    result = await server.call_tool("teams_archive_team", {"team_id": "t1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_unarchive_team(server):
    respx.post(f"{GRAPH_BASE}/teams/t1/unarchive").mock(return_value=httpx.Response(202))
    result = await server.call_tool("teams_unarchive_team", {"team_id": "t1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_members(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/members").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "m1"}]})
    )
    result = await server.call_tool("teams_list_members", {"team_id": "t1"})
    assert _get_result_data(result)["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_add_member(server):
    respx.post(f"{GRAPH_BASE}/teams/t1/members").mock(
        return_value=httpx.Response(201, json={"id": "m_new"})
    )
    result = await server.call_tool("teams_add_member", {"team_id": "t1", "user_id": "u1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_remove_member(server):
    respx.delete(f"{GRAPH_BASE}/teams/t1/members/m1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("teams_remove_member", {
        "team_id": "t1", "membership_id": "m1",
    })
    assert _get_result_data(result)["status"] == "success"
```

### 10d. Channel Tests (5 tools)

```python
@pytest.mark.asyncio
@respx.mock
async def test_list_channels(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/channels").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "c1"}]})
    )
    result = await server.call_tool("teams_list_channels", {"team_id": "t1"})
    assert _get_result_data(result)["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_get_channel(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/channels/c1").mock(
        return_value=httpx.Response(200, json={"id": "c1"})
    )
    result = await server.call_tool("teams_get_channel", {"team_id": "t1", "channel_id": "c1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_create_channel(server):
    respx.post(f"{GRAPH_BASE}/teams/t1/channels").mock(
        return_value=httpx.Response(201, json={"id": "c_new"})
    )
    result = await server.call_tool("teams_create_channel", {
        "team_id": "t1", "display_name": "General",
    })
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_update_channel(server):
    respx.patch(f"{GRAPH_BASE}/teams/t1/channels/c1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("teams_update_channel", {
        "team_id": "t1", "channel_id": "c1", "display_name": "Renamed",
    })
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_delete_channel(server):
    respx.delete(f"{GRAPH_BASE}/teams/t1/channels/c1").mock(return_value=httpx.Response(204))
    result = await server.call_tool("teams_delete_channel", {"team_id": "t1", "channel_id": "c1"})
    assert _get_result_data(result)["status"] == "success"
```

### 10e. Messaging Tests (5 tools)

```python
@pytest.mark.asyncio
@respx.mock
async def test_list_channel_messages(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/channels/c1/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "msg1"}]})
    )
    result = await server.call_tool("teams_list_channel_messages", {
        "team_id": "t1", "channel_id": "c1",
    })
    assert _get_result_data(result)["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_get_message(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/channels/c1/messages/msg1").mock(
        return_value=httpx.Response(200, json={"id": "msg1"})
    )
    result = await server.call_tool("teams_get_message", {
        "team_id": "t1", "channel_id": "c1", "message_id": "msg1",
    })
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_message_replies(server):
    respx.get(f"{GRAPH_BASE}/teams/t1/channels/c1/messages/msg1/replies").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "r1"}]})
    )
    result = await server.call_tool("teams_list_message_replies", {
        "team_id": "t1", "channel_id": "c1", "message_id": "msg1",
    })
    assert _get_result_data(result)["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_send_webhook_message(server):
    webhook_url = "https://prod-123.westus.logic.azure.com/workflows/abc/triggers/manual"
    respx.post(webhook_url).mock(return_value=httpx.Response(200))
    result = await server.call_tool("teams_send_webhook_message", {
        "webhook_url": webhook_url, "text": "Hello Teams!",
    })
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
async def test_send_channel_message_delegated_fails(server):
    with pytest.raises(Exception, match="delegated"):
        await server.call_tool("teams_send_channel_message_delegated", {
            "team_id": "t1", "channel_id": "c1", "content": "Hello",
        })
```

### 10f. Meetings Tests (4 tools)

```python
@pytest.mark.asyncio
@respx.mock
async def test_create_meeting(server):
    respx.post(f"{GRAPH_BASE}/users/user@example.com/onlineMeetings").mock(
        return_value=httpx.Response(201, json={"id": "m1", "joinWebUrl": "https://..."})
    )
    result = await server.call_tool("teams_create_meeting", {
        "subject": "Standup", "start_time": "2025-06-15T10:00:00Z",
        "end_time": "2025-06-15T10:30:00Z",
    })
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_meetings(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/onlineMeetings").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "m1"}]})
    )
    result = await server.call_tool("teams_list_meetings", {})
    assert _get_result_data(result)["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_get_meeting(server):
    respx.get(f"{GRAPH_BASE}/users/user@example.com/onlineMeetings/m1").mock(
        return_value=httpx.Response(200, json={"id": "m1"})
    )
    result = await server.call_tool("teams_get_meeting", {"meeting_id": "m1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_delete_meeting(server):
    respx.delete(f"{GRAPH_BASE}/users/user@example.com/onlineMeetings/m1").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("teams_delete_meeting", {"meeting_id": "m1"})
    assert _get_result_data(result)["status"] == "success"
```

### 10g. Presence & Chat Tests (5 tools)

```python
@pytest.mark.asyncio
@respx.mock
async def test_get_presence(server):
    respx.get(f"{GRAPH_BASE}/users/u1/presence").mock(
        return_value=httpx.Response(200, json={"availability": "Available"})
    )
    result = await server.call_tool("teams_get_presence", {"user_id": "u1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_get_presence_bulk(server):
    respx.post(f"{GRAPH_BASE}/communications/getPresencesByUserId").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "u1"}]})
    )
    result = await server.call_tool("teams_get_presence_bulk", {"user_ids": ["u1", "u2"]})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_chats(server):
    respx.get(f"{GRAPH_BASE}/users/u1/chats").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "chat1"}]})
    )
    result = await server.call_tool("teams_list_chats", {"user_id": "u1"})
    assert _get_result_data(result)["count"] == 1

@pytest.mark.asyncio
@respx.mock
async def test_get_chat(server):
    respx.get(f"{GRAPH_BASE}/chats/chat1").mock(
        return_value=httpx.Response(200, json={"id": "chat1"})
    )
    result = await server.call_tool("teams_get_chat", {"chat_id": "chat1"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_chat_messages(server):
    respx.get(f"{GRAPH_BASE}/chats/chat1/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "cm1"}]})
    )
    result = await server.call_tool("teams_list_chat_messages", {"chat_id": "chat1"})
    assert _get_result_data(result)["count"] == 1
```

---

## Step 11: Update test_server.py

Add all 28 Teams tool names and update count to 144:

```python
        # Teams tools (28)
        "teams_list_teams", "teams_get_team", "teams_create_team",
        "teams_update_team", "teams_archive_team", "teams_unarchive_team",
        "teams_list_members", "teams_add_member", "teams_remove_member",
        "teams_list_channels", "teams_get_channel", "teams_create_channel",
        "teams_update_channel", "teams_delete_channel",
        "teams_list_channel_messages", "teams_get_message",
        "teams_list_message_replies", "teams_send_webhook_message",
        "teams_send_channel_message_delegated",
        "teams_create_meeting", "teams_list_meetings",
        "teams_get_meeting", "teams_delete_meeting",
        "teams_get_presence", "teams_get_presence_bulk",
        "teams_list_chats", "teams_get_chat", "teams_list_chat_messages",
```

Total assertion: `assert len(tools) == 144`

---

## Step 12: Documentation & Validation

### 12a. Update CLAUDE.md

### 12b. Run validation
```bash
uv sync --dev --all-extras
uv run pytest -v
uv run ruff check src/ tests/
uv run pyright src/
```

---

## Execution Order

| Order | Step | Tools | Depends On |
|-------|------|-------|------------|
| 1 | Config | — | — |
| 2 | Foundation | helpers | Step 1 |
| 3 | Teams Management | 9 | Step 2 |
| 4 | Channels | 5 | Step 2 |
| 5 | Messaging | 5 | Step 2 |
| 6 | Meetings | 4 | Step 2 |
| 7 | Presence | 2 | Step 2 |
| 8 | Chat Reading | 3 | Step 2 |
| 9 | Registration | — | Steps 3-8 |
| 10 | Tests | 30 | Steps 3-9 |
| 11 | test_server.py | — | Steps 3-9 |
| 12 | Docs & validation | — | Steps 1-11 |

Steps 3-8 are independent.

---

## Risk Notes

- **Webhook URL lifetime:** Power Automate Workflow webhook URLs can be invalidated if the workflow is deleted or modified. The tool cannot detect this until a request fails.
- **`teams_send_channel_message_delegated`:** Always raises ToolError. Included as a placeholder so LLM clients can discover the limitation. If delegated auth is added later, this tool becomes functional.
- **Meeting access policy:** `teams_create_meeting` will fail with a confusing Graph error if the Application Access Policy is not configured. The tool's docstring warns about this but can't detect it proactively.
- **`async with httpx.AsyncClient()` in webhook tool:** Creates a new client per call (no connection pooling). Acceptable since webhook calls are infrequent and go to different URLs.
- **msal sync in async:** Same as O365 — `_get_token()` wrapped in `asyncio.to_thread()`.
