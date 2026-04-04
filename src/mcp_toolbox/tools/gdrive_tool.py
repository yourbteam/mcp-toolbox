"""Google Drive API v3 — files, permissions, comments, replies,
revisions, changes, shared drives."""

import asyncio
import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import (
    GDRIVE_DEFAULT_FOLDER_ID,
    GOOGLE_SERVICE_ACCOUNT_JSON,
)

logger = logging.getLogger(__name__)

_credentials = None
_client: httpx.AsyncClient | None = None

BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
MAX_DOWNLOAD_CHARS = 50_000


def _get_token() -> str:
    global _credentials
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ToolError(
            "GOOGLE_SERVICE_ACCOUNT_JSON not configured. "
            "Set it to the path of your service account "
            "JSON key file."
        )
    if _credentials is None:
        import google.auth.transport.requests
        from google.oauth2 import service_account

        _credentials = (
            service_account.Credentials
            .from_service_account_file(
                GOOGLE_SERVICE_ACCOUNT_JSON,
                scopes=[
                    "https://www.googleapis.com/auth/drive"
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


def _fid(override: str | None = None) -> str | None:
    return override or GDRIVE_DEFAULT_FOLDER_ID


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
        response = await client.request(
            method, url, **kwargs
        )
    except httpx.HTTPError as e:
        raise ToolError(
            f"Google Drive request failed: {e}"
        ) from e
    if response.status_code == 429:
        raise ToolError(
            "Google Drive rate limit exceeded. "
            "Retry after a short delay."
        )
    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
            msg = err.get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(
            f"Google Drive error "
            f"({response.status_code}): {msg}"
        )
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


async def _raw_req(
    method: str,
    url: str,
    params: dict | None = None,
) -> httpx.Response:
    """Low-level request returning the raw response
    (for downloads / exports)."""
    client = await _get_client()
    kwargs: dict = {}
    if params:
        kwargs["params"] = params
    try:
        response = await client.request(
            method, url, **kwargs
        )
    except httpx.HTTPError as e:
        raise ToolError(
            f"Google Drive request failed: {e}"
        ) from e
    if response.status_code == 429:
        raise ToolError(
            "Google Drive rate limit exceeded. "
            "Retry after a short delay."
        )
    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
            msg = err.get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(
            f"Google Drive error "
            f"({response.status_code}): {msg}"
        )
    return response


async def _upload_req(
    method: str,
    url: str,
    metadata: dict,
    content: str,
    mime_type: str,
    params: dict | None = None,
) -> dict:
    """Multipart/related upload for file creation/update
    with text content."""
    client = await _get_client()
    boundary = "mcp_toolbox_boundary"
    body_parts = [
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8"
        "\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mime_type}\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--"
    ]
    body = "".join(body_parts)
    headers = {
        "Content-Type": (
            f"multipart/related; boundary={boundary}"
        ),
        "Authorization": client.headers["Authorization"],
    }
    qs = "uploadType=multipart"
    if params:
        qs += "&" + "&".join(f"{k}={v}" for k, v in params.items())
    full_url = f"{UPLOAD_BASE}{url}?{qs}"
    try:
        response = await client.request(
            method,
            full_url,
            content=body.encode("utf-8"),
            headers=headers,
        )
    except httpx.HTTPError as e:
        raise ToolError(
            f"Google Drive upload failed: {e}"
        ) from e
    if response.status_code == 429:
        raise ToolError(
            "Google Drive rate limit exceeded."
        )
    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
            msg = err.get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(
            f"Google Drive upload error "
            f"({response.status_code}): {msg}"
        )
    return response.json()


# ── Tier 1: File Operations (10 tools) ──────────


def register_tools(mcp: FastMCP) -> None:  # noqa: C901
    """Register all Google Drive tools."""

    # ── Tier 1: Files ────────────────────

    @mcp.tool()
    async def gdrive_list_files(
        q: str | None = None,
        folder_id: str | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
        order_by: str | None = None,
        fields: str | None = None,
        include_trashed: bool | None = None,
        corpora: str | None = None,
        drive_id: str | None = None,
    ) -> str:
        """List files and folders in Google Drive with
        optional search query."""
        params: dict = {"supportsAllDrives": "true"}
        # Build query
        query_parts: list[str] = []
        if q is not None:
            query_parts.append(q)
        if folder_id is not None:
            query_parts.append(
                f"'{folder_id}' in parents"
            )
        elif _fid() is not None:
            query_parts.append(
                f"'{_fid()}' in parents"
            )
        if include_trashed is not True:
            query_parts.append("trashed=false")
        if query_parts:
            params["q"] = " and ".join(query_parts)
        if page_size is not None:
            params["pageSize"] = page_size
        if page_token is not None:
            params["pageToken"] = page_token
        if order_by is not None:
            params["orderBy"] = order_by
        params["fields"] = fields or (
            "nextPageToken,"
            "files(id,name,mimeType,parents,"
            "modifiedTime,size,trashed)"
        )
        if corpora is not None:
            params["corpora"] = corpora
            if corpora == "allDrives":
                params["includeItemsFromAllDrives"] = (
                    "true"
                )
        if drive_id is not None:
            params["driveId"] = drive_id
            params["includeItemsFromAllDrives"] = "true"
        data = await _req("GET", "/files", params=params)
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_get_file(
        file_id: str,
        fields: str | None = None,
    ) -> str:
        """Get metadata for a single file or folder."""
        params: dict = {"supportsAllDrives": "true"}
        params["fields"] = fields or (
            "id,name,mimeType,parents,modifiedTime,"
            "size,webViewLink,description,starred,"
            "trashed,capabilities"
        )
        data = await _req(
            "GET", f"/files/{file_id}", params=params
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_create_file(
        name: str,
        mime_type: str | None = None,
        parent_id: str | None = None,
        content: str | None = None,
        description: str | None = None,
        starred: bool | None = None,
    ) -> str:
        """Create a new file or folder. For folders set
        mime_type to application/vnd.google-apps.folder.
        For files with text content provide content."""
        metadata: dict = {"name": name}
        parent = parent_id or _fid()
        if parent is not None:
            metadata["parents"] = [parent]
        if description is not None:
            metadata["description"] = description
        if starred is not None:
            metadata["starred"] = starred

        if content is not None:
            mt = mime_type or "text/plain"
            metadata["mimeType"] = mt
            data = await _upload_req(
                "POST", "/files", metadata, content, mt,
                params={"supportsAllDrives": "true"},
            )
        else:
            metadata["mimeType"] = mime_type or (
                "application/vnd.google-apps.folder"
            )
            params: dict = {"supportsAllDrives": "true"}
            data = await _req(
                "POST", "/files",
                json_body=metadata, params=params,
            )
        return _success(200, file=data)

    @mcp.tool()
    async def gdrive_copy_file(
        file_id: str,
        name: str | None = None,
        parent_id: str | None = None,
    ) -> str:
        """Create a copy of a file."""
        body: dict = {}
        if name is not None:
            body["name"] = name
        if parent_id is not None:
            body["parents"] = [parent_id]
        params: dict = {"supportsAllDrives": "true"}
        data = await _req(
            "POST", f"/files/{file_id}/copy",
            json_body=body, params=params,
        )
        return _success(200, file=data)

    @mcp.tool()
    async def gdrive_update_file(
        file_id: str,
        name: str | None = None,
        description: str | None = None,
        starred: bool | None = None,
        trashed: bool | None = None,
        add_parents: str | None = None,
        remove_parents: str | None = None,
        content: str | None = None,
        mime_type: str | None = None,
    ) -> str:
        """Update file metadata and/or content."""
        metadata: dict = {}
        if name is not None:
            metadata["name"] = name
        if description is not None:
            metadata["description"] = description
        if starred is not None:
            metadata["starred"] = starred
        if trashed is not None:
            metadata["trashed"] = trashed

        params: dict = {"supportsAllDrives": "true"}
        if add_parents is not None:
            params["addParents"] = add_parents
        if remove_parents is not None:
            params["removeParents"] = remove_parents

        if content is not None:
            mt = mime_type or "text/plain"
            # Upload endpoint uses full URL
            url = f"/files/{file_id}"
            # Need to add params to upload URL manually
            data = await _upload_req(
                "PATCH", url, metadata, content, mt,
                params=params,
            )
        else:
            data = await _req(
                "PATCH", f"/files/{file_id}",
                json_body=metadata, params=params,
            )
        return _success(200, file=data)

    @mcp.tool()
    async def gdrive_delete_file(
        file_id: str,
    ) -> str:
        """Permanently delete a file (bypasses trash).
        Use gdrive_update_file with trashed=true for
        soft delete."""
        params: dict = {"supportsAllDrives": "true"}
        await _req(
            "DELETE", f"/files/{file_id}",
            params=params,
        )
        return _success(204)

    @mcp.tool()
    async def gdrive_export_file(
        file_id: str,
        mime_type: str,
    ) -> str:
        """Export a Google Workspace file (Docs, Sheets,
        Slides) to a standard format like text/plain,
        text/csv, or application/pdf."""
        params: dict = {"mimeType": mime_type, "supportsAllDrives": "true"}
        resp = await _raw_req(
            "GET", f"/files/{file_id}/export",
            params=params,
        )
        ct = resp.headers.get("content-type", "")
        if "text" in ct or "json" in ct or "csv" in ct:
            text = resp.text
            if len(text) > MAX_DOWNLOAD_CHARS:
                text = text[:MAX_DOWNLOAD_CHARS]
                return _success(
                    200,
                    content=text,
                    truncated=True,
                    message=(
                        "Content truncated to "
                        f"{MAX_DOWNLOAD_CHARS} chars."
                    ),
                )
            return _success(200, content=text)
        return _success(
            200,
            message=(
                "Binary export completed. "
                f"MIME type: {mime_type}. "
                "Binary content not suitable "
                "for LLM consumption."
            ),
            size_bytes=len(resp.content),
        )

    @mcp.tool()
    async def gdrive_empty_trash() -> str:
        """Permanently delete all trashed files."""
        await _req("DELETE", "/files/emptyTrash")
        return _success(204)

    @mcp.tool()
    async def gdrive_download_file(
        file_id: str,
    ) -> str:
        """Download file content (non-Google-Workspace
        files). For Docs/Sheets/Slides use
        gdrive_export_file instead."""
        params: dict = {"alt": "media", "supportsAllDrives": "true"}
        resp = await _raw_req(
            "GET", f"/files/{file_id}", params=params
        )
        ct = resp.headers.get("content-type", "")
        if "text" in ct or "json" in ct or "csv" in ct:
            text = resp.text
            if len(text) > MAX_DOWNLOAD_CHARS:
                text = text[:MAX_DOWNLOAD_CHARS]
                return _success(
                    200,
                    content=text,
                    truncated=True,
                    message=(
                        "Content truncated to "
                        f"{MAX_DOWNLOAD_CHARS} chars."
                    ),
                )
            return _success(200, content=text)
        return _success(
            200,
            message=(
                "Binary file downloaded. "
                f"Content-Type: {ct}. "
                "Binary content not suitable "
                "for LLM consumption."
            ),
            size_bytes=len(resp.content),
        )

    @mcp.tool()
    async def gdrive_stop_channel(
        channel_id: str,
        resource_id: str,
    ) -> str:
        """Stop receiving push notifications for a
        watch channel."""
        body = {
            "id": channel_id,
            "resourceId": resource_id,
        }
        await _req(
            "POST", "/channels/stop", json_body=body
        )
        return _success(204)

    # ── Tier 2: Permissions ────────────────────

    @mcp.tool()
    async def gdrive_list_permissions(
        file_id: str,
        page_size: int | None = None,
        page_token: str | None = None,
        fields: str | None = None,
    ) -> str:
        """List all permissions on a file or folder."""
        params: dict = {"supportsAllDrives": "true"}
        params["fields"] = fields or (
            "nextPageToken,"
            "permissions(id,type,role,"
            "emailAddress,displayName,domain)"
        )
        if page_size is not None:
            params["pageSize"] = page_size
        if page_token is not None:
            params["pageToken"] = page_token
        data = await _req(
            "GET",
            f"/files/{file_id}/permissions",
            params=params,
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_get_permission(
        file_id: str,
        permission_id: str,
        fields: str | None = None,
    ) -> str:
        """Get a specific permission by ID."""
        params: dict = {"supportsAllDrives": "true"}
        if fields is not None:
            params["fields"] = fields
        data = await _req(
            "GET",
            f"/files/{file_id}/permissions"
            f"/{permission_id}",
            params=params,
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_create_permission(
        file_id: str,
        role: str,
        type: str,
        email_address: str | None = None,
        domain: str | None = None,
        send_notification_email: bool | None = None,
        email_message: str | None = None,
        transfer_ownership: bool | None = None,
        move_to_new_owners_root: bool | None = None,
    ) -> str:
        """Share a file/folder with a user, group,
        domain, or anyone."""
        body: dict = {"role": role, "type": type}
        if email_address is not None:
            body["emailAddress"] = email_address
        if domain is not None:
            body["domain"] = domain
        params: dict = {"supportsAllDrives": "true"}
        if send_notification_email is not None:
            params["sendNotificationEmail"] = str(
                send_notification_email
            ).lower()
        if email_message is not None:
            params["emailMessage"] = email_message
        if transfer_ownership is not None:
            params["transferOwnership"] = str(
                transfer_ownership
            ).lower()
        if move_to_new_owners_root is not None:
            params["moveToNewOwnersRoot"] = str(
                move_to_new_owners_root
            ).lower()
        data = await _req(
            "POST",
            f"/files/{file_id}/permissions",
            json_body=body, params=params,
        )
        return _success(200, permission=data)

    @mcp.tool()
    async def gdrive_update_permission(
        file_id: str,
        permission_id: str,
        role: str,
        transfer_ownership: bool | None = None,
    ) -> str:
        """Update an existing permission (change role)."""
        body: dict = {"role": role}
        params: dict = {"supportsAllDrives": "true"}
        if transfer_ownership is not None:
            params["transferOwnership"] = str(
                transfer_ownership
            ).lower()
        data = await _req(
            "PATCH",
            f"/files/{file_id}/permissions"
            f"/{permission_id}",
            json_body=body, params=params,
        )
        return _success(200, permission=data)

    @mcp.tool()
    async def gdrive_delete_permission(
        file_id: str,
        permission_id: str,
    ) -> str:
        """Remove a permission (unshare)."""
        params: dict = {"supportsAllDrives": "true"}
        await _req(
            "DELETE",
            f"/files/{file_id}/permissions"
            f"/{permission_id}",
            params=params,
        )
        return _success(204)

    # ── Tier 3: Comments ──────────────────────

    @mcp.tool()
    async def gdrive_list_comments(
        file_id: str,
        page_size: int | None = None,
        page_token: str | None = None,
        include_deleted: bool | None = None,
        start_modified_time: str | None = None,
        fields: str | None = None,
    ) -> str:
        """List comments on a file."""
        params: dict = {}
        params["fields"] = fields or (
            "nextPageToken,"
            "comments(id,content,author,"
            "createdTime,modifiedTime,"
            "resolved,replies)"
        )
        if page_size is not None:
            params["pageSize"] = page_size
        if page_token is not None:
            params["pageToken"] = page_token
        if include_deleted is not None:
            params["includeDeleted"] = str(
                include_deleted
            ).lower()
        if start_modified_time is not None:
            params["startModifiedTime"] = (
                start_modified_time
            )
        data = await _req(
            "GET",
            f"/files/{file_id}/comments",
            params=params,
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_get_comment(
        file_id: str,
        comment_id: str,
        include_deleted: bool | None = None,
        fields: str | None = None,
    ) -> str:
        """Get a single comment by ID."""
        params: dict = {}
        if fields is not None:
            params["fields"] = fields
        if include_deleted is not None:
            params["includeDeleted"] = str(
                include_deleted
            ).lower()
        data = await _req(
            "GET",
            f"/files/{file_id}/comments/{comment_id}",
            params=params,
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_create_comment(
        file_id: str,
        content: str,
        anchor: str | None = None,
        quoted_content: str | None = None,
    ) -> str:
        """Add a comment to a file."""
        body: dict = {"content": content}
        if anchor is not None:
            body["anchor"] = anchor
        if quoted_content is not None:
            body["quotedFileContent"] = {
                "value": quoted_content,
            }
        params: dict = {"fields": "*"}
        data = await _req(
            "POST",
            f"/files/{file_id}/comments",
            json_body=body, params=params,
        )
        return _success(200, comment=data)

    @mcp.tool()
    async def gdrive_update_comment(
        file_id: str,
        comment_id: str,
        content: str,
    ) -> str:
        """Update a comment's content."""
        body: dict = {"content": content}
        params: dict = {"fields": "*"}
        data = await _req(
            "PATCH",
            f"/files/{file_id}/comments/{comment_id}",
            json_body=body, params=params,
        )
        return _success(200, comment=data)

    @mcp.tool()
    async def gdrive_delete_comment(
        file_id: str,
        comment_id: str,
    ) -> str:
        """Delete a comment."""
        await _req(
            "DELETE",
            f"/files/{file_id}/comments/{comment_id}",
        )
        return _success(204)

    # ── Tier 4: Replies ───────────────────────

    @mcp.tool()
    async def gdrive_list_replies(
        file_id: str,
        comment_id: str,
        page_size: int | None = None,
        page_token: str | None = None,
        include_deleted: bool | None = None,
        fields: str | None = None,
    ) -> str:
        """List replies to a comment."""
        params: dict = {}
        params["fields"] = fields or (
            "nextPageToken,"
            "replies(id,content,author,"
            "createdTime,modifiedTime,action)"
        )
        if page_size is not None:
            params["pageSize"] = page_size
        if page_token is not None:
            params["pageToken"] = page_token
        if include_deleted is not None:
            params["includeDeleted"] = str(
                include_deleted
            ).lower()
        base = (
            f"/files/{file_id}"
            f"/comments/{comment_id}/replies"
        )
        data = await _req("GET", base, params=params)
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_get_reply(
        file_id: str,
        comment_id: str,
        reply_id: str,
        include_deleted: bool | None = None,
        fields: str | None = None,
    ) -> str:
        """Get a single reply by ID."""
        params: dict = {}
        if fields is not None:
            params["fields"] = fields
        if include_deleted is not None:
            params["includeDeleted"] = str(
                include_deleted
            ).lower()
        base = (
            f"/files/{file_id}"
            f"/comments/{comment_id}"
            f"/replies/{reply_id}"
        )
        data = await _req("GET", base, params=params)
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_create_reply(
        file_id: str,
        comment_id: str,
        content: str,
        action: str | None = None,
    ) -> str:
        """Reply to a comment. Set action to 'resolve'
        or 'reopen' to change comment status."""
        body: dict = {"content": content}
        if action is not None:
            body["action"] = action
        params: dict = {"fields": "*"}
        base = (
            f"/files/{file_id}"
            f"/comments/{comment_id}/replies"
        )
        data = await _req(
            "POST", base,
            json_body=body, params=params,
        )
        return _success(200, reply=data)

    @mcp.tool()
    async def gdrive_update_reply(
        file_id: str,
        comment_id: str,
        reply_id: str,
        content: str,
    ) -> str:
        """Update a reply's content."""
        body: dict = {"content": content}
        params: dict = {"fields": "*"}
        base = (
            f"/files/{file_id}"
            f"/comments/{comment_id}"
            f"/replies/{reply_id}"
        )
        data = await _req(
            "PATCH", base,
            json_body=body, params=params,
        )
        return _success(200, reply=data)

    @mcp.tool()
    async def gdrive_delete_reply(
        file_id: str,
        comment_id: str,
        reply_id: str,
    ) -> str:
        """Delete a reply."""
        base = (
            f"/files/{file_id}"
            f"/comments/{comment_id}"
            f"/replies/{reply_id}"
        )
        await _req("DELETE", base)
        return _success(204)

    # ── Tier 5: Revisions ─────────────────────

    @mcp.tool()
    async def gdrive_list_revisions(
        file_id: str,
        page_size: int | None = None,
        page_token: str | None = None,
        fields: str | None = None,
    ) -> str:
        """List revisions of a file."""
        params: dict = {}
        params["fields"] = fields or (
            "nextPageToken,"
            "revisions(id,modifiedTime,mimeType,"
            "size,keepForever,published,"
            "lastModifyingUser)"
        )
        if page_size is not None:
            params["pageSize"] = page_size
        if page_token is not None:
            params["pageToken"] = page_token
        data = await _req(
            "GET",
            f"/files/{file_id}/revisions",
            params=params,
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_get_revision(
        file_id: str,
        revision_id: str,
        fields: str | None = None,
    ) -> str:
        """Get metadata for a specific revision."""
        params: dict = {}
        if fields is not None:
            params["fields"] = fields
        data = await _req(
            "GET",
            f"/files/{file_id}/revisions"
            f"/{revision_id}",
            params=params,
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_update_revision(
        file_id: str,
        revision_id: str,
        keep_forever: bool | None = None,
        published: bool | None = None,
        publish_auto: bool | None = None,
        published_outside_domain: bool | None = None,
    ) -> str:
        """Update revision metadata (keep forever,
        publish settings)."""
        body: dict = {}
        if keep_forever is not None:
            body["keepForever"] = keep_forever
        if published is not None:
            body["published"] = published
        if publish_auto is not None:
            body["publishAuto"] = publish_auto
        if published_outside_domain is not None:
            body["publishedOutsideDomain"] = (
                published_outside_domain
            )
        data = await _req(
            "PATCH",
            f"/files/{file_id}/revisions"
            f"/{revision_id}",
            json_body=body,
        )
        return _success(200, revision=data)

    @mcp.tool()
    async def gdrive_delete_revision(
        file_id: str,
        revision_id: str,
    ) -> str:
        """Permanently delete a revision. Only for files
        with binary content (not Workspace files)."""
        await _req(
            "DELETE",
            f"/files/{file_id}/revisions"
            f"/{revision_id}",
        )
        return _success(204)

    # ── Tier 6: Changes ───────────────────────

    @mcp.tool()
    async def gdrive_get_start_page_token(
        drive_id: str | None = None,
    ) -> str:
        """Get the starting page token for listing
        future changes."""
        params: dict = {"supportsAllDrives": "true"}
        if drive_id is not None:
            params["driveId"] = drive_id
        data = await _req(
            "GET", "/changes/startPageToken",
            params=params,
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_list_changes(
        page_token: str,
        page_size: int | None = None,
        spaces: str | None = None,
        include_removed: bool | None = None,
        include_items_from_all_drives: (
            bool | None
        ) = None,
        fields: str | None = None,
    ) -> str:
        """List changes to files starting from a page
        token."""
        params: dict = {
            "pageToken": page_token,
            "supportsAllDrives": "true",
        }
        params["fields"] = fields or (
            "nextPageToken,newStartPageToken,"
            "changes(fileId,removed,time,"
            "file(id,name,mimeType,trashed))"
        )
        if page_size is not None:
            params["pageSize"] = page_size
        if spaces is not None:
            params["spaces"] = spaces
        if include_removed is not None:
            params["includeRemoved"] = str(
                include_removed
            ).lower()
        if include_items_from_all_drives is not None:
            params["includeItemsFromAllDrives"] = str(
                include_items_from_all_drives
            ).lower()
        data = await _req(
            "GET", "/changes", params=params
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_watch_changes(
        page_token: str,
        channel_id: str,
        webhook_url: str,
        expiration: str | None = None,
        channel_type: str | None = None,
    ) -> str:
        """Subscribe to push notifications for file
        changes (sets up a webhook)."""
        body: dict = {
            "id": channel_id,
            "type": channel_type or "web_hook",
            "address": webhook_url,
        }
        if expiration is not None:
            body["expiration"] = expiration
        params: dict = {
            "pageToken": page_token,
            "supportsAllDrives": "true",
        }
        data = await _req(
            "POST", "/changes/watch",
            json_body=body, params=params,
        )
        return _success(200, channel=data)

    # ── Tier 7: Shared Drives ──────────────────

    @mcp.tool()
    async def gdrive_list_drives(
        page_size: int | None = None,
        page_token: str | None = None,
        q: str | None = None,
        fields: str | None = None,
    ) -> str:
        """List shared drives the service account has
        access to."""
        params: dict = {}
        params["fields"] = fields or (
            "nextPageToken,"
            "drives(id,name,createdTime,capabilities)"
        )
        if page_size is not None:
            params["pageSize"] = page_size
        if page_token is not None:
            params["pageToken"] = page_token
        if q is not None:
            params["q"] = q
        data = await _req(
            "GET", "/drives", params=params
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_get_drive(
        drive_id: str,
        fields: str | None = None,
    ) -> str:
        """Get metadata for a shared drive."""
        params: dict = {}
        if fields is not None:
            params["fields"] = fields
        data = await _req(
            "GET", f"/drives/{drive_id}",
            params=params,
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdrive_create_drive(
        name: str,
        request_id: str,
    ) -> str:
        """Create a new shared drive. Use a UUID for
        request_id as an idempotency key."""
        body: dict = {"name": name}
        params: dict = {"requestId": request_id}
        data = await _req(
            "POST", "/drives",
            json_body=body, params=params,
        )
        return _success(200, drive=data)

    @mcp.tool()
    async def gdrive_update_drive(
        drive_id: str,
        name: str | None = None,
        restrictions: dict | None = None,
    ) -> str:
        """Update a shared drive's name or
        restrictions."""
        body: dict = {}
        if name is not None:
            body["name"] = name
        if restrictions is not None:
            body["restrictions"] = restrictions
        data = await _req(
            "PATCH", f"/drives/{drive_id}",
            json_body=body,
        )
        return _success(200, drive=data)

    @mcp.tool()
    async def gdrive_delete_drive(
        drive_id: str,
    ) -> str:
        """Delete a shared drive (must be empty)."""
        await _req("DELETE", f"/drives/{drive_id}")
        return _success(204)
