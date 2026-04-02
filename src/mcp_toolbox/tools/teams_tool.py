"""Microsoft Teams integration — teams, channels, messages, meetings, presence via Graph."""

import asyncio
import json
import logging

import httpx
import msal
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import (
    O365_USER_ID,
    TEAMS_CLIENT_ID,
    TEAMS_CLIENT_SECRET,
    TEAMS_TENANT_ID,
)

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

    # --- Teams Management ---

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
            "template@odata.bind": (
                "https://graph.microsoft.com/v1.0/teamsTemplates('standard')"
            ),
            "displayName": display_name,
            "visibility": visibility,
            "members": [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": (
                        f"https://graph.microsoft.com/v1.0/users('{owner_id}')"
                    ),
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
            "user@odata.bind": (
                f"https://graph.microsoft.com/v1.0/users('{user_id}')"
            ),
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

    # --- Channel Management ---

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

    # --- Messaging ---

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
        It will NOT work with app-only client credentials.

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

    # --- Meetings ---

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

    # --- Presence ---

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

    # --- Chat Reading ---

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
