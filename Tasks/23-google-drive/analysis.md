# Task 23: Google Drive Integration - Analysis & Requirements

## Objective
Add Google Drive as a tool integration in mcp-toolbox, exposing file management, permissions, comments, replies, revisions, change tracking, and shared drive capabilities as MCP tools for LLM clients.

---

## API Technical Details

### Google Drive API v3 -- REST
- **Base URL:** `https://www.googleapis.com/drive/v3`
- **Upload URL:** `https://www.googleapis.com/upload/drive/v3/files` (for file content uploads)
- **Download:** `GET https://www.googleapis.com/drive/v3/files/{fileId}?alt=media` (raw content)
- **Auth:** Google Service Account with JSON key file. Reuse existing `google-auth` library pattern from `sheets_tool.py`.
- **Scope:** `https://www.googleapis.com/auth/drive` (full read/write access to all files the service account can access)
- **Format:** JSON request/response (except upload/download of file content)
- **API Version:** v3 (stable, current)

### Authentication Flow (same as Sheets)
1. Load service account credentials from JSON key file via `google.oauth2.service_account.Credentials.from_service_account_file()`
2. Scope the credentials to `https://www.googleapis.com/auth/drive`
3. Call `credentials.refresh(google.auth.transport.requests.Request())` to obtain/refresh the access token (sync call, wrapped with `asyncio.to_thread`)
4. Use `credentials.token` as the Bearer token in httpx request headers
5. Token auto-expires (typically 1 hour); refresh before each request if `credentials.valid` is `False`

### Rate Limits

| Metric | Limit |
|--------|-------|
| Queries per day | 1,000,000,000 (effectively unlimited) |
| Queries per 100 seconds per user | 1,000 |
| Queries per 100 seconds per project | 20,000 |
| Upload bandwidth | 750 GB per day per user |
| Download bandwidth | 10 GB per day per user |

- HTTP 403 with `userRateLimitExceeded` or `rateLimitExceeded` on exceed
- HTTP 429 also possible -- use exponential backoff with jitter
- `Retry-After` header may or may not be present; implement client-side backoff regardless

### Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes | Path to the service account JSON key file (reused from Sheets/Docs/Calendar) |
| `GDRIVE_DEFAULT_FOLDER_ID` | No | Default parent folder ID for file operations; if not set, operations target the service account's "My Drive" root |

### REST Resources

The Drive API v3 has 7 primary REST resources:

| Resource | Description |
|----------|-------------|
| `files` | File/folder CRUD, search, copy, export, trash |
| `permissions` | Sharing and access control on files/folders |
| `comments` | Comments on files |
| `replies` | Replies to comments |
| `revisions` | File version history |
| `changes` | Change log for files the user has access to |
| `drives` | Shared drive management |

---

## Key Quirks & Design Notes

### File Upload vs Metadata
- **Metadata-only requests** go to `https://www.googleapis.com/drive/v3/files` (standard base URL)
- **Upload requests** (creating/updating file content) go to `https://www.googleapis.com/upload/drive/v3/files` with `uploadType=multipart` or `uploadType=media`
- For this integration, limit file creation/update to **metadata + small text content**. Do not attempt large binary uploads.
- Use `uploadType=multipart` for combined metadata + content (max ~5 MB for simple use cases). The request body is `multipart/related` with a JSON metadata part and a content part.
- Use `uploadType=media` for content-only upload (no metadata).

### Export MIME Types
- Google Workspace files (Docs, Sheets, Slides) cannot be downloaded directly via `alt=media`. They must be **exported** to a standard format using `files.export`.
- Common export mappings:
  - Google Docs -> `application/pdf`, `text/plain`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
  - Google Sheets -> `text/csv`, `application/pdf`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
  - Google Slides -> `application/pdf`, `application/vnd.openxmlformats-officedocument.presentationml.presentation`
  - Google Drawings -> `image/png`, `image/svg+xml`, `application/pdf`

### `corpora` Parameter (files.list)
- Controls which collection of files to search:
  - `user` -- files owned by or shared with the authenticated user (default)
  - `drive` -- files in a specific shared drive (requires `driveId`)
  - `domain` -- files shared to the domain (service accounts have no domain, rarely useful)
  - `allDrives` -- both personal and shared drives (requires `includeItemsFromAllDrives=true` and `supportsAllDrives=true`)
- Always pass `supportsAllDrives=true` in requests to ensure shared drive files are accessible.

### Trashed Items
- Deleted files go to trash by default (`files.delete` with `DELETE` method permanently deletes; use `files.update` with `trashed=true` to soft-delete).
- `files.list` excludes trashed files by default (`trashed=false` implicit filter).
- To list trashed files: `q=trashed=true`.
- `files.emptyTrash` permanently removes all trashed files.

### File IDs
- Every file and folder in Google Drive has a unique `fileId` string.
- Folder IDs work the same as file IDs -- folders are files with MIME type `application/vnd.google-apps.folder`.
- The root folder ID can be referenced as `root` in API calls.

### Query Language (files.list `q` parameter)
- Supports operators: `=`, `!=`, `contains`, `not`, `in`, `and`, `or`, `has`
- Common queries:
  - `'<folderId>' in parents` -- files in a specific folder
  - `name = 'filename.txt'` -- exact name match
  - `mimeType = 'application/vnd.google-apps.folder'` -- only folders
  - `fullText contains 'search term'` -- full-text content search
  - `modifiedTime > '2024-01-01T00:00:00'` -- date filtering

### Fields Parameter
- Drive API uses **partial response** -- you must specify which fields to return via the `fields` parameter.
- Use `fields=*` for all fields (expensive, avoid in production).
- Use `fields=files(id,name,mimeType,parents,modifiedTime,size)` for targeted responses on list operations.
- Use `fields=id,name,mimeType,parents,modifiedTime,size,webViewLink` for single-file operations.

### Shared Drives (formerly "Team Drives")
- All operations on shared drive content require `supportsAllDrives=true` query parameter.
- Creating files in a shared drive requires specifying the shared drive folder as parent.
- Shared drives themselves are managed via the `drives` resource.

---

## Tool Specifications

### Tier 1: File Operations (8 tools)

#### `gdrive_list_files`
List files and folders in Google Drive with optional search query.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `q` | str | No | Search query (Drive query syntax, e.g. `"'folderId' in parents"`) |
| `folder_id` | str | No | List files in this folder (shortcut for `'<id>' in parents` query) |
| `page_size` | int | No | Max results per page (1-1000, default 100) |
| `page_token` | str | No | Token for next page of results |
| `order_by` | str | No | Sort order (e.g. `"modifiedTime desc"`, `"name"`) |
| `fields` | str | No | Fields to return (default: `"files(id,name,mimeType,parents,modifiedTime,size,trashed)"`) |
| `include_trashed` | bool | No | Include trashed files (default: false) |
| `corpora` | str | No | Search scope: `"user"`, `"drive"`, `"allDrives"` (default: `"user"`) |
| `drive_id` | str | No | Shared drive ID (required when corpora=`"drive"`) |

- **Endpoint:** `GET /drive/v3/files`
- **HTTP Method:** GET

---

#### `gdrive_get_file`
Get metadata for a single file or folder.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `fields` | str | No | Fields to return (default: `"id,name,mimeType,parents,modifiedTime,size,webViewLink,description,starred,trashed,capabilities"`) |

- **Endpoint:** `GET /drive/v3/files/{fileId}`
- **HTTP Method:** GET

---

#### `gdrive_create_file`
Create a new file or folder. For folders, set `mime_type` to `application/vnd.google-apps.folder`. For files with content, provide `content` (text only).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | File or folder name |
| `mime_type` | str | No | MIME type (default: `"application/vnd.google-apps.folder"` if no content, else auto-detected) |
| `parent_id` | str | No | Parent folder ID (default: `GDRIVE_DEFAULT_FOLDER_ID` or root) |
| `content` | str | No | Text content for the file (small files only; omit for folders) |
| `description` | str | No | File description |
| `starred` | bool | No | Whether to star the file |

- **Endpoint (metadata only):** `POST /drive/v3/files`
- **Endpoint (with content):** `POST /upload/drive/v3/files?uploadType=multipart`
- **HTTP Method:** POST

---

#### `gdrive_copy_file`
Create a copy of a file.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | ID of the file to copy |
| `name` | str | No | Name for the copy (default: "Copy of <original>") |
| `parent_id` | str | No | Parent folder for the copy |

- **Endpoint:** `POST /drive/v3/files/{fileId}/copy`
- **HTTP Method:** POST

---

#### `gdrive_update_file`
Update a file's metadata and/or content.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `name` | str | No | New file name |
| `description` | str | No | New description |
| `starred` | bool | No | Star or unstar |
| `trashed` | bool | No | Move to or restore from trash |
| `add_parents` | str | No | Comma-separated parent folder IDs to add |
| `remove_parents` | str | No | Comma-separated parent folder IDs to remove |
| `content` | str | No | New text content (small files only) |
| `mime_type` | str | No | MIME type of the new content |

- **Endpoint (metadata only):** `PATCH /drive/v3/files/{fileId}`
- **Endpoint (with content):** `PATCH /upload/drive/v3/files/{fileId}?uploadType=multipart`
- **HTTP Method:** PATCH

---

#### `gdrive_delete_file`
Permanently delete a file (bypasses trash). Use `gdrive_update_file` with `trashed=true` for soft delete.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |

- **Endpoint:** `DELETE /drive/v3/files/{fileId}`
- **HTTP Method:** DELETE

---

#### `gdrive_export_file`
Export a Google Workspace file (Docs, Sheets, Slides) to a standard format.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The Google Workspace file ID |
| `mime_type` | str | Yes | Target MIME type (e.g. `"text/plain"`, `"application/pdf"`, `"text/csv"`) |

- **Endpoint:** `GET /drive/v3/files/{fileId}/export`
- **HTTP Method:** GET
- **Query Param:** `mimeType=<target>`
- **Note:** Returns raw file content in the response body. For text-based exports, return as string. For binary (PDF), return base64 or a status message indicating export is not suitable for LLM consumption.

---

#### `gdrive_empty_trash`
Permanently delete all trashed files.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| *(none)* | | | |

- **Endpoint:** `DELETE /drive/v3/files/emptyTrash`
- **HTTP Method:** DELETE

---

#### `gdrive_download_file`
Download file content (for non-Google-Workspace files).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | File ID |

- **Endpoint:** `GET /drive/v3/files/{fileId}?alt=media`
- **HTTP Method:** GET
- **Note:** Returns raw file content. For Google Workspace files (Docs, Sheets, Slides), use `gdrive_export_file` instead.

---

#### `gdrive_stop_channel`
Stop receiving push notifications for a channel.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `channel_id` | str | Yes | Channel ID from the watch response |
| `resource_id` | str | Yes | Resource ID from the watch response |

- **Endpoint:** `POST /drive/v3/channels/stop`
- **HTTP Method:** POST
- **Body:** `{"id": channel_id, "resourceId": resource_id}`

---

### Tier 2: Permissions (5 tools)

#### `gdrive_list_permissions`
List all permissions on a file or folder.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file/folder ID |
| `page_size` | int | No | Max results (1-100, default 100) |
| `page_token` | str | No | Pagination token |
| `fields` | str | No | Fields to return (default: `"permissions(id,type,role,emailAddress,displayName,domain)"`) |

- **Endpoint:** `GET /drive/v3/files/{fileId}/permissions`
- **HTTP Method:** GET

---

#### `gdrive_get_permission`
Get a specific permission by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file/folder ID |
| `permission_id` | str | Yes | The permission ID |
| `fields` | str | No | Fields to return |

- **Endpoint:** `GET /drive/v3/files/{fileId}/permissions/{permissionId}`
- **HTTP Method:** GET

---

#### `gdrive_create_permission`
Share a file/folder with a user, group, domain, or anyone.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file/folder ID |
| `role` | str | Yes | Permission role: `"reader"`, `"commenter"`, `"writer"`, `"organizer"`, `"fileOrganizer"`, `"owner"` |
| `type` | str | Yes | Grantee type: `"user"`, `"group"`, `"domain"`, `"anyone"` |
| `email_address` | str | No | Email address (required for type `"user"` or `"group"`) |
| `domain` | str | No | Domain (required for type `"domain"`) |
| `send_notification_email` | bool | No | Send a notification email (default: true) |
| `email_message` | str | No | Custom message for the notification email |
| `transfer_ownership` | bool | No | Transfer ownership (only with role `"owner"`) |
| `move_to_new_owners_root` | bool | No | Move file to new owner's root (only with ownership transfer) |

- **Endpoint:** `POST /drive/v3/files/{fileId}/permissions`
- **HTTP Method:** POST

---

#### `gdrive_update_permission`
Update an existing permission (e.g., change role).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file/folder ID |
| `permission_id` | str | Yes | The permission ID |
| `role` | str | Yes | New role: `"reader"`, `"commenter"`, `"writer"`, `"organizer"`, `"fileOrganizer"`, `"owner"` |
| `transfer_ownership` | bool | No | Transfer ownership (only with role `"owner"`) |

- **Endpoint:** `PATCH /drive/v3/files/{fileId}/permissions/{permissionId}`
- **HTTP Method:** PATCH

---

#### `gdrive_delete_permission`
Remove a permission (unshare).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file/folder ID |
| `permission_id` | str | Yes | The permission ID to remove |

- **Endpoint:** `DELETE /drive/v3/files/{fileId}/permissions/{permissionId}`
- **HTTP Method:** DELETE

---

### Tier 3: Comments (5 tools)

#### `gdrive_list_comments`
List comments on a file.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `page_size` | int | No | Max results (1-100, default 20) |
| `page_token` | str | No | Pagination token |
| `include_deleted` | bool | No | Include deleted comments (default: false) |
| `start_modified_time` | str | No | Only comments modified after this time (RFC 3339) |
| `fields` | str | No | Fields to return (default: `"comments(id,content,author,createdTime,modifiedTime,resolved,replies)"`) |

- **Endpoint:** `GET /drive/v3/files/{fileId}/comments`
- **HTTP Method:** GET

---

#### `gdrive_get_comment`
Get a single comment by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `comment_id` | str | Yes | The comment ID |
| `include_deleted` | bool | No | Include if deleted (default: false) |
| `fields` | str | No | Fields to return |

- **Endpoint:** `GET /drive/v3/files/{fileId}/comments/{commentId}`
- **HTTP Method:** GET

---

#### `gdrive_create_comment`
Add a comment to a file.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `content` | str | Yes | Comment text (supports basic HTML) |
| `anchor` | str | No | JSON string defining the anchor region in the file (API-specific format) |
| `quoted_content` | str | No | The text being commented on |

- **Endpoint:** `POST /drive/v3/files/{fileId}/comments`
- **HTTP Method:** POST

---

#### `gdrive_update_comment`
Update a comment's content.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `comment_id` | str | Yes | The comment ID |
| `content` | str | Yes | New comment text |

- **Endpoint:** `PATCH /drive/v3/files/{fileId}/comments/{commentId}`
- **HTTP Method:** PATCH

---

#### `gdrive_delete_comment`
Delete a comment.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `comment_id` | str | Yes | The comment ID |

- **Endpoint:** `DELETE /drive/v3/files/{fileId}/comments/{commentId}`
- **HTTP Method:** DELETE

---

### Tier 4: Replies (5 tools)

#### `gdrive_list_replies`
List replies to a comment.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `comment_id` | str | Yes | The comment ID |
| `page_size` | int | No | Max results (1-100, default 20) |
| `page_token` | str | No | Pagination token |
| `include_deleted` | bool | No | Include deleted replies (default: false) |
| `fields` | str | No | Fields to return (default: `"replies(id,content,author,createdTime,modifiedTime,action)"`) |

- **Endpoint:** `GET /drive/v3/files/{fileId}/comments/{commentId}/replies`
- **HTTP Method:** GET

---

#### `gdrive_get_reply`
Get a single reply by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `comment_id` | str | Yes | The comment ID |
| `reply_id` | str | Yes | The reply ID |
| `include_deleted` | bool | No | Include if deleted (default: false) |
| `fields` | str | No | Fields to return |

- **Endpoint:** `GET /drive/v3/files/{fileId}/comments/{commentId}/replies/{replyId}`
- **HTTP Method:** GET

---

#### `gdrive_create_reply`
Reply to a comment. Can also resolve/reopen a comment by setting `action`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `comment_id` | str | Yes | The comment ID |
| `content` | str | Yes | Reply text |
| `action` | str | No | `"resolve"` or `"reopen"` the parent comment |

- **Endpoint:** `POST /drive/v3/files/{fileId}/comments/{commentId}/replies`
- **HTTP Method:** POST

---

#### `gdrive_update_reply`
Update a reply's content.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `comment_id` | str | Yes | The comment ID |
| `reply_id` | str | Yes | The reply ID |
| `content` | str | Yes | New reply text |

- **Endpoint:** `PATCH /drive/v3/files/{fileId}/comments/{commentId}/replies/{replyId}`
- **HTTP Method:** PATCH

---

#### `gdrive_delete_reply`
Delete a reply.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `comment_id` | str | Yes | The comment ID |
| `reply_id` | str | Yes | The reply ID |

- **Endpoint:** `DELETE /drive/v3/files/{fileId}/comments/{commentId}/replies/{replyId}`
- **HTTP Method:** DELETE

---

### Tier 5: Revisions (4 tools)

#### `gdrive_list_revisions`
List revisions of a file.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `page_size` | int | No | Max results (1-200, default 200) |
| `page_token` | str | No | Pagination token |
| `fields` | str | No | Fields to return (default: `"revisions(id,modifiedTime,mimeType,size,keepForever,published,lastModifyingUser)"`) |

- **Endpoint:** `GET /drive/v3/files/{fileId}/revisions`
- **HTTP Method:** GET

---

#### `gdrive_get_revision`
Get metadata for a specific revision.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `revision_id` | str | Yes | The revision ID |
| `fields` | str | No | Fields to return |

- **Endpoint:** `GET /drive/v3/files/{fileId}/revisions/{revisionId}`
- **HTTP Method:** GET

---

#### `gdrive_update_revision`
Update revision metadata (e.g., keep forever, publish).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `revision_id` | str | Yes | The revision ID |
| `keep_forever` | bool | No | Pin this revision so it is not auto-purged |
| `published` | bool | No | Whether this revision is published (Google Docs only) |
| `publish_auto` | bool | No | Whether future revisions auto-publish |
| `published_outside_domain` | bool | No | Whether published outside the domain |

- **Endpoint:** `PATCH /drive/v3/files/{fileId}/revisions/{revisionId}`
- **HTTP Method:** PATCH

---

#### `gdrive_delete_revision`
Permanently delete a revision. Only applicable to files with binary content (not Google Workspace files).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | str | Yes | The file ID |
| `revision_id` | str | Yes | The revision ID |

- **Endpoint:** `DELETE /drive/v3/files/{fileId}/revisions/{revisionId}`
- **HTTP Method:** DELETE

---

### Tier 6: Changes (3 tools)

#### `gdrive_get_start_page_token`
Get the starting page token for listing future changes.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `drive_id` | str | No | Shared drive ID (for shared drive changes) |

- **Endpoint:** `GET /drive/v3/changes/startPageToken`
- **HTTP Method:** GET

---

#### `gdrive_list_changes`
List changes to files the user has access to, starting from a page token.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `page_token` | str | Yes | Token from `gdrive_get_start_page_token` or previous `list_changes` |
| `page_size` | int | No | Max results (1-1000, default 100) |
| `spaces` | str | No | Comma-separated list of spaces: `"drive"`, `"appDataFolder"` (default: `"drive"`) |
| `include_removed` | bool | No | Include changes for removed files (default: true) |
| `include_items_from_all_drives` | bool | No | Include shared drive items (default: false) |
| `fields` | str | No | Fields to return (default: `"nextPageToken,newStartPageToken,changes(fileId,removed,time,file(id,name,mimeType,trashed))"`) |

- **Endpoint:** `GET /drive/v3/changes`
- **HTTP Method:** GET
- **Note:** When `newStartPageToken` is present in the response, no more changes are available and this token should be stored for the next poll.

---

#### `gdrive_watch_changes`
Subscribe to push notifications for changes (sets up a webhook).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `page_token` | str | Yes | Starting page token |
| `channel_id` | str | Yes | Unique channel ID (UUID recommended) |
| `webhook_url` | str | Yes | HTTPS URL to receive notifications |
| `expiration` | str | No | Expiration time in ms since epoch (max ~24h from now) |
| `channel_type` | str | No | Channel type (default: `"web_hook"`) |

- **Endpoint:** `POST /drive/v3/changes/watch`
- **HTTP Method:** POST

---

### Tier 7: Shared Drives (5 tools)

#### `gdrive_list_drives`
List shared drives the service account has access to.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `page_size` | int | No | Max results (1-100, default 10) |
| `page_token` | str | No | Pagination token |
| `q` | str | No | Query string to filter (e.g. `"name contains 'Marketing'"`) |
| `fields` | str | No | Fields to return (default: `"drives(id,name,createdTime,capabilities)"`) |

- **Endpoint:** `GET /drive/v3/drives`
- **HTTP Method:** GET

---

#### `gdrive_get_drive`
Get metadata for a shared drive.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `drive_id` | str | Yes | The shared drive ID |
| `fields` | str | No | Fields to return |

- **Endpoint:** `GET /drive/v3/drives/{driveId}`
- **HTTP Method:** GET

---

#### `gdrive_create_drive`
Create a new shared drive.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Name of the shared drive |
| `request_id` | str | Yes | Idempotency key (UUID recommended; same ID = same drive returned) |

- **Endpoint:** `POST /drive/v3/drives`
- **HTTP Method:** POST
- **Query Param:** `requestId=<request_id>`

---

#### `gdrive_update_drive`
Update a shared drive's name or restrictions.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `drive_id` | str | Yes | The shared drive ID |
| `name` | str | No | New name |
| `restrictions` | dict | No | Restrictions object: `adminManagedRestrictions`, `copyRequiresWriterPermission`, `domainUsersOnly`, `driveMembersOnly` |

- **Endpoint:** `PATCH /drive/v3/drives/{driveId}`
- **HTTP Method:** PATCH

---

#### `gdrive_delete_drive`
Delete a shared drive (must be empty).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `drive_id` | str | Yes | The shared drive ID |

- **Endpoint:** `DELETE /drive/v3/drives/{driveId}`
- **HTTP Method:** DELETE

---

## Tool Summary

| Tier | Category | Tool Count | Tools |
|------|----------|------------|-------|
| 1 | Files | 10 | list_files, get_file, create_file, copy_file, update_file, delete_file, export_file, empty_trash, download_file, stop_channel |
| 2 | Permissions | 5 | list_permissions, get_permission, create_permission, update_permission, delete_permission |
| 3 | Comments | 5 | list_comments, get_comment, create_comment, update_comment, delete_comment |
| 4 | Replies | 5 | list_replies, get_reply, create_reply, update_reply, delete_reply |
| 5 | Revisions | 4 | list_revisions, get_revision, update_revision, delete_revision |
| 6 | Changes | 3 | get_start_page_token, list_changes, watch_changes |
| 7 | Shared Drives | 5 | list_drives, get_drive, create_drive, update_drive, delete_drive |
| **Total** | | **37** | |

---

## Implementation Architecture

### Module: `src/mcp_toolbox/tools/gdrive_tool.py`

```
gdrive_tool.py
├── _get_token() -> str              # Service account token (cached + auto-refresh)
├── _get_client() -> httpx.AsyncClient  # Singleton with Bearer auth
├── _success() -> str                # Standard JSON success response
├── _fid() -> str                    # Default folder ID helper
├── register_tools(mcp: FastMCP)     # All 35 tools registered here
```

### Auth Pattern (exact copy from sheets_tool.py)
```python
_credentials = None
_client: httpx.AsyncClient | None = None

BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

def _get_token() -> str:
    global _credentials
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ToolError("GOOGLE_SERVICE_ACCOUNT_JSON not configured.")
    if _credentials is None:
        from google.oauth2 import service_account
        _credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
    if not _credentials.valid:
        import google.auth.transport.requests
        _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token

async def _get_client() -> httpx.AsyncClient:
    global _client
    token = await asyncio.to_thread(_get_token)
    if _client is None:
        _client = httpx.AsyncClient(base_url=BASE, timeout=30.0)
    _client.headers["Authorization"] = f"Bearer {token}"
    return _client
```

### Upload Client
For file creation/update with content, use a separate `httpx.AsyncClient` with `base_url=UPLOAD_BASE` or construct the full URL manually. The upload requires `multipart/related` content type with two parts: JSON metadata and file content.

### Config Changes (`config.py`)
Add one new variable:
```python
GDRIVE_DEFAULT_FOLDER_ID: str | None = os.getenv("GDRIVE_DEFAULT_FOLDER_ID")
```

### `__init__.py` Changes
Add import and registration:
```python
from .gdrive_tool import register_tools as register_gdrive_tools
# in register_all_tools():
register_gdrive_tools(mcp)
```

### Response Conventions
- All tools return JSON strings via `json.dumps()`
- Success responses: `{"status": "success", "status_code": 200, ...}`
- List responses include `nextPageToken` when more results are available
- File content downloads: return text content directly for text MIME types; for binary, return metadata with `webViewLink`
- Export responses: return text content for text-based exports; indicate unsuitability for binary exports

### Error Handling
- Use `ToolError` for configuration errors (missing credentials, missing required params)
- HTTP errors: raise `ToolError` with status code and API error message from response JSON
- Always include `supportsAllDrives=true` in requests that touch files to ensure shared drive compatibility

---

## Dependencies

### Already Installed (no changes needed)
- `httpx` -- async HTTP client
- `google-auth` -- service account credential handling
- `mcp` -- FastMCP framework

### No New Dependencies Required
The Google Drive API is a standard REST API. All calls use `httpx` directly with Bearer token auth from `google-auth`. No Google-specific SDK needed.

---

## Testing Strategy

### Unit Tests (`tests/test_gdrive_tool.py`)
- Mock `httpx.AsyncClient` responses for every tool
- Test default parameter handling (default folder ID, default fields)
- Test pagination token passthrough
- Test multipart upload construction for file creation with content
- Test error cases: missing credentials, missing required params, API errors

### Integration Tests (manual / CI with service account)
- Create folder -> create file in folder -> list files -> get file -> update file -> delete file -> empty trash
- Share file (create permission) -> list permissions -> update permission -> delete permission
- Add comment -> list comments -> reply -> resolve via reply -> delete comment
- List revisions -> get revision -> update keep_forever
- Get start page token -> make changes -> list changes
- Create shared drive -> list drives -> update drive -> delete drive
