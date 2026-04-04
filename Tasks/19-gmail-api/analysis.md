# Task 19: Gmail API Integration - Analysis & Requirements

## Objective
Add Gmail as a tool integration in mcp-toolbox, exposing email capabilities (messages, threads, labels, drafts, settings, history) as MCP tools for LLM clients. Uses the same Google service account authentication pattern as the existing Sheets integration.

---

## API Technical Details

### Gmail API v1 -- REST
- **Base URL:** `https://gmail.googleapis.com/gmail/v1/users/{userId}`
- **Auth:** Google Service Account with domain-wide delegation and user impersonation
- **Scopes:** `https://mail.google.com/` (full access -- read, send, delete, manage)
- **Format:** JSON request/response; message bodies use base64url encoding
- **API Version:** v1 (stable, current)

### Authentication Flow
1. Load service account credentials from JSON key file via `google.oauth2.service_account.Credentials.from_service_account_file()`
2. Scope the credentials to `https://mail.google.com/`
3. Create delegated credentials via `credentials.with_subject(GMAIL_DELEGATED_USER)` to impersonate the target user
4. Call `credentials.refresh(google.auth.transport.requests.Request())` to obtain/refresh the access token
5. Use `credentials.token` as the Bearer token in httpx request headers
6. Token auto-expires (typically 1 hour); refresh before each request if expired via `credentials.valid` check

**Key difference from Sheets:** Gmail requires `with_subject()` for domain-wide delegation because service accounts cannot own a mailbox. The delegated user is the email address the service account impersonates.

### Configuration Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes | Path to service account JSON key file (reused from Sheets) |
| `GMAIL_DELEGATED_USER` | Yes | Email address to impersonate (e.g., `user@company.com`) |

### Rate Limits

| Metric | Limit |
|--------|-------|
| Daily sending limit | 2,000 messages/day (Google Workspace), 500/day (trial) |
| Per-user rate limit | 250 quota units per second per user |
| Batch requests | 100 calls per batch |
| Messages.send | 100 quota units per call |
| Messages.list | 5 quota units per call |
| Messages.get | 5 quota units per call |
| Messages.modify | 5 quota units per call |
| Messages.delete | 10 quota units per call |
| Messages.insert | 25 quota units per call |
| Threads.list | 10 quota units per call |
| Labels.list | 1 quota unit per call |
| Drafts.create | 10 quota units per call |
| History.list | 2 quota units per call |

- HTTP 429 on rate limit exceed -- implement exponential backoff
- HTTP 403 with `rateLimitExceeded` for per-user quota
- Daily sending quota resets at midnight Pacific Time
- No `Retry-After` header; implement client-side backoff

### REST Resources

The Gmail API v1 has the following REST resources (all under `users/{userId}`):

| Resource | Description |
|----------|-------------|
| `users.messages` | Email messages -- send, list, get, modify, delete, trash, untrash, import, insert, batchModify, batchDelete |
| `users.threads` | Conversation threads -- list, get, modify, delete, trash, untrash |
| `users.labels` | Mailbox labels -- list, get, create, update, patch, delete |
| `users.drafts` | Draft messages -- list, get, create, update, delete, send |
| `users.history` | Mailbox change history -- list |
| `users.settings` | User settings -- getAutoForwarding, getImap, getLanguage, getPop, getVacation, updateAutoForwarding, updateImap, updateLanguage, updatePop, updateVacation |
| `users.settings.sendAs` | Send-as aliases -- list, get, create, update, patch, delete, verify |
| `users.settings.filters` | Email filters -- list, get, create, delete |
| `users.settings.forwardingAddresses` | Forwarding addresses -- list, get, create, delete |
| `users.settings.delegates` | Delegation -- list, get, create, delete |
| `users.profile` | User profile (email, messagesTotal, threadsTotal, historyId) |

---

## Gmail Object Model

```
User (userId = "me" or email address)
  |-- profile (emailAddress, messagesTotal, threadsTotal, historyId)
  |-- messages[]
  |     |-- id (immutable message ID)
  |     |-- threadId (conversation thread ID)
  |     |-- labelIds[] (e.g., "INBOX", "UNREAD", "SENT", "Label_123")
  |     |-- snippet (short plain-text preview)
  |     |-- historyId
  |     |-- internalDate (epoch ms)
  |     |-- sizeEstimate (bytes)
  |     |-- raw (base64url-encoded RFC 2822 message -- only with format=raw)
  |     |-- payload (structured MIME -- only with format=full/metadata/minimal)
  |           |-- mimeType
  |           |-- headers[] (name/value pairs: From, To, Subject, Date, etc.)
  |           |-- body (data in base64url)
  |           |-- parts[] (recursive MIME parts for multipart messages)
  |-- threads[]
  |     |-- id
  |     |-- snippet
  |     |-- historyId
  |     |-- messages[] (ordered list of Message objects in the thread)
  |-- labels[]
  |     |-- id (e.g., "INBOX", "Label_123")
  |     |-- name (display name)
  |     |-- type ("system" or "user")
  |     |-- messageListVisibility ("show" or "hide")
  |     |-- labelListVisibility ("labelShow", "labelShowIfUnread", "labelHide")
  |     |-- color (backgroundColor, textColor)
  |     |-- messagesTotal, messagesUnread, threadsTotal, threadsUnread
  |-- drafts[]
  |     |-- id
  |     |-- message (Message object)
  |-- history[]
  |     |-- id
  |     |-- messages[] (affected messages)
  |     |-- messagesAdded/messagesDeleted/labelsAdded/labelsRemoved
  |-- settings
        |-- sendAs[] (email, displayName, replyToAddress, isPrimary, isDefault)
        |-- filters[] (id, criteria, action)
        |-- forwardingAddresses[] (forwardingEmail, verificationStatus)
        |-- autoForwarding (enabled, emailAddress, disposition)
        |-- vacation (enableAutoReply, responseSubject, responseBodyPlainText, etc.)
```

### Key Data Types

#### Message Format Options (`format` query parameter)
| Value | Returns | Use Case |
|-------|---------|----------|
| `full` | Parsed MIME payload with headers, body, parts | Reading message content |
| `metadata` | Only headers (no body) | Listing with subject/from/to |
| `minimal` | Only id, threadId, labelIds, snippet | Fast enumeration |
| `raw` | Full RFC 2822 in base64url `raw` field | Forwarding, archiving |

#### Label IDs (System Labels)
| Label ID | Meaning |
|----------|---------|
| `INBOX` | Inbox |
| `SENT` | Sent Mail |
| `DRAFT` | Drafts |
| `TRASH` | Trash |
| `SPAM` | Spam |
| `UNREAD` | Unread |
| `STARRED` | Starred |
| `IMPORTANT` | Important |
| `CATEGORY_PERSONAL` | Primary tab |
| `CATEGORY_SOCIAL` | Social tab |
| `CATEGORY_PROMOTIONS` | Promotions tab |
| `CATEGORY_UPDATES` | Updates tab |
| `CATEGORY_FORUMS` | Forums tab |

---

## Key Quirks & Implementation Notes

1. **base64url encoding** -- Message bodies (both in `payload.body.data` and in `raw`) use base64url encoding (RFC 4648 section 5), NOT standard base64. Python: use `base64.urlsafe_b64encode()` / `base64.urlsafe_b64decode()` and strip `=` padding for encoding.

2. **RFC 2822 format for sending** -- `messages.send` accepts the full message as a base64url-encoded RFC 2822 string in the `raw` field. Use Python's `email.mime` module to construct MIME messages, then encode with `base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')`.

3. **userId is always "me"** -- When using delegated credentials (service account impersonating a user), `userId` should be `"me"` in the URL path. The impersonated user is determined by the `with_subject()` call on the credentials, not the URL.

4. **Label IDs vs. names** -- System labels use uppercase string IDs (e.g., `INBOX`, `SENT`). User-created labels get auto-generated IDs like `Label_123`. Always use IDs (not names) in API calls. Provide a `gmail_list_labels` tool so users can discover IDs.

5. **Pagination** -- `messages.list`, `threads.list`, `drafts.list`, and `history.list` all use `pageToken`/`nextPageToken` pagination. Default `maxResults` varies (typically 100). Always expose `max_results` and `page_token` parameters.

6. **Thread model** -- Gmail groups messages into threads automatically. A thread's labels are the union of its messages' labels. Operations on threads (trash, modify labels) apply to ALL messages in the thread.

7. **Trash vs. delete** -- `messages.trash` moves to Trash (recoverable for 30 days). `messages.delete` is permanent and irreversible. Prefer trash in tool implementations; expose delete but document the danger.

8. **Attachments** -- Attachments are MIME parts in `payload.parts[]` with a `body.attachmentId`. Large attachments have their data stored separately and must be fetched via `messages.attachments.get`. Small attachments (< ~5MB) may have data inline.

9. **Sending with attachments** -- Build a multipart MIME message with attachment parts. The entire message is base64url-encoded and sent via `messages.send`. There is no separate "attach file" endpoint.

10. **Search syntax** -- `messages.list` and `threads.list` accept a `q` parameter that supports Gmail search syntax (e.g., `from:user@example.com`, `subject:hello`, `has:attachment`, `after:2024/01/01`, `is:unread`).

11. **Batch modify/delete** -- `messages.batchModify` and `messages.batchDelete` accept up to 1,000 message IDs per request. Useful for bulk label changes or cleanup.

12. **History API** -- Returns incremental changes since a given `historyId`. Useful for sync. Types of changes: `messageAdded`, `messageDeleted`, `labelAdded`, `labelRemoved`. The `startHistoryId` must be from a recent `messages.get` or `profile` call.

13. **Upload for send/insert** -- For messages > 5MB, use resumable upload to `https://www.googleapis.com/upload/gmail/v1/users/{userId}/messages/send`. For typical messages, simple JSON body with `raw` field suffices.

14. **Settings require admin scope** -- Some settings operations (auto-forwarding, delegation) require additional admin privileges. The `https://mail.google.com/` scope covers most settings but delegation management may need domain admin rights.

---

## Tool Specifications

### Tier 1: Messages (12 tools)

#### `gmail_send_message`
Send an email message.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | str | Yes | Recipient email(s), comma-separated |
| `subject` | str | Yes | Email subject line |
| `body` | str | Yes | Email body (plain text) |
| `html_body` | str | No | HTML body (if provided, creates multipart/alternative) |
| `cc` | str | No | CC recipients, comma-separated |
| `bcc` | str | No | BCC recipients, comma-separated |
| `reply_to` | str | No | Reply-To address |
| `in_reply_to` | str | No | Message-ID being replied to (for threading) |
| `references` | str | No | References header (for threading) |
| `thread_id` | str | No | Thread ID to add this message to |

**Returns:** Sent message with `id`, `threadId`, `labelIds`.
**Endpoint:** `POST /gmail/v1/users/me/messages/send`
**Body:** `{"raw": "<base64url-encoded RFC 2822 message>", "threadId": "..."}`
**Implementation:** Build RFC 2822 MIME message using `email.mime.multipart.MIMEMultipart` / `email.mime.text.MIMEText`, set headers, encode with `base64.urlsafe_b64encode`, strip padding.

#### `gmail_send_message_with_attachment`
Send an email with file attachment(s).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | str | Yes | Recipient email(s), comma-separated |
| `subject` | str | Yes | Email subject line |
| `body` | str | Yes | Email body (plain text) |
| `html_body` | str | No | HTML body |
| `cc` | str | No | CC recipients, comma-separated |
| `bcc` | str | No | BCC recipients, comma-separated |
| `attachment_paths` | list[str] | Yes | File paths to attach |
| `thread_id` | str | No | Thread ID to add this message to |

**Returns:** Sent message with `id`, `threadId`, `labelIds`.
**Endpoint:** `POST /gmail/v1/users/me/messages/send`
**Implementation:** Build multipart/mixed MIME message, attach files using `email.mime.base.MIMEBase` with `email.encoders.encode_base64`. Guess MIME type with `mimetypes.guess_type`.

#### `gmail_list_messages`
List messages in the mailbox with optional filtering.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | No | Gmail search query (e.g., `from:user@example.com is:unread`) |
| `label_ids` | list[str] | No | Filter by label IDs (e.g., `["INBOX", "UNREAD"]`) |
| `max_results` | int | No | Max messages to return (default: 20, max: 500) |
| `page_token` | str | No | Token for next page of results |
| `include_spam_trash` | bool | No | Include SPAM and TRASH (default: false) |

**Returns:** List of message stubs (`id`, `threadId`) and `nextPageToken` if more results.
**Endpoint:** `GET /gmail/v1/users/me/messages?q={query}&labelIds={id}&maxResults={n}&pageToken={token}&includeSpamTrash={bool}`

#### `gmail_get_message`
Get a single message by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID |
| `format` | str | No | Response format: `full` (default), `metadata`, `minimal`, `raw` |
| `metadata_headers` | list[str] | No | Headers to include when format=metadata (e.g., `["From", "To", "Subject", "Date"]`) |

**Returns:** Full message resource with payload, headers, body, attachments metadata.
**Endpoint:** `GET /gmail/v1/users/me/messages/{id}?format={format}&metadataHeaders={header}`

#### `gmail_modify_message`
Add or remove labels from a message.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID |
| `add_label_ids` | list[str] | No | Label IDs to add |
| `remove_label_ids` | list[str] | No | Label IDs to remove |

**Returns:** Updated message with `id`, `threadId`, `labelIds`.
**Endpoint:** `POST /gmail/v1/users/me/messages/{id}/modify`
**Body:** `{"addLabelIds": [...], "removeLabelIds": [...]}`

#### `gmail_delete_message`
Permanently delete a message. This is IRREVERSIBLE.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID to permanently delete |

**Returns:** Empty response (204 No Content).
**Endpoint:** `DELETE /gmail/v1/users/me/messages/{id}`

#### `gmail_trash_message`
Move a message to Trash. Recoverable for 30 days.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID to trash |

**Returns:** Updated message resource.
**Endpoint:** `POST /gmail/v1/users/me/messages/{id}/trash`

#### `gmail_untrash_message`
Remove a message from Trash, restoring it to its previous location.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID to untrash |

**Returns:** Updated message resource.
**Endpoint:** `POST /gmail/v1/users/me/messages/{id}/untrash`

#### `gmail_batch_modify_messages`
Add or remove labels from multiple messages at once.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_ids` | list[str] | Yes | Message IDs to modify (max 1,000) |
| `add_label_ids` | list[str] | No | Label IDs to add |
| `remove_label_ids` | list[str] | No | Label IDs to remove |

**Returns:** Empty response (204 No Content) on success.
**Endpoint:** `POST /gmail/v1/users/me/messages/batchModify`
**Body:** `{"ids": [...], "addLabelIds": [...], "removeLabelIds": [...]}`

#### `gmail_batch_delete_messages`
Permanently delete multiple messages. IRREVERSIBLE.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_ids` | list[str] | Yes | Message IDs to permanently delete (max 1,000) |

**Returns:** Empty response (204 No Content) on success.
**Endpoint:** `POST /gmail/v1/users/me/messages/batchDelete`
**Body:** `{"ids": [...]}`

#### `gmail_import_message`
Import a message into the mailbox (similar to receiving via SMTP). Does not send.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `raw` | str | Yes | Base64url-encoded RFC 2822 message |
| `label_ids` | list[str] | No | Labels to apply |
| `internal_date_source` | str | No | `receivedTime` (default) or `dateHeader` |
| `never_mark_spam` | bool | No | Never mark as spam (default: false) |
| `process_for_calendar` | bool | No | Process calendar invites (default: false) |
| `deleted` | bool | No | Mark as deleted (move to Trash) (default: false) |

**Returns:** Imported message with `id`, `threadId`, `labelIds`.
**Endpoint:** `POST /gmail/v1/users/me/messages/import?internalDateSource={src}&neverMarkSpam={bool}&processForCalendar={bool}&deleted={bool}`
**Body:** `{"raw": "...", "labelIds": [...]}`

#### `gmail_insert_message`
Insert a message directly into the mailbox (bypasses spam/sending checks).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `raw` | str | Yes | Base64url-encoded RFC 2822 message |
| `label_ids` | list[str] | No | Labels to apply |
| `internal_date_source` | str | No | `receivedTime` (default) or `dateHeader` |
| `deleted` | bool | No | Mark as deleted (default: false) |

**Returns:** Inserted message with `id`, `threadId`, `labelIds`.
**Endpoint:** `POST /gmail/v1/users/me/messages?internalDateSource={src}&deleted={bool}`
**Body:** `{"raw": "...", "labelIds": [...]}`

---

### Tier 2: Threads (6 tools)

#### `gmail_list_threads`
List conversation threads.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | No | Gmail search query |
| `label_ids` | list[str] | No | Filter by label IDs |
| `max_results` | int | No | Max threads to return (default: 20, max: 500) |
| `page_token` | str | No | Token for next page |
| `include_spam_trash` | bool | No | Include SPAM and TRASH (default: false) |

**Returns:** List of thread stubs (`id`, `snippet`, `historyId`) and `nextPageToken`.
**Endpoint:** `GET /gmail/v1/users/me/threads?q={query}&labelIds={id}&maxResults={n}&pageToken={token}&includeSpamTrash={bool}`

#### `gmail_get_thread`
Get a thread and all its messages.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `thread_id` | str | Yes | Thread ID |
| `format` | str | No | Message format: `full` (default), `metadata`, `minimal` |
| `metadata_headers` | list[str] | No | Headers to include when format=metadata |

**Returns:** Thread with `id`, `snippet`, `historyId`, and nested `messages[]` array.
**Endpoint:** `GET /gmail/v1/users/me/threads/{id}?format={format}&metadataHeaders={header}`

#### `gmail_modify_thread`
Add or remove labels from all messages in a thread.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `thread_id` | str | Yes | Thread ID |
| `add_label_ids` | list[str] | No | Label IDs to add |
| `remove_label_ids` | list[str] | No | Label IDs to remove |

**Returns:** Updated thread resource.
**Endpoint:** `POST /gmail/v1/users/me/threads/{id}/modify`
**Body:** `{"addLabelIds": [...], "removeLabelIds": [...]}`

#### `gmail_delete_thread`
Permanently delete a thread and all its messages. IRREVERSIBLE.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `thread_id` | str | Yes | Thread ID to permanently delete |

**Returns:** Empty response (204 No Content).
**Endpoint:** `DELETE /gmail/v1/users/me/threads/{id}`

#### `gmail_trash_thread`
Move a thread and all its messages to Trash.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `thread_id` | str | Yes | Thread ID to trash |

**Returns:** Updated thread resource.
**Endpoint:** `POST /gmail/v1/users/me/threads/{id}/trash`

#### `gmail_untrash_thread`
Remove a thread from Trash, restoring all its messages.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `thread_id` | str | Yes | Thread ID to untrash |

**Returns:** Updated thread resource.
**Endpoint:** `POST /gmail/v1/users/me/threads/{id}/untrash`

---

### Tier 3: Labels (6 tools)

#### `gmail_list_labels`
List all labels in the mailbox.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** Array of label objects with `id`, `name`, `type`, message/thread counts.
**Endpoint:** `GET /gmail/v1/users/me/labels`

#### `gmail_get_label`
Get a single label's details.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `label_id` | str | Yes | Label ID (e.g., `INBOX`, `Label_123`) |

**Returns:** Full label resource including counts.
**Endpoint:** `GET /gmail/v1/users/me/labels/{id}`

#### `gmail_create_label`
Create a new user label.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Label name (supports nesting with `/`, e.g., `Projects/Active`) |
| `message_list_visibility` | str | No | `show` (default) or `hide` |
| `label_list_visibility` | str | No | `labelShow` (default), `labelShowIfUnread`, or `labelHide` |
| `background_color` | str | No | Background hex color (e.g., `#16a765`) |
| `text_color` | str | No | Text hex color (e.g., `#ffffff`) |

**Returns:** Created label with auto-generated `id`.
**Endpoint:** `POST /gmail/v1/users/me/labels`
**Body:**
```json
{
  "name": "Projects/Active",
  "messageListVisibility": "show",
  "labelListVisibility": "labelShow",
  "color": {"backgroundColor": "#16a765", "textColor": "#ffffff"}
}
```

#### `gmail_update_label`
Update a label's properties (full update, replaces all mutable fields).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `label_id` | str | Yes | Label ID to update |
| `name` | str | No | New name |
| `message_list_visibility` | str | No | `show` or `hide` |
| `label_list_visibility` | str | No | `labelShow`, `labelShowIfUnread`, or `labelHide` |
| `background_color` | str | No | Background hex color |
| `text_color` | str | No | Text hex color |

**Returns:** Updated label resource.
**Endpoint:** `PUT /gmail/v1/users/me/labels/{id}`
**Body:** Full label object with all fields.

#### `gmail_patch_label`
Partially update a label (only specified fields change).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `label_id` | str | Yes | Label ID to patch |
| `name` | str | No | New name |
| `message_list_visibility` | str | No | `show` or `hide` |
| `label_list_visibility` | str | No | `labelShow`, `labelShowIfUnread`, or `labelHide` |
| `background_color` | str | No | Background hex color |
| `text_color` | str | No | Text hex color |

**Returns:** Updated label resource.
**Endpoint:** `PATCH /gmail/v1/users/me/labels/{id}`
**Body:** Only the fields to update.

#### `gmail_delete_label`
Delete a user label. System labels cannot be deleted.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `label_id` | str | Yes | Label ID to delete |

**Returns:** Empty response (204 No Content).
**Endpoint:** `DELETE /gmail/v1/users/me/labels/{id}`

---

### Tier 4: Drafts (6 tools)

#### `gmail_list_drafts`
List drafts in the mailbox.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | No | Gmail search query |
| `max_results` | int | No | Max drafts to return (default: 20, max: 500) |
| `page_token` | str | No | Token for next page |
| `include_spam_trash` | bool | No | Include SPAM and TRASH (default: false) |

**Returns:** List of draft stubs (`id`, `message.id`, `message.threadId`) and `nextPageToken`.
**Endpoint:** `GET /gmail/v1/users/me/drafts?q={query}&maxResults={n}&pageToken={token}&includeSpamTrash={bool}`

#### `gmail_get_draft`
Get a draft and its message content.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `draft_id` | str | Yes | Draft ID |
| `format` | str | No | Message format: `full` (default), `metadata`, `minimal`, `raw` |

**Returns:** Draft with `id` and nested `message` resource.
**Endpoint:** `GET /gmail/v1/users/me/drafts/{id}?format={format}`

#### `gmail_create_draft`
Create a new draft.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | str | No | Recipient email(s), comma-separated |
| `subject` | str | No | Email subject line |
| `body` | str | No | Email body (plain text) |
| `html_body` | str | No | HTML body |
| `cc` | str | No | CC recipients, comma-separated |
| `bcc` | str | No | BCC recipients, comma-separated |
| `reply_to` | str | No | Reply-To address |
| `in_reply_to` | str | No | Message-ID for threading |
| `references` | str | No | References header for threading |
| `thread_id` | str | No | Thread ID |

**Returns:** Created draft with `id` and `message` stub.
**Endpoint:** `POST /gmail/v1/users/me/drafts`
**Body:** `{"message": {"raw": "<base64url-encoded RFC 2822>", "threadId": "..."}}`

#### `gmail_update_draft`
Replace a draft's content with new content.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `draft_id` | str | Yes | Draft ID to update |
| `to` | str | No | Recipient email(s) |
| `subject` | str | No | Email subject |
| `body` | str | No | Email body (plain text) |
| `html_body` | str | No | HTML body |
| `cc` | str | No | CC recipients |
| `bcc` | str | No | BCC recipients |
| `thread_id` | str | No | Thread ID |

**Returns:** Updated draft with `id` and `message` stub.
**Endpoint:** `PUT /gmail/v1/users/me/drafts/{id}`
**Body:** `{"message": {"raw": "<base64url-encoded RFC 2822>", "threadId": "..."}}`

#### `gmail_delete_draft`
Delete a draft. Does not send.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `draft_id` | str | Yes | Draft ID to delete |

**Returns:** Empty response (204 No Content).
**Endpoint:** `DELETE /gmail/v1/users/me/drafts/{id}`

#### `gmail_send_draft`
Send an existing draft.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `draft_id` | str | Yes | Draft ID to send |

**Returns:** Sent message with `id`, `threadId`, `labelIds`.
**Endpoint:** `POST /gmail/v1/users/me/drafts/send`
**Body:** `{"id": "<draft_id>"}`

---

### Tier 5: History (1 tool)

#### `gmail_list_history`
List mailbox change history since a given history ID. Useful for incremental sync.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `start_history_id` | str | Yes | History ID to start from (obtain from message.historyId or profile.historyId) |
| `label_id` | str | No | Filter history to changes involving this label |
| `history_types` | list[str] | No | Filter by type: `messageAdded`, `messageDeleted`, `labelAdded`, `labelRemoved` |
| `max_results` | int | No | Max history records (default: 100, max: 500) |
| `page_token` | str | No | Token for next page |

**Returns:** History records with changed messages and `nextPageToken`.
**Endpoint:** `GET /gmail/v1/users/me/history?startHistoryId={id}&labelId={id}&historyTypes={type}&maxResults={n}&pageToken={token}`

---

### Tier 6: Settings (13 tools)

#### `gmail_get_vacation_settings`
Get vacation (out-of-office) auto-reply settings.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** Vacation settings including `enableAutoReply`, `responseSubject`, `responseBodyPlainText`, `responseBodyHtml`, `startTime`, `endTime`, `restrictToContacts`, `restrictToDomain`.
**Endpoint:** `GET /gmail/v1/users/me/settings/vacation`

#### `gmail_update_vacation_settings`
Update vacation auto-reply settings.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `enable_auto_reply` | bool | Yes | Enable or disable auto-reply |
| `response_subject` | str | No | Auto-reply subject |
| `response_body_plain_text` | str | No | Plain text auto-reply body |
| `response_body_html` | str | No | HTML auto-reply body |
| `start_time` | int | No | Start time in epoch ms (UTC) |
| `end_time` | int | No | End time in epoch ms (UTC) |
| `restrict_to_contacts` | bool | No | Only reply to known contacts |
| `restrict_to_domain` | bool | No | Only reply to same domain |

**Returns:** Updated vacation settings.
**Endpoint:** `PUT /gmail/v1/users/me/settings/vacation`
**Body:** Full vacation settings object.

#### `gmail_get_auto_forwarding`
Get auto-forwarding settings.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** Auto-forwarding config: `enabled`, `emailAddress`, `disposition` (`leaveInInbox`, `archive`, `trash`, `markRead`).
**Endpoint:** `GET /gmail/v1/users/me/settings/autoForwarding`

#### `gmail_update_auto_forwarding`
Update auto-forwarding settings.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | bool | Yes | Enable or disable forwarding |
| `email_address` | str | No | Forwarding address (must be verified) |
| `disposition` | str | No | What to do with forwarded messages: `leaveInInbox`, `archive`, `trash`, `markRead` |

**Returns:** Updated forwarding settings.
**Endpoint:** `PUT /gmail/v1/users/me/settings/autoForwarding`

#### `gmail_get_imap_settings`
Get IMAP access settings.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** IMAP settings: `enabled`, `autoExpunge`, `expungeBehavior`, `maxFolderSize`.
**Endpoint:** `GET /gmail/v1/users/me/settings/imap`

#### `gmail_get_pop_settings`
Get POP access settings.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** POP settings: `accessWindow`, `disposition`.
**Endpoint:** `GET /gmail/v1/users/me/settings/pop`

#### `gmail_update_imap_settings`
Update IMAP access settings.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | bool | Yes | Enable or disable IMAP |
| `auto_expunge` | bool | No | Auto-expunge on delete |
| `expunge_behavior` | str | No | `archive`, `deleteForever`, `trash` |
| `max_folder_size` | int | No | Max folder size (0 = no limit) |

**Returns:** Updated IMAP settings.
**Endpoint:** `PUT /gmail/v1/users/me/settings/imap`

#### `gmail_update_pop_settings`
Update POP access settings.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `access_window` | str | Yes | `disabled`, `allMail`, `fromNowOn` |
| `disposition` | str | No | `leaveInInbox`, `archive`, `trash`, `markRead` |

**Returns:** Updated POP settings.
**Endpoint:** `PUT /gmail/v1/users/me/settings/pop`

#### `gmail_get_language_settings`
Get the user's language/display settings.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** Language settings: `displayLanguage`.
**Endpoint:** `GET /gmail/v1/users/me/settings/language`

#### `gmail_update_language_settings`
Update the user's display language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `display_language` | str | Yes | BCP 47 language tag (e.g., `en`, `fr`, `ja`) |

**Returns:** Updated language settings.
**Endpoint:** `PUT /gmail/v1/users/me/settings/language`
**Body:** `{"displayLanguage": "en"}`

#### `gmail_get_profile`
Get the user's profile (email, total counts, history ID).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** `emailAddress`, `messagesTotal`, `threadsTotal`, `historyId`.
**Endpoint:** `GET /gmail/v1/users/me/profile`

---

### Tier 7: Send-As Aliases (7 tools)

#### `gmail_list_send_as`
List send-as aliases for the user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** Array of send-as objects: `sendAsEmail`, `displayName`, `replyToAddress`, `isPrimary`, `isDefault`, `verificationStatus`.
**Endpoint:** `GET /gmail/v1/users/me/settings/sendAs`

#### `gmail_get_send_as`
Get a specific send-as alias.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `send_as_email` | str | Yes | Send-as email address |

**Returns:** Full send-as resource.
**Endpoint:** `GET /gmail/v1/users/me/settings/sendAs/{sendAsEmail}`

#### `gmail_create_send_as`
Create a new send-as alias. Requires verification.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `send_as_email` | str | Yes | Email address for the alias |
| `display_name` | str | No | Display name for the alias |
| `reply_to_address` | str | No | Reply-to address |
| `is_default` | bool | No | Set as default send-as (default: false) |
| `treat_as_alias` | bool | No | Treat as alias for reply behavior (default: true) |
| `smtp_host` | str | No | SMTP server for sending (if custom) |
| `smtp_port` | int | No | SMTP port |
| `smtp_username` | str | No | SMTP username |
| `smtp_password` | str | No | SMTP password |
| `smtp_security_mode` | str | No | `none`, `ssl`, or `starttls` |

**Returns:** Created send-as resource (status: `pending` until verified).
**Endpoint:** `POST /gmail/v1/users/me/settings/sendAs`
**Body:** Full send-as configuration.

#### `gmail_update_send_as`
Update a send-as alias configuration.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `send_as_email` | str | Yes | Send-as email to update |
| `display_name` | str | No | New display name |
| `reply_to_address` | str | No | New reply-to address |
| `is_default` | bool | No | Set as default |

**Returns:** Updated send-as resource.
**Endpoint:** `PUT /gmail/v1/users/me/settings/sendAs/{sendAsEmail}`

#### `gmail_patch_send_as`
Partially update a send-as alias (only provided fields change).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `send_as_email` | str | Yes | Send-as email to patch |
| `display_name` | str | No | New display name |
| `reply_to_address` | str | No | New reply-to address |
| `is_default` | bool | No | Set as default |

**Returns:** Updated send-as resource.
**Endpoint:** `PATCH /gmail/v1/users/me/settings/sendAs/{sendAsEmail}`

#### `gmail_delete_send_as`
Delete a send-as alias. Cannot delete the primary address.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `send_as_email` | str | Yes | Send-as email to delete |

**Returns:** Empty response (204 No Content).
**Endpoint:** `DELETE /gmail/v1/users/me/settings/sendAs/{sendAsEmail}`

#### `gmail_verify_send_as`
Send a verification email for a send-as alias.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `send_as_email` | str | Yes | Send-as email to verify |

**Returns:** Empty response (204 No Content).
**Endpoint:** `POST /gmail/v1/users/me/settings/sendAs/{sendAsEmail}/verify`

---

### Tier 8: Filters (4 tools)

#### `gmail_list_filters`
List all email filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** Array of filter objects with `id`, `criteria`, `action`.
**Endpoint:** `GET /gmail/v1/users/me/settings/filters`

#### `gmail_get_filter`
Get a specific email filter by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `filter_id` | str | Yes | Filter ID |

**Returns:** Filter object with `id`, `criteria`, `action`.
**Endpoint:** `GET /gmail/v1/users/me/settings/filters/{id}`

#### `gmail_create_filter`
Create a new email filter.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `criteria_from` | str | No | Match sender |
| `criteria_to` | str | No | Match recipient |
| `criteria_subject` | str | No | Match subject |
| `criteria_query` | str | No | Gmail search query to match |
| `criteria_negated_query` | str | No | Negated search query |
| `criteria_has_attachment` | bool | No | Match messages with attachments |
| `criteria_exclude_chats` | bool | No | Exclude chat messages |
| `criteria_size` | int | No | Size in bytes for comparison |
| `criteria_size_comparison` | str | No | `larger` or `smaller` |
| `action_add_label_ids` | list[str] | No | Labels to add |
| `action_remove_label_ids` | list[str] | No | Labels to remove |
| `action_forward` | str | No | Forward to email (must be verified forwarding address) |

**Returns:** Created filter with auto-generated `id`.
**Endpoint:** `POST /gmail/v1/users/me/settings/filters`
**Body:**
```json
{
  "criteria": {
    "from": "...", "to": "...", "subject": "...",
    "query": "...", "negatedQuery": "...",
    "hasAttachment": true, "excludeChats": true,
    "size": 1024, "sizeComparison": "larger"
  },
  "action": {
    "addLabelIds": [...], "removeLabelIds": [...],
    "forward": "user@example.com"
  }
}
```

#### `gmail_delete_filter`
Delete an email filter.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `filter_id` | str | Yes | Filter ID to delete |

**Returns:** Empty response (204 No Content).
**Endpoint:** `DELETE /gmail/v1/users/me/settings/filters/{id}`

---

### Tier 9: Forwarding Addresses (4 tools)

#### `gmail_list_forwarding_addresses`
List forwarding addresses.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** Array of forwarding address objects: `forwardingEmail`, `verificationStatus`.
**Endpoint:** `GET /gmail/v1/users/me/settings/forwardingAddresses`

#### `gmail_get_forwarding_address`
Get a specific forwarding address.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `forwarding_email` | str | Yes | Forwarding email address |

**Returns:** Forwarding address with `forwardingEmail`, `verificationStatus`.
**Endpoint:** `GET /gmail/v1/users/me/settings/forwardingAddresses/{forwardingEmail}`

#### `gmail_create_forwarding_address`
Add a new forwarding address. Sends verification email.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `forwarding_email` | str | Yes | Email address to add as forwarding destination |

**Returns:** Created forwarding address with `verificationStatus: pending`.
**Endpoint:** `POST /gmail/v1/users/me/settings/forwardingAddresses`
**Body:** `{"forwardingEmail": "user@example.com"}`

#### `gmail_delete_forwarding_address`
Delete a forwarding address.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `forwarding_email` | str | Yes | Forwarding email to remove |

**Returns:** Empty response (204 No Content).
**Endpoint:** `DELETE /gmail/v1/users/me/settings/forwardingAddresses/{forwardingEmail}`

---

### Tier 10: Delegates (4 tools)

#### `gmail_list_delegates`
List delegates who have access to this account.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** Array of delegate objects: `delegateEmail`, `verificationStatus`.
**Endpoint:** `GET /gmail/v1/users/me/settings/delegates`

#### `gmail_get_delegate`
Get a specific delegate.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `delegate_email` | str | Yes | Delegate email address |

**Returns:** Delegate object with `delegateEmail`, `verificationStatus`.
**Endpoint:** `GET /gmail/v1/users/me/settings/delegates/{delegateEmail}`

#### `gmail_create_delegate`
Add a delegate to the account.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `delegate_email` | str | Yes | Email of the delegate to add |

**Returns:** Created delegate with `verificationStatus`.
**Endpoint:** `POST /gmail/v1/users/me/settings/delegates`
**Body:** `{"delegateEmail": "delegate@example.com"}`

#### `gmail_delete_delegate`
Remove a delegate from the account.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `delegate_email` | str | Yes | Email of the delegate to remove |

**Returns:** Empty response (204 No Content).
**Endpoint:** `DELETE /gmail/v1/users/me/settings/delegates/{delegateEmail}`

---

### Tier 11: Attachments (1 tool)

#### `gmail_get_attachment`
Get the data of a specific message attachment.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | str | Yes | Message ID containing the attachment |
| `attachment_id` | str | Yes | Attachment ID from message payload parts |

**Returns:** Attachment data in base64url encoding: `{"size": ..., "data": "..."}`.
**Endpoint:** `GET /gmail/v1/users/me/messages/{messageId}/attachments/{id}`

---

## Tool Count Summary

| Tier | Category | Tool Count |
|------|----------|------------|
| Tier 1 | Messages | 12 |
| Tier 2 | Threads | 6 |
| Tier 3 | Labels | 6 |
| Tier 4 | Drafts | 6 |
| Tier 5 | History | 1 |
| Tier 6 | Settings & Profile | 13 |
| Tier 7 | Send-As Aliases | 7 |
| Tier 8 | Filters | 4 |
| Tier 9 | Forwarding Addresses | 4 |
| Tier 10 | Delegates | 4 |
| Tier 11 | Attachments | 1 |
| **Total** | | **62** |

---

## Architecture Decisions

### 1. Reuse Existing Service Account Credential Path
The `GOOGLE_SERVICE_ACCOUNT_JSON` config var is already defined in `config.py` for Sheets. Gmail reuses it, adding only `GMAIL_DELEGATED_USER` for impersonation. This avoids credential sprawl.

### 2. Domain-Wide Delegation with `with_subject()`
Unlike Sheets (where the service account is shared directly on spreadsheets), Gmail requires domain-wide delegation. The service account impersonates a real user via `credentials.with_subject(email)`. This means:
- The Google Workspace admin must grant the service account domain-wide delegation
- The scope `https://mail.google.com/` must be authorized in the Admin Console
- The `GMAIL_DELEGATED_USER` email must be a real user in the domain

### 3. Separate httpx Client from Sheets
Gmail uses a different base URL (`gmail.googleapis.com`) and different scopes. The module will have its own `_credentials` and `_client` singletons, similar to Sheets but with the delegation addition. The `_get_token()` helper creates delegated credentials.

### 4. userId is Always "me"
With delegated credentials, the userId path parameter is always `"me"`. The actual user is determined by the `with_subject()` call. This simplifies URL construction -- no need for a userId parameter on every tool.

### 5. MIME Message Construction as Helper
A shared `_build_message()` helper function constructs RFC 2822 MIME messages from parameters (to, subject, body, html_body, cc, bcc, attachments). This is reused by `gmail_send_message`, `gmail_send_message_with_attachment`, `gmail_create_draft`, and `gmail_update_draft`. The helper returns a base64url-encoded string ready for the `raw` field.

### 6. Response Body Decoding Helper
A `_decode_body()` helper extracts and decodes the message body from the nested MIME payload structure. It handles:
- Single-part messages (body in `payload.body.data`)
- Multipart messages (recursively walks `payload.parts[]`)
- Returns both plain text and HTML when available

### 7. Error Handling Pattern
Follow the Sheets pattern: `_req()` helper handles HTTP errors, 429 rate limits, and JSON parsing. Return `ToolError` with descriptive messages.

### 8. No Additional Dependencies
Gmail integration uses the same `google-auth` library as Sheets, plus Python stdlib `email.mime`, `base64`, and `mimetypes`. No new pip packages needed.

### 9. pyright Compatibility
Unlike some integrations (SendGrid, Stripe), the Gmail tool uses only typed libraries (`google-auth`, `httpx`, stdlib). It should be pyright-compatible with no exclusions needed.

### 10. File Layout
Single file: `src/mcp_toolbox/tools/gmail_tool.py`. Registration via `register_tools(mcp: FastMCP)` as per project convention.

---

## Config Changes Required

### `config.py` additions:
```python
# Gmail (reuses GOOGLE_SERVICE_ACCOUNT_JSON)
GMAIL_DELEGATED_USER: str | None = os.getenv("GMAIL_DELEGATED_USER")
```

### `tools/__init__.py` additions:
```python
from mcp_toolbox.tools import gmail_tool
# ...
gmail_tool.register_tools(mcp)
```

### `.env` additions:
```
GMAIL_DELEGATED_USER=user@company.com
```

---

## Implementation Helper Functions

### `_get_token() -> str`
Loads service account credentials, calls `with_subject(GMAIL_DELEGATED_USER)`, refreshes token if expired, returns Bearer token string.

### `_get_client() -> httpx.AsyncClient`
Singleton async HTTP client with base URL `https://gmail.googleapis.com/gmail/v1/users/me`. Refreshes Bearer token header on each call.

### `_req(method, url, json_body?, params?) -> dict | list`
Generic request helper (mirrors Sheets). Handles errors, 429, JSON parsing.

### `_build_message(to?, subject?, body?, html_body?, cc?, bcc?, reply_to?, in_reply_to?, references?, attachment_paths?) -> str`
Constructs RFC 2822 MIME message and returns base64url-encoded string. Handles:
- Plain text only
- HTML only
- Multipart/alternative (text + HTML)
- Multipart/mixed (with attachments)

### `_decode_body(payload: dict) -> dict`
Extracts body content from Gmail message payload. Returns `{"plain": "...", "html": "..."}`.

### `_success(sc: int, **kw) -> str`
Standard success response formatter (same as Sheets).

---

## Testing Strategy

### Unit Tests (`tests/test_gmail_tool.py`)
- Mock httpx responses for each tool
- Test `_build_message()` helper produces valid RFC 2822
- Test `_decode_body()` helper with various MIME structures
- Test base64url encoding/decoding
- Test error handling (429, 400, 403)
- Test pagination parameter passing
- Test that `with_subject()` is called with `GMAIL_DELEGATED_USER`

### Integration Tests (manual, requires credentials)
- Send a test email and verify delivery
- Create/send/delete draft lifecycle
- Label CRUD lifecycle
- Thread listing and modification
- Filter creation and deletion

---

## Google Workspace Admin Setup Required

1. **Enable Gmail API** in Google Cloud Console for the project
2. **Create/use service account** with domain-wide delegation enabled
3. **Admin Console > Security > API Controls > Domain-wide Delegation:**
   - Add the service account client ID
   - Authorize scope: `https://mail.google.com/`
4. **Set environment variables:**
   - `GOOGLE_SERVICE_ACCOUNT_JSON` = path to key file
   - `GMAIL_DELEGATED_USER` = email to impersonate
