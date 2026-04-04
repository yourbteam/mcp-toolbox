# Task 25: Zendesk Integration - Analysis & Requirements

## Objective
Add Zendesk Support as a tool integration in mcp-toolbox, exposing customer support ticket management, user/organization administration, views, search, and satisfaction tracking as MCP tools for LLM clients.

---

## API Technical Details

### Zendesk Support REST API v2
- **Base URL:** `https://{subdomain}.zendesk.com/api/v2`
- **Auth:** Basic Authentication — `Authorization: Basic base64({email}/token:{api_token})`
  - The literal string `/token:` separates the email from the API token
  - Alternative: OAuth2 Bearer token — `Authorization: Bearer {access_token}`
- **Format:** JSON request/response (`Content-Type: application/json`)
- **SDK:** None — direct `httpx.AsyncClient` (same pattern as Jira)

### Configuration
| Variable | Required | Description |
|----------|----------|-------------|
| `ZENDESK_SUBDOMAIN` | Yes | Zendesk subdomain (e.g., `mycompany` for `mycompany.zendesk.com`) |
| `ZENDESK_EMAIL` | Yes | Agent email address (used with API token auth) |
| `ZENDESK_API_TOKEN` | Yes | API token (Admin > Channels > API) |

### Rate Limits

Rate limits vary by Zendesk plan:

| Plan | Rate Limit (RPM) |
|------|-------------------|
| **Essential / Team** | 200 requests per minute |
| **Growth / Professional** | 400 requests per minute |
| **Enterprise** | 700 requests per minute |
| **High Volume API Add-on** | 2,500 requests per minute |

- HTTP 429 `Too Many Requests` on exceed
- Response header: `Retry-After` (seconds to wait)
- Response header: `X-Rate-Limit` (current limit)
- Response header: `X-Rate-Limit-Remaining` (remaining requests in window)
- Limits apply globally per account, not per token
- Some endpoints have additional restrictive limits (e.g., ticket imports: 100 RPM)

### Key Quirks

1. **Wrapper keys** — All responses wrap data in a top-level key matching the resource name. A single ticket returns `{"ticket": {...}}`, a list returns `{"tickets": [...]}`. Create/update requests must also wrap the payload (e.g., `{"ticket": {...}}`).

2. **Pagination** — Three styles available:
   - **Cursor-based (preferred):** `page[size]=100&page[after]=cursor_value`. Response includes `"meta": {"has_more": true, "after_cursor": "..."}` and `"links": {"next": "..."}`. Maximum 100 per page.
   - **Offset-based (legacy):** `per_page=100&page=2`. Limited to first 10,000 records. Most list endpoints still support this.
   - **CBP (Cursor-Based Pagination) export:** For bulk exports, use `GET /api/v2/incremental/tickets/cursor.json`.

3. **Sideloading** — Many list endpoints support `?include=` to embed related objects in the response (e.g., `?include=users,groups` on ticket list). Reduces API calls. Available includes vary per endpoint.

4. **Ticket comments vs. conversation** — Comments are the primary communication unit. Each comment has `public` (boolean) to control whether it is visible to the requester or is an internal/private note. Comments are append-only; you cannot edit or delete them after creation.

5. **Custom fields** — Ticket custom fields are set/read via `custom_fields` array: `[{"id": 12345, "value": "foo"}]`. Organization and user custom fields use `organization_fields` and `user_fields` hashes respectively.

6. **Tags** — Tags are simple strings on tickets, users, and organizations. They are set as a full replacement array, not incremental. Use `PUT` with the complete tag list, or use the dedicated safe `tags` endpoints with `PUT` (set), `POST` (add), `DELETE` (remove).

7. **Soft delete** — Deleting a ticket moves it to "Deleted Tickets" (recoverable for 30 days). Users can be soft-deleted (suspended) or permanently deleted. Organizations are hard-deleted immediately.

8. **Ticket status** — Standard statuses: `new`, `open`, `pending`, `hold`, `solved`, `closed`. Only system can set `closed`. Custom ticket statuses available on Enterprise plans.

9. **Search API** — Unified search across tickets, users, organizations via `/api/v2/search.json?query=`. Uses Zendesk Query Language (ZQL). Results limited to 1,000 per query. Anonymous search counts available at `/api/v2/search/count.json`.

10. **Merge** — Ticket merge combines two tickets into one (comments from source move to target). User merge combines two user profiles. Both are destructive and irreversible.

11. **Attachments** — Upload first via `POST /api/v2/uploads.json?filename=` (multipart), receive a token, then reference the token in a comment's `uploads` array.

12. **Suspended tickets** — Spam-filtered or flagged tickets land in a separate suspended queue with their own CRUD endpoints.

---

## Tool Specifications

### Tier 1: Ticket Management (16 tools)

#### `zendesk_create_ticket`
Create a new support ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | str | Yes | Ticket subject line |
| `description` | str | Yes | Initial comment body (becomes first comment) |
| `requester_email` | str | No | Requester email (creates user if not found) |
| `requester_id` | int | No | Requester user ID (alternative to email) |
| `assignee_id` | int | No | Assignee agent user ID |
| `group_id` | int | No | Assigned group ID |
| `priority` | str | No | `urgent`, `high`, `normal`, `low` |
| `type` | str | No | `problem`, `incident`, `question`, `task` |
| `status` | str | No | `new`, `open`, `pending`, `hold`, `solved` |
| `tags` | list[str] | No | Tags to apply |
| `custom_fields` | list[dict] | No | Custom fields as `[{"id": 123, "value": "x"}]` |
| `external_id` | str | No | External system ID for cross-reference |
| `due_at` | str | No | Due date (ISO 8601, for task-type tickets) |

**Returns:** Created ticket object with ID.
**Endpoint:** `POST /api/v2/tickets.json`

#### `zendesk_get_ticket`
Get a single ticket by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Ticket ID |
| `include` | str | No | Sideload related objects (comma-separated: `users`, `groups`, `organizations`, `sharing_agreements`, `comment_count`, `incident_counts`, `dates`, `metric_sets`) |

**Returns:** Ticket object with all fields.
**Endpoint:** `GET /api/v2/tickets/{ticket_id}.json`

#### `zendesk_update_ticket`
Update ticket fields.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Ticket ID |
| `subject` | str | No | New subject |
| `status` | str | No | New status |
| `priority` | str | No | New priority |
| `type` | str | No | New type |
| `assignee_id` | int | No | New assignee user ID |
| `group_id` | int | No | New group ID |
| `tags` | list[str] | No | Replace all tags |
| `custom_fields` | list[dict] | No | Custom fields to update |
| `due_at` | str | No | Due date (ISO 8601) |
| `external_id` | str | No | External ID |
| `comment` | dict | No | Comment to add: `{"body": "text", "public": true}` |

**Returns:** Updated ticket object.
**Endpoint:** `PUT /api/v2/tickets/{ticket_id}.json`

#### `zendesk_delete_ticket`
Soft-delete a ticket (moves to Deleted Tickets, recoverable for 30 days).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Ticket ID |

**Returns:** Confirmation (204 No Content).
**Endpoint:** `DELETE /api/v2/tickets/{ticket_id}.json`

#### `zendesk_list_tickets`
List tickets (all, or filtered by requester/assignee/org via sub-endpoints).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `requester_id` | int | No | List tickets by requester (uses `/users/{id}/tickets/requested.json`) |
| `assignee_id` | int | No | List tickets by assignee (uses `/users/{id}/tickets/assigned.json`) |
| `organization_id` | int | No | List tickets by org (uses `/organizations/{id}/tickets.json`) |
| `sort_by` | str | No | Sort field: `created_at`, `updated_at`, `priority`, `status`, `ticket_type` |
| `sort_order` | str | No | `asc` or `desc` |
| `page_size` | int | No | Results per page (max 100, default 100) |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of ticket objects with pagination metadata.
**Endpoint:** `GET /api/v2/tickets.json` (default), or sub-endpoint when filter provided (cursor pagination)
**Note:** Only one filter (requester_id, assignee_id, or organization_id) at a time. For complex filtering, use `zendesk_search`.

#### `zendesk_add_ticket_comment`
Add a public reply or internal note to a ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Ticket ID |
| `body` | str | Yes | Comment body (plain text or HTML) |
| `public` | bool | No | `true` for public reply, `false` for internal note (default `true`) |
| `author_id` | int | No | Comment author user ID (defaults to authenticated user) |
| `html_body` | str | No | HTML body (overrides `body` if provided) |
| `upload_tokens` | list[str] | No | Attachment upload tokens from `zendesk_upload_attachment` |

**Returns:** Updated ticket with new comment.
**Endpoint:** `PUT /api/v2/tickets/{ticket_id}.json` (comment added via `ticket.comment` field)

#### `zendesk_list_ticket_comments`
List all comments on a ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Ticket ID |
| `sort_order` | str | No | `asc` or `desc` (default `asc`) |
| `include_inline_images` | bool | No | Include inline image attachments (default `false`) |
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of comment objects.
**Endpoint:** `GET /api/v2/tickets/{ticket_id}/comments.json`

#### `zendesk_add_ticket_tags`
Add tags to a ticket (non-destructive, keeps existing tags).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Ticket ID |
| `tags` | list[str] | Yes | Tags to add |

**Returns:** Updated tag list.
**Endpoint:** `PUT /api/v2/tickets/{ticket_id}/tags.json`
**Note:** Uses PUT (safe add — merges with existing tags)

#### `zendesk_remove_ticket_tags`
Remove specific tags from a ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Ticket ID |
| `tags` | list[str] | Yes | Tags to remove |

**Returns:** Updated tag list.
**Endpoint:** `DELETE /api/v2/tickets/{ticket_id}/tags.json`

#### `zendesk_set_ticket_tags`
Replace all tags on a ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Ticket ID |
| `tags` | list[str] | Yes | Complete replacement tag list |

**Returns:** Updated tag list.
**Endpoint:** `POST /api/v2/tickets/{ticket_id}/tags.json`
**Note:** Uses POST (full replacement of all tags)

#### `zendesk_merge_tickets`
Merge a source ticket into a target ticket (irreversible).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `target_ticket_id` | int | Yes | Target ticket ID (survives) |
| `source_ticket_ids` | list[int] | Yes | Source ticket IDs to merge (max 5) |
| `target_comment` | str | No | Comment to add to target ticket |
| `source_comment` | str | No | Comment to add to source tickets |
| `target_comment_is_public` | bool | No | Whether target comment is public (default `true`) |
| `source_comment_is_public` | bool | No | Whether source comment is public (default `true`) |

**Returns:** Job status (async merge).
**Endpoint:** `POST /api/v2/tickets/{target_ticket_id}/merge.json`

#### `zendesk_bulk_update_tickets`
Update multiple tickets at once.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_ids` | list[int] | Yes | Ticket IDs to update (max 100) |
| `status` | str | No | New status for all |
| `priority` | str | No | New priority for all |
| `assignee_id` | int | No | New assignee for all |
| `group_id` | int | No | New group for all |
| `tags` | list[str] | No | Tags to set on all |
| `comment` | dict | No | Comment to add to all |

**Returns:** Job status (async bulk update).
**Endpoint:** `PUT /api/v2/tickets/update_many.json?ids={ids}`

#### `zendesk_list_ticket_collaborators`
List CCs/followers on a ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Ticket ID |

**Returns:** Array of user objects (collaborators).
**Endpoint:** `GET /api/v2/tickets/{ticket_id}/collaborators.json`

#### `zendesk_list_ticket_incidents`
List incidents linked to a problem ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Problem ticket ID |

**Returns:** Array of incident ticket objects.
**Endpoint:** `GET /api/v2/tickets/{ticket_id}/incidents.json`

#### `zendesk_apply_macro`
Apply a macro to a ticket (preview the changes without saving).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Ticket ID |
| `macro_id` | int | Yes | Macro ID |

**Returns:** Result showing what changes the macro would make.
**Endpoint:** `GET /api/v2/tickets/{ticket_id}/macros/{macro_id}/apply.json`

#### `zendesk_list_ticket_audits`
List the full audit trail (all change events) for a ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Ticket ID |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of audit objects (each containing events array).
**Endpoint:** `GET /api/v2/tickets/{ticket_id}/audits.json`

---

### Tier 2: User Management (10 tools)

#### `zendesk_create_user`
Create a new user (end-user, agent, or admin).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Full name |
| `email` | str | Yes | Email address |
| `role` | str | No | `end-user`, `agent`, `admin` (default `end-user`) |
| `organization_id` | int | No | Organization ID to associate |
| `phone` | str | No | Phone number |
| `tags` | list[str] | No | Tags |
| `user_fields` | dict | No | Custom user fields as `{field_key: value}` |
| `external_id` | str | No | External system ID |
| `verified` | bool | No | Whether email is verified (default `false`) |

**Returns:** Created user object.
**Endpoint:** `POST /api/v2/users.json`

#### `zendesk_get_user`
Get a user by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | int | Yes | User ID |

**Returns:** User object.
**Endpoint:** `GET /api/v2/users/{user_id}.json`

#### `zendesk_update_user`
Update user fields.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | int | Yes | User ID |
| `name` | str | No | New name |
| `email` | str | No | New email |
| `role` | str | No | New role |
| `organization_id` | int | No | New organization ID |
| `phone` | str | No | New phone |
| `tags` | list[str] | No | Replace tags |
| `user_fields` | dict | No | Custom user fields |
| `suspended` | bool | No | Suspend/unsuspend user |

**Returns:** Updated user object.
**Endpoint:** `PUT /api/v2/users/{user_id}.json`

#### `zendesk_delete_user`
Soft-delete a user (can be recovered).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | int | Yes | User ID |

**Returns:** Soft-deleted user object.
**Endpoint:** `DELETE /api/v2/users/{user_id}.json`

#### `zendesk_list_users`
List users with optional filtering.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `role` | str | No | Filter by role: `end-user`, `agent`, `admin` |
| `role_ids` | str | No | Filter by custom role IDs (comma-separated) |
| `permission_set` | str | No | Filter by permission set ID |
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of user objects with pagination.
**Endpoint:** `GET /api/v2/users.json`

#### `zendesk_search_users`
Search users by name or email.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | Yes | Search query (name or email fragment) |

**Returns:** Array of matching user objects.
**Endpoint:** `GET /api/v2/users/search.json?query={query}`

#### `zendesk_list_user_tickets`
List tickets where a user is the requester.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | int | Yes | User ID |
| `sort_by` | str | No | Sort field |
| `sort_order` | str | No | `asc` or `desc` |
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of ticket objects.
**Endpoint:** `GET /api/v2/users/{user_id}/tickets/requested.json`

#### `zendesk_merge_users`
Merge a user into another user (irreversible). Moves all tickets, comments, and activity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | int | Yes | Source user ID (will be deleted) |
| `target_user_id` | int | Yes | Target user ID (survives) |

**Returns:** Merged user object.
**Endpoint:** `PUT /api/v2/users/{user_id}/merge.json`

#### `zendesk_list_user_identities`
List identities (emails, phone numbers, X handles) for a user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | int | Yes | User ID |

**Returns:** Array of identity objects.
**Endpoint:** `GET /api/v2/users/{user_id}/identities.json`

#### `zendesk_create_or_update_user`
Create a user or update if email/external_id already exists (upsert).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Full name |
| `email` | str | Yes | Email address (used as match key) |
| `role` | str | No | Role |
| `organization_id` | int | No | Organization ID |
| `user_fields` | dict | No | Custom user fields |
| `external_id` | str | No | External system ID (alternative match key) |

**Returns:** Created or updated user object.
**Endpoint:** `POST /api/v2/users/create_or_update.json`

---

### Tier 3: Organization Management (6 tools)

#### `zendesk_create_organization`
Create an organization.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Organization name (must be unique) |
| `details` | str | No | Details/notes |
| `notes` | str | No | Additional notes |
| `domain_names` | list[str] | No | Associated domains (auto-assign users) |
| `tags` | list[str] | No | Tags |
| `organization_fields` | dict | No | Custom org fields as `{field_key: value}` |
| `external_id` | str | No | External system ID |
| `group_id` | int | No | Default group ID |

**Returns:** Created organization object.
**Endpoint:** `POST /api/v2/organizations.json`

#### `zendesk_get_organization`
Get an organization by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `organization_id` | int | Yes | Organization ID |

**Returns:** Organization object.
**Endpoint:** `GET /api/v2/organizations/{organization_id}.json`

#### `zendesk_update_organization`
Update organization fields.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `organization_id` | int | Yes | Organization ID |
| `name` | str | No | New name |
| `details` | str | No | New details |
| `notes` | str | No | New notes |
| `domain_names` | list[str] | No | Replace domain names |
| `tags` | list[str] | No | Replace tags |
| `organization_fields` | dict | No | Custom org fields |
| `group_id` | int | No | New default group ID |

**Returns:** Updated organization object.
**Endpoint:** `PUT /api/v2/organizations/{organization_id}.json`

#### `zendesk_delete_organization`
Delete an organization (hard delete, irreversible).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `organization_id` | int | Yes | Organization ID |

**Returns:** Confirmation (204 No Content).
**Endpoint:** `DELETE /api/v2/organizations/{organization_id}.json`

#### `zendesk_list_organizations`
List organizations.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of organization objects.
**Endpoint:** `GET /api/v2/organizations.json`

#### `zendesk_search_organizations`
Search organizations by name.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Organization name (exact or partial match) |

**Returns:** Array of matching organization objects.
**Endpoint:** `GET /api/v2/organizations/search.json?name={name}`

---

### Tier 4: Group Management (7 tools)

#### `zendesk_create_group`
Create a group.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Group name |
| `description` | str | No | Group description |

**Returns:** Created group object.
**Endpoint:** `POST /api/v2/groups.json`

#### `zendesk_get_group`
Get a group by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `group_id` | int | Yes | Group ID |

**Returns:** Group object.
**Endpoint:** `GET /api/v2/groups/{group_id}.json`

#### `zendesk_update_group`
Update a group.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `group_id` | int | Yes | Group ID |
| `name` | str | No | New name |
| `description` | str | No | New description |

**Returns:** Updated group object.
**Endpoint:** `PUT /api/v2/groups/{group_id}.json`

#### `zendesk_delete_group`
Delete a group.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `group_id` | int | Yes | Group ID |

**Returns:** Confirmation (204 No Content).
**Endpoint:** `DELETE /api/v2/groups/{group_id}.json`

#### `zendesk_list_groups`
List all groups.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |
| `exclude_deleted` | bool | No | Exclude deleted groups (default `true`) |

**Returns:** Array of group objects.
**Endpoint:** `GET /api/v2/groups.json`

#### `zendesk_list_group_memberships`
List memberships for a group (which agents belong to it).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `group_id` | int | Yes | Group ID |
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of group membership objects.
**Endpoint:** `GET /api/v2/groups/{group_id}/memberships.json`

#### `zendesk_create_group_membership`
Add an agent to a group.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `group_id` | int | Yes | Group ID |
| `user_id` | int | Yes | Agent user ID |

**Returns:** Created membership object.
**Endpoint:** `POST /api/v2/group_memberships.json`

---

### Tier 5: Ticket Fields & Forms (6 tools)

#### `zendesk_list_ticket_fields`
List all ticket fields (system and custom).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of ticket field objects (includes type, options, active status).
**Endpoint:** `GET /api/v2/ticket_fields.json`

#### `zendesk_get_ticket_field`
Get a single ticket field.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_field_id` | int | Yes | Ticket field ID |

**Returns:** Ticket field object.
**Endpoint:** `GET /api/v2/ticket_fields/{ticket_field_id}.json`

#### `zendesk_create_ticket_field`
Create a custom ticket field.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | str | Yes | Field type: `text`, `textarea`, `checkbox`, `date`, `integer`, `decimal`, `regexp`, `tagger` (dropdown), `multiselect`, `lookup` |
| `title` | str | Yes | Display title |
| `description` | str | No | Description |
| `required` | bool | No | Whether required (default `false`) |
| `active` | bool | No | Whether active (default `true`) |
| `visible_in_portal` | bool | No | Visible to end-users (default `false`) |
| `editable_in_portal` | bool | No | Editable by end-users (default `false`) |
| `tag` | str | No | Associated tag (for checkbox fields) |
| `custom_field_options` | list[dict] | No | Options for `tagger`/`multiselect` fields: `[{"name": "display", "value": "tag_value"}]` |

**Returns:** Created ticket field object.
**Endpoint:** `POST /api/v2/ticket_fields.json`

#### `zendesk_update_ticket_field`
Update a ticket field.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_field_id` | int | Yes | Ticket field ID |
| `title` | str | No | New title |
| `description` | str | No | New description |
| `required` | bool | No | New required status |
| `active` | bool | No | New active status |
| `custom_field_options` | list[dict] | No | Updated options |

**Returns:** Updated ticket field object.
**Endpoint:** `PUT /api/v2/ticket_fields/{ticket_field_id}.json`

#### `zendesk_delete_ticket_field`
Delete a custom ticket field.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_field_id` | int | Yes | Ticket field ID |

**Returns:** Empty (204).
**Endpoint:** `DELETE /api/v2/ticket_fields/{ticket_field_id}.json`

#### `zendesk_list_ticket_forms`
List all ticket forms.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `active` | bool | No | Filter by active status |

**Returns:** Array of ticket form objects.
**Endpoint:** `GET /api/v2/ticket_forms.json`

#### `zendesk_get_ticket_form`
Get a single ticket form.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_form_id` | int | Yes | Ticket form ID |

**Returns:** Ticket form object.
**Endpoint:** `GET /api/v2/ticket_forms/{ticket_form_id}.json`

---

### Tier 6: Views (4 tools)

#### `zendesk_list_views`
List all shared and personal views.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `active` | bool | No | Filter by active status |
| `group_id` | int | No | Filter by group ID |
| `sort_by` | str | No | Sort field: `alphabetical`, `created_at`, `updated_at` |
| `sort_order` | str | No | `asc` or `desc` |
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of view objects.
**Endpoint:** `GET /api/v2/views.json`

#### `zendesk_get_view`
Get a single view.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `view_id` | int | Yes | View ID |

**Returns:** View object with conditions and output columns.
**Endpoint:** `GET /api/v2/views/{view_id}.json`

#### `zendesk_execute_view`
Execute a view and return matching tickets.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `view_id` | int | Yes | View ID |
| `sort_by` | str | No | Sort column |
| `sort_order` | str | No | `asc` or `desc` |
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of ticket objects matching the view.
**Endpoint:** `GET /api/v2/views/{view_id}/execute.json`

#### `zendesk_get_view_count`
Get the ticket count for a view without fetching tickets.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `view_id` | int | Yes | View ID |

**Returns:** View count object with value and freshness.
**Endpoint:** `GET /api/v2/views/{view_id}/count.json`

---

### Tier 7: Search (2 tools)

#### `zendesk_search`
Unified search across tickets, users, and organizations using Zendesk Query Language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | Yes | ZQL query (e.g., `type:ticket status:open assignee:me`, `type:user email:*@example.com`) |
| `sort_by` | str | No | Sort field: `relevance`, `created_at`, `updated_at`, `priority`, `status`, `ticket_type` |
| `sort_order` | str | No | `asc` or `desc` |
| `per_page` | int | No | Results per page (max 100) |
| `page` | int | No | Page number (1-based, offset pagination) |

**Returns:** Array of mixed result objects (tickets, users, orgs) with `result_type` field. Limited to 1,000 total results.
**Endpoint:** `GET /api/v2/search.json`
**Note:** Search API uses offset pagination (page/per_page), not cursor pagination.

#### `zendesk_search_count`
Get the count of results for a search query without fetching results.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | Yes | ZQL query |

**Returns:** Count value.
**Endpoint:** `GET /api/v2/search/count.json`

---

### Tier 8: Satisfaction Ratings (3 tools)

#### `zendesk_list_satisfaction_ratings`
List satisfaction ratings (CSAT responses).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `score` | str | No | Filter by score: `good`, `bad`, `offered`, `unoffered` |
| `start_time` | int | No | Filter by creation time (Unix epoch) |
| `end_time` | int | No | Filter by creation time (Unix epoch) |
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of satisfaction rating objects.
**Endpoint:** `GET /api/v2/satisfaction_ratings.json`

#### `zendesk_get_satisfaction_rating`
Get a single satisfaction rating.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `rating_id` | int | Yes | Satisfaction rating ID |

**Returns:** Satisfaction rating object.
**Endpoint:** `GET /api/v2/satisfaction_ratings/{rating_id}.json`

#### `zendesk_create_satisfaction_rating`
Create a satisfaction rating on a solved ticket (on behalf of a requester).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | int | Yes | Solved ticket ID |
| `score` | str | Yes | `good` or `bad` |
| `comment` | str | No | Requester feedback text |

**Returns:** Created satisfaction rating object.
**Endpoint:** `POST /api/v2/tickets/{ticket_id}/satisfaction_rating.json`

---

### Tier 9: Attachments (2 tools)

#### `zendesk_upload_attachment`
Upload a file to get an upload token (used when adding comments).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_path` | str | Yes | Local file path |
| `filename` | str | No | Override filename (defaults to file basename) |
| `token` | str | No | Existing upload token to append to (for multi-file uploads) |

**Returns:** Upload object with `token` to reference in comments.
**Endpoint:** `POST /api/v2/uploads.json?filename={filename}`
**Note:** Uses `multipart/form-data` with binary body, not JSON.

#### `zendesk_delete_upload`
Delete an uploaded file by token (before it is associated with a comment).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `token` | str | Yes | Upload token |

**Returns:** Confirmation (204 No Content).
**Endpoint:** `DELETE /api/v2/uploads/{token}.json`

---

### Tier 10: Suspended Tickets (4 tools)

#### `zendesk_list_suspended_tickets`
List suspended (spam-filtered) tickets.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sort_by` | str | No | Sort field: `author`, `cause`, `created_at`, `subject` |
| `sort_order` | str | No | `asc` or `desc` |
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |

**Returns:** Array of suspended ticket objects.
**Endpoint:** `GET /api/v2/suspended_tickets.json`

#### `zendesk_get_suspended_ticket`
Get a single suspended ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `suspended_ticket_id` | int | Yes | Suspended ticket ID |

**Returns:** Suspended ticket object.
**Endpoint:** `GET /api/v2/suspended_tickets/{suspended_ticket_id}.json`

#### `zendesk_recover_suspended_ticket`
Recover a suspended ticket (move it to the active ticket queue).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `suspended_ticket_id` | int | Yes | Suspended ticket ID |

**Returns:** Recovered ticket object.
**Endpoint:** `PUT /api/v2/suspended_tickets/{suspended_ticket_id}/recover.json`

#### `zendesk_delete_suspended_ticket`
Permanently delete a suspended ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `suspended_ticket_id` | int | Yes | Suspended ticket ID |

**Returns:** Confirmation (204 No Content).
**Endpoint:** `DELETE /api/v2/suspended_tickets/{suspended_ticket_id}.json`

---

### Tier 11: Macros (4 tools)

#### `zendesk_list_macros`
List macros available to the authenticated agent.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `active` | bool | No | Filter by active status |
| `category` | int | No | Filter by category ID |
| `group_id` | int | No | Filter by group ID |
| `sort_by` | str | No | Sort field: `alphabetical`, `created_at`, `updated_at`, `usage_1h`, `usage_24h`, `usage_7d` |
| `sort_order` | str | No | `asc` or `desc` |
| `page_size` | int | No | Results per page (max 100) |
| `page_after` | str | No | Cursor for next page |
| `include` | str | No | Sideload: `usage_7d`, `usage_24h`, `usage_1h` |

**Returns:** Array of macro objects.
**Endpoint:** `GET /api/v2/macros.json`

#### `zendesk_get_macro`
Get a single macro.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `macro_id` | int | Yes | Macro ID |

**Returns:** Macro object with actions definition.
**Endpoint:** `GET /api/v2/macros/{macro_id}.json`

#### `zendesk_create_macro`
Create a macro.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | str | Yes | Macro title |
| `actions` | list[dict] | Yes | Actions as `[{"field": "status", "value": "solved"}, {"field": "comment_value", "value": "Thanks!"}]` |
| `description` | str | No | Macro description |
| `active` | bool | No | Active status (default `true`) |
| `restriction` | dict | No | Restriction: `{"type": "Group", "id": 123}` |

**Returns:** Created macro object.
**Endpoint:** `POST /api/v2/macros.json`

#### `zendesk_update_macro`
Update a macro.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `macro_id` | int | Yes | Macro ID |
| `title` | str | No | New title |
| `actions` | list[dict] | No | New actions |
| `description` | str | No | New description |
| `active` | bool | No | New active status |

**Returns:** Updated macro object.
**Endpoint:** `PUT /api/v2/macros/{macro_id}.json`

#### `zendesk_delete_macro`
Delete a macro.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `macro_id` | int | Yes | Macro ID |

**Returns:** Empty (204).
**Endpoint:** `DELETE /api/v2/macros/{macro_id}.json`

---

## Tool Count Summary

| Tier | Category | Tool Count |
|------|----------|------------|
| 1 | Ticket Management | 16 |
| 2 | User Management | 10 |
| 3 | Organization Management | 6 |
| 4 | Group Management | 7 |
| 5 | Ticket Fields & Forms | 7 |
| 6 | Views | 4 |
| 7 | Search | 2 |
| 8 | Satisfaction Ratings | 3 |
| 9 | Attachments | 2 |
| 10 | Suspended Tickets | 4 |
| 11 | Macros | 5 |
| **Total** | | **66** |

---

## Implementation Notes

### Architecture (follows Jira pattern)
- **File:** `src/mcp_toolbox/tools/zendesk_tool.py`
- **HTTP Client:** Singleton `httpx.AsyncClient` with Basic auth header and base URL pre-configured
- **Base URL construction:** `https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2`
- **Auth header:** `Basic base64("{ZENDESK_EMAIL}/token:{ZENDESK_API_TOKEN}")`
- **Helper function:** `_req(method, path, **kwargs)` wrapping all requests, handling 429 rate limits and error extraction
- **Response unwrapping:** Helper to extract the data key from wrapper objects (e.g., `response["ticket"]` from `{"ticket": {...}}`)

### Config additions (`config.py`)
```python
ZENDESK_SUBDOMAIN: str | None = os.getenv("ZENDESK_SUBDOMAIN")
ZENDESK_EMAIL: str | None = os.getenv("ZENDESK_EMAIL")
ZENDESK_API_TOKEN: str | None = os.getenv("ZENDESK_API_TOKEN")
```

### Registration (`tools/__init__.py`)
Add `from .zendesk_tool import register_tools as register_zendesk` and call in `register_all_tools()`.

### pyright
Include this file in pyright checking (no untyped SDK dependency).

### Error handling patterns
- 429 responses: extract `Retry-After` header and raise `ToolError`
- 422 responses: Zendesk returns `{"error": "RecordInvalid", "description": "...", "details": {...}}`
- 404 responses: Zendesk returns `{"error": "RecordNotFound"}`
- Wrap all errors into structured `ToolError` messages

### Pagination helper
Consider a `_paginate()` helper or consistent `page_size`/`page_after` params across all list tools to standardize cursor-based pagination. Return `meta.has_more` and `meta.after_cursor` in tool responses for client-driven pagination.

### Attachment upload
Uses binary `application/octet-stream` body with `?filename=` query param, not the standard JSON wrapper pattern. Needs special handling in `_req` or a dedicated upload method.

---

## Dependencies
- No new pip dependencies required (httpx already available)
- No SDK needed — pure REST API via httpx

## Testing Strategy
- Unit tests mocking httpx responses for each tool
- Test wrapper key extraction (single vs. list responses)
- Test auth header construction (`email/token:key` format)
- Test pagination cursor passing
- Test error handling (429, 404, 422)
- Test attachment upload (multipart binary)
