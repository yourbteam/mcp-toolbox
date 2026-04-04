"""Slack integration — messaging, channels, users, reactions, pins, files."""

import asyncio
import json
import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from mcp_toolbox.config import SLACK_BOT_TOKEN

logger = logging.getLogger(__name__)

_slack_client: WebClient | None = None


def _get_client() -> WebClient:
    global _slack_client
    if not SLACK_BOT_TOKEN:
        raise ToolError("SLACK_BOT_TOKEN not configured. Set it in your environment.")
    if _slack_client is None:
        _slack_client = WebClient(token=SLACK_BOT_TOKEN)
    return _slack_client


def _success(status_code: int, **kwargs) -> str:
    return json.dumps({"status": "success", "status_code": status_code, **kwargs})


def _get_cursor(result) -> str | None:
    meta = result.get("response_metadata", {})
    cursor = meta.get("next_cursor", "")
    return cursor if cursor else None


async def _call(method_name: str, **kwargs):
    client = _get_client()
    fn = getattr(client, method_name)
    try:
        return await asyncio.to_thread(fn, **kwargs)
    except SlackApiError as e:
        error = e.response.get("error", "unknown_error")
        raise ToolError(f"Slack error ({error})") from e
    except Exception as e:
        raise ToolError(f"Slack request failed: {e}") from e


def register_tools(mcp: FastMCP) -> None:
    if not SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN not set — Slack tools will fail at invocation.")

    # --- Messaging ---

    @mcp.tool()
    async def slack_send_message(
        channel: str, text: str,
        blocks: list[dict] | None = None,
        thread_ts: str | None = None,
        unfurl_links: bool = True,
    ) -> str:
        """Send a message to a Slack channel.

        Args:
            channel: Channel ID or name
            text: Message text (mrkdwn supported)
            blocks: Block Kit blocks for rich formatting
            thread_ts: Thread timestamp to reply to
            unfurl_links: Unfurl URLs (default true)
        """
        kwargs: dict = {"channel": channel, "text": text, "unfurl_links": unfurl_links}
        if blocks:
            kwargs["blocks"] = blocks
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        result = await _call("chat_postMessage", **kwargs)
        return _success(200, ts=result["ts"], channel=result["channel"])

    @mcp.tool()
    async def slack_send_dm(
        user_id: str, text: str, blocks: list[dict] | None = None,
    ) -> str:
        """Send a direct message to a Slack user.

        Args:
            user_id: User ID (e.g., U12345)
            text: Message text
            blocks: Block Kit blocks
        """
        open_result = await _call("conversations_open", users=user_id)
        dm_channel = open_result["channel"]["id"]
        kwargs: dict = {"channel": dm_channel, "text": text}
        if blocks:
            kwargs["blocks"] = blocks
        result = await _call("chat_postMessage", **kwargs)
        return _success(200, ts=result["ts"], channel=dm_channel)

    @mcp.tool()
    async def slack_update_message(
        channel: str, ts: str, text: str, blocks: list[dict] | None = None,
    ) -> str:
        """Update a Slack message.

        Args:
            channel: Channel ID
            ts: Message timestamp to update
            text: New message text
            blocks: New blocks
        """
        kwargs: dict = {"channel": channel, "ts": ts, "text": text}
        if blocks:
            kwargs["blocks"] = blocks
        result = await _call("chat_update", **kwargs)
        return _success(200, ts=result["ts"], channel=result["channel"])

    @mcp.tool()
    async def slack_delete_message(channel: str, ts: str) -> str:
        """Delete a Slack message (bot can only delete its own).

        Args:
            channel: Channel ID
            ts: Message timestamp to delete
        """
        await _call("chat_delete", channel=channel, ts=ts)
        return _success(200, message="Message deleted")

    @mcp.tool()
    async def slack_schedule_message(
        channel: str, text: str, post_at: int, blocks: list[dict] | None = None,
    ) -> str:
        """Schedule a Slack message for future delivery.

        Args:
            channel: Channel ID
            text: Message text
            post_at: Unix timestamp for delivery
            blocks: Block Kit blocks
        """
        kwargs: dict = {"channel": channel, "text": text, "post_at": post_at}
        if blocks:
            kwargs["blocks"] = blocks
        result = await _call("chat_scheduleMessage", **kwargs)
        return _success(200, scheduled_message_id=result["scheduled_message_id"])

    @mcp.tool()
    async def slack_get_channel_history(
        channel: str, limit: int = 20, cursor: str | None = None,
        oldest: str | None = None, latest: str | None = None,
    ) -> str:
        """List messages in a Slack channel.

        Args:
            channel: Channel ID
            limit: Max results (default 20, max 1000)
            cursor: Pagination cursor
            oldest: Start of time range (Unix ts)
            latest: End of time range (Unix ts)
        """
        kwargs: dict = {"channel": channel, "limit": limit}
        if cursor:
            kwargs["cursor"] = cursor
        if oldest:
            kwargs["oldest"] = oldest
        if latest:
            kwargs["latest"] = latest
        result = await _call("conversations_history", **kwargs)
        msgs = result.get("messages", [])
        return _success(200, data=msgs, count=len(msgs), next_cursor=_get_cursor(result))

    @mcp.tool()
    async def slack_get_thread_replies(
        channel: str, ts: str, limit: int = 20, cursor: str | None = None,
    ) -> str:
        """List replies in a Slack thread.

        Args:
            channel: Channel ID
            ts: Thread parent timestamp
            limit: Max results (default 20)
            cursor: Pagination cursor
        """
        kwargs: dict = {"channel": channel, "ts": ts, "limit": limit}
        if cursor:
            kwargs["cursor"] = cursor
        result = await _call("conversations_replies", **kwargs)
        msgs = result.get("messages", [])
        return _success(200, data=msgs, count=len(msgs), next_cursor=_get_cursor(result))

    # --- Channel Management ---

    @mcp.tool()
    async def slack_list_channels(
        types: str = "public_channel", limit: int = 100, cursor: str | None = None,
    ) -> str:
        """List Slack channels.

        Args:
            types: Channel types (public_channel,private_channel)
            limit: Max results (default 100)
            cursor: Pagination cursor
        """
        kwargs: dict = {"types": types, "limit": limit}
        if cursor:
            kwargs["cursor"] = cursor
        result = await _call("conversations_list", **kwargs)
        channels = result.get("channels", [])
        return _success(
            200, data=channels, count=len(channels), next_cursor=_get_cursor(result)
        )

    @mcp.tool()
    async def slack_get_channel_info(channel: str) -> str:
        """Get Slack channel details.

        Args:
            channel: Channel ID
        """
        result = await _call("conversations_info", channel=channel)
        return _success(200, data=result.get("channel", {}))

    @mcp.tool()
    async def slack_create_channel(name: str, is_private: bool = False) -> str:
        """Create a Slack channel.

        Args:
            name: Channel name (lowercase, no spaces)
            is_private: Create as private (default false)
        """
        result = await _call("conversations_create", name=name, is_private=is_private)
        return _success(200, data=result.get("channel", {}))

    @mcp.tool()
    async def slack_archive_channel(channel: str) -> str:
        """Archive a Slack channel.

        Args:
            channel: Channel ID
        """
        await _call("conversations_archive", channel=channel)
        return _success(200, message="Channel archived")

    @mcp.tool()
    async def slack_unarchive_channel(channel: str) -> str:
        """Unarchive a Slack channel.

        Args:
            channel: Channel ID
        """
        await _call("conversations_unarchive", channel=channel)
        return _success(200, message="Channel unarchived")

    @mcp.tool()
    async def slack_invite_to_channel(channel: str, users: str) -> str:
        """Invite users to a Slack channel.

        Args:
            channel: Channel ID
            users: Comma-separated user IDs
        """
        result = await _call("conversations_invite", channel=channel, users=users)
        return _success(200, data=result.get("channel", {}))

    @mcp.tool()
    async def slack_list_channel_members(
        channel: str, limit: int = 100, cursor: str | None = None,
    ) -> str:
        """List members of a Slack channel.

        Args:
            channel: Channel ID
            limit: Max results (default 100)
            cursor: Pagination cursor
        """
        kwargs: dict = {"channel": channel, "limit": limit}
        if cursor:
            kwargs["cursor"] = cursor
        result = await _call("conversations_members", **kwargs)
        members = result.get("members", [])
        return _success(
            200, data=members, count=len(members), next_cursor=_get_cursor(result)
        )

    @mcp.tool()
    async def slack_set_channel_topic(channel: str, topic: str) -> str:
        """Set a Slack channel topic.

        Args:
            channel: Channel ID
            topic: New topic text
        """
        result = await _call("conversations_setTopic", channel=channel, topic=topic)
        return _success(200, topic=result.get("topic", ""))

    @mcp.tool()
    async def slack_set_channel_purpose(channel: str, purpose: str) -> str:
        """Set a Slack channel purpose.

        Args:
            channel: Channel ID
            purpose: New purpose text
        """
        result = await _call(
            "conversations_setPurpose", channel=channel, purpose=purpose
        )
        return _success(200, purpose=result.get("purpose", ""))

    # --- Users ---

    @mcp.tool()
    async def slack_list_users(limit: int = 100, cursor: str | None = None) -> str:
        """List Slack workspace members.

        Args:
            limit: Max results (default 100)
            cursor: Pagination cursor
        """
        kwargs: dict = {"limit": limit}
        if cursor:
            kwargs["cursor"] = cursor
        result = await _call("users_list", **kwargs)
        members = result.get("members", [])
        return _success(
            200, data=members, count=len(members), next_cursor=_get_cursor(result)
        )

    @mcp.tool()
    async def slack_get_user_info(user: str) -> str:
        """Get Slack user details.

        Args:
            user: User ID
        """
        result = await _call("users_info", user=user)
        return _success(200, data=result.get("user", {}))

    @mcp.tool()
    async def slack_find_user_by_email(email: str) -> str:
        """Look up a Slack user by email.

        Args:
            email: Email address
        """
        result = await _call("users_lookupByEmail", email=email)
        return _success(200, data=result.get("user", {}))

    @mcp.tool()
    async def slack_get_user_presence(user: str) -> str:
        """Get a Slack user presence status.

        Args:
            user: User ID
        """
        result = await _call("users_getPresence", user=user)
        return _success(200, presence=result.get("presence"), online=result.get("online"))

    # --- Reactions ---

    @mcp.tool()
    async def slack_add_reaction(channel: str, timestamp: str, name: str) -> str:
        """Add an emoji reaction to a Slack message.

        Args:
            channel: Channel ID
            timestamp: Message timestamp
            name: Emoji name (without colons, e.g., thumbsup)
        """
        await _call("reactions_add", channel=channel, timestamp=timestamp, name=name)
        return _success(200, message="Reaction added")

    @mcp.tool()
    async def slack_remove_reaction(channel: str, timestamp: str, name: str) -> str:
        """Remove an emoji reaction from a Slack message.

        Args:
            channel: Channel ID
            timestamp: Message timestamp
            name: Emoji name
        """
        await _call(
            "reactions_remove", channel=channel, timestamp=timestamp, name=name
        )
        return _success(200, message="Reaction removed")

    @mcp.tool()
    async def slack_get_reactions(channel: str, timestamp: str) -> str:
        """Get reactions on a Slack message.

        Args:
            channel: Channel ID
            timestamp: Message timestamp
        """
        result = await _call(
            "reactions_get", channel=channel, timestamp=timestamp, full=True
        )
        msg = result.get("message", {})
        reactions = msg.get("reactions", [])
        return _success(200, data=reactions, count=len(reactions))

    # --- Pins ---

    @mcp.tool()
    async def slack_pin_message(channel: str, timestamp: str) -> str:
        """Pin a message in a Slack channel.

        Args:
            channel: Channel ID
            timestamp: Message timestamp
        """
        await _call("pins_add", channel=channel, timestamp=timestamp)
        return _success(200, message="Message pinned")

    @mcp.tool()
    async def slack_unpin_message(channel: str, timestamp: str) -> str:
        """Unpin a Slack message.

        Args:
            channel: Channel ID
            timestamp: Message timestamp
        """
        await _call("pins_remove", channel=channel, timestamp=timestamp)
        return _success(200, message="Message unpinned")

    @mcp.tool()
    async def slack_list_pins(channel: str) -> str:
        """List pinned items in a Slack channel.

        Args:
            channel: Channel ID
        """
        result = await _call("pins_list", channel=channel)
        items = result.get("items", [])
        return _success(200, data=items, count=len(items))

    # --- Files ---

    @mcp.tool()
    async def slack_upload_file(
        channel: str, file_path: str,
        title: str | None = None, initial_comment: str | None = None,
    ) -> str:
        """Upload a file to a Slack channel.

        Args:
            channel: Channel ID
            file_path: Local file path
            title: File title
            initial_comment: Comment with the file
        """
        kwargs: dict = {"channel": channel, "file": file_path}
        if title:
            kwargs["title"] = title
        if initial_comment:
            kwargs["initial_comment"] = initial_comment
        result = await _call("files_upload_v2", **kwargs)
        return _success(200, data=result.get("file", {}))

    @mcp.tool()
    async def slack_delete_file(file_id: str) -> str:
        """Delete a Slack file.

        Args:
            file_id: File ID
        """
        await _call("files_delete", file=file_id)
        return _success(200, message="File deleted")
