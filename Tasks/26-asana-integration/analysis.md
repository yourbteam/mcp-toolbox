# Task 26: Asana Integration - Analysis & Requirements

## Objective
Add Asana as a tool integration in mcp-toolbox, exposing the Asana REST API (workspaces, teams, projects, sections, tasks, subtasks, stories/comments, tags, attachments, custom fields, users, webhooks, status updates) as MCP tools for LLM clients.

---

## API Technical Details

### Asana API (v1.0) — REST
- **Base URL:** `https://app.asana.com/api/1.0`
- **Auth:** Personal Access Token (PAT) via `Authorization: Bearer <token>` header. (OAuth2 is also supported by Asana but a PAT is the simplest model and is consistent with our Notion/HubSpot/GitHub pattern.)
- **Format:** JSON request/response (`Content-Type: application/json`)
- **Request envelope:** All request bodies are wrapped in a top-level `data` key: `{"data": {...}}`.
- **Response envelope:** All successful responses are wrapped in a top-level `data` key: `{"data": {...}}` (single object) or `{"data": [...]}` (collection). Most collection endpoints also include a `next_page` object for offset pagination — but **the search endpoint (`/tasks/search`) does NOT** (it has no traditional pagination; you page by sorting on a field like `created_at` and re-querying). So "collections return `next_page`" is true for every list endpoint *except search*.

### Rate Limits

| Plan / Scope | Limit |
|------|-------|
| Free | 150 requests per minute |
| Paid | 1500 requests per minute |
| Search endpoint (`/tasks/search`) | **60 requests per minute** (its own per-minute cap) |
| Cost-based limiting | A **separate** mechanism that throttles expensive queries (deep graph traversals, large `opt_fields` expansions) — no published numeric quota; distinct from the 60/min search cap |
| Concurrent — GET | 50 concurrent requests max |
| Concurrent — writes (POST/PUT/PATCH/DELETE) | **15** concurrent requests max |

- HTTP **429** on exceed with a `Retry-After` header (seconds).
- Recommendation: surface `Retry-After` in the error message; callers/back-off handled upstream (consistent with Notion tool behavior — we raise `ToolError`, we do not auto-retry).
- **Note:** The search endpoint is governed by both its 60/min cap AND cost-based limiting; treat these as two independent budgets.

### No SDK — Direct HTTP
Asana publishes `asana` (a Python SDK), but it is a heavy, partially-generated client. **Recommendation:** use `httpx` (already a dependency) for direct async HTTP — consistent with Notion/HubSpot/ClickUp/GitHub. Simpler, fully async, full control over the `data` envelope.

### Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `ASANA_ACCESS_TOKEN` | Yes | Personal Access Token (created in Asana → My Settings → Apps → Developer apps → Personal access tokens) |
| `ASANA_DEFAULT_WORKSPACE_ID` | No | Default workspace (organization) GID used when a tool needs a workspace and none is supplied |

### Key Quirks

- **`data` envelope everywhere** — Every POST/PUT body must be `{"data": {...}}`; every response unwraps from `{"data": ...}`. A `_req` helper must wrap outgoing bodies and unwrap incoming responses centrally.
- **GIDs, not UUIDs** — Every Asana resource is identified by a `gid` (a numeric string, e.g. `"1201234567890123"`). All IDs are strings.
- **`opt_fields` field selection** — By default Asana returns a "compact" record (just `gid`, `name`, `resource_type`). To get more fields you must pass `opt_fields` as a comma-separated query param (e.g. `opt_fields=name,notes,completed,due_on,assignee.name`). Tools should accept an optional `opt_fields` string and pass it through; sensible defaults can be supplied per tool.
- **Offset-based pagination** — Collection endpoints accept `limit` (1–100) and `offset`. The response includes `next_page: {offset, path, uri}` when more results exist (or `null`). Pass the returned `offset` back to continue. **Note:** `offset` is an opaque token returned by Asana — you cannot construct it yourself; only the first page omits it.
- **Workspace vs Organization** — An "organization" is a special workspace tied to an email domain. Both use the same `/workspaces` endpoints. `is_organization` distinguishes them. Teams only exist within organizations.
- **Tasks require a container** — On creation a task must belong to a `workspace` (and may be placed in `projects`); if `projects` is provided, `workspace` may be omitted/inferred. A task can live in multiple projects simultaneously.
- **Sections belong to projects** — Adding a task to a section uses `POST /sections/{section_gid}/addTask`. A task's membership in a project+section is a "membership".
- **Stories = comments + activity** — "Stories" are the activity-feed entries on a task. User-authored comment stories have `type: "comment"`; system stories (`type: "system"`) are read-only audit entries. Only comment stories can be created/edited/deleted.
- **Custom fields are typed** — `enum`, `multi_enum`, `text`, `number`, `date`, `people`. Setting a custom field on a task uses the `custom_fields` map keyed by the field GID: `{"custom_fields": {"<field_gid>": <value>}}` where value is an enum option GID (enum), a list of option GIDs (multi_enum), a string/number, etc.
- **Booleans for completion** — Tasks use `completed: true/false`, not a status enum. `completed_at` is read-only.
- **Dates** — `due_on`/`start_on` are date-only (`YYYY-MM-DD`); `due_at`/`start_at` are full ISO 8601 timestamps. Setting `due_at` clears `due_on` and vice versa.
- **Attachments use multipart** — Uploading an attachment is `multipart/form-data` to `POST /attachments` (operation `createAttachmentForObject`; the legacy `/tasks/{gid}/attachments` still works), NOT JSON. This is the one endpoint that does not use the `data` JSON envelope for the request. The `parent` form field accepts a **task, project, or project_brief** GID — our `asana_upload_attachment` tool exposes the task case (the common one) but the `parent` field is the same mechanism for all three.
- **Add/remove relationships use sub-actions** — Many mutations are POST sub-resources: `addProject`, `removeProject`, `addFollowers`, `removeFollowers`, `addDependencies`, `removeDependencies`, `addTag`, `removeTag`, `setParent`, `addTask` (section). Bodies are still `{"data": {...}}`.
- **Search is workspace-scoped & cost-limited** — `GET /workspaces/{workspace_gid}/tasks/search` supports rich typeahead filters but is rate-limited separately and only available on paid plans. The simpler `GET /workspaces/{workspace_gid}/typeahead` is available more broadly.
- **Deletion is real** — `DELETE /tasks/{gid}` permanently deletes (moves to trash for ~30 days but not retrievable via API). Unlike Notion, there is no "archived" flag for tasks (projects do have `archived`).

---

## Asana Object Model

```
Workspace / Organization
  |
  +-- Teams (organizations only)
  |     |
  |     +-- Projects
  |
  +-- Projects (board or list layout)
  |     |
  |     +-- Sections (columns / groupings)
  |     |     |
  |     |     +-- Tasks (via memberships)
  |     |
  |     +-- Custom Field Settings
  |     +-- Status Updates
  |
  +-- Tasks
  |     |
  |     +-- Subtasks (parent/child)
  |     +-- Stories (comments + system activity)
  |     +-- Attachments
  |     +-- Dependencies / Dependents
  |     +-- Followers
  |     +-- Tags
  |     +-- Custom field values
  |
  +-- Tags
  +-- Users (members)
  +-- Custom Fields (workspace-level definitions)
  +-- Webhooks
```

### Core Object Types

| Object | API Path | Description |
|--------|----------|-------------|
| Workspaces | `/workspaces` | Top-level container (org or workspace) |
| Teams | `/teams`, `/workspaces/{gid}/teams` | Sub-groups within an organization (canonical list path is `/workspaces/{gid}/teams`; `/organizations/{gid}/teams` is a legacy alias) |
| Users | `/users`, `/workspaces/{gid}/users` | People in a workspace |
| Projects | `/projects` | Collections of tasks |
| Sections | `/sections`, `/projects/{gid}/sections` | Columns/groupings within a project |
| Tasks | `/tasks` | The core unit of work |
| Subtasks | `/tasks/{gid}/subtasks` | Child tasks |
| Stories | `/tasks/{gid}/stories` | Comments and activity entries |
| Tags | `/tags` | Labels applied to tasks |
| Attachments | `/attachments` | Files attached to tasks |
| Custom Fields | `/custom_fields`, `/workspaces/{gid}/custom_fields` | Typed metadata definitions |
| Status Updates | `/status_updates` | Project progress posts |
| Webhooks | `/webhooks` | Event subscriptions |

---

## Tool Specifications

> All tools are prefixed `asana_`. All accept an optional `opt_fields: str | None` (comma-separated) where the underlying endpoint supports it, to let callers expand the compact record. GIDs are strings throughout.

### Tier 1: Workspaces, Users & Jobs (6 tools)

#### `asana_list_workspaces`
List all workspaces/organizations visible to the token.
- **Params:** `limit` (int, opt), `offset` (str, opt), `opt_fields` (str, opt)
- **Endpoint:** `GET /workspaces`

#### `asana_get_workspace`
Get a single workspace by GID.
- **Params:** `workspace_gid` (str, req — defaults to `ASANA_DEFAULT_WORKSPACE_ID`), `opt_fields` (str, opt)
- **Endpoint:** `GET /workspaces/{workspace_gid}`

#### `asana_get_me`
Get the user record for the token owner.
- **Params:** `opt_fields` (str, opt)
- **Endpoint:** `GET /users/me`

#### `asana_list_users`
List users in a workspace.
- **Params:** `workspace_gid` (str, req — default), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /workspaces/{workspace_gid}/users`

#### `asana_get_user`
Get a single user.
- **Params:** `user_gid` (str, req — `"me"` accepted), `opt_fields`
- **Endpoint:** `GET /users/{user_gid}`

#### `asana_get_job`
Poll the status of an asynchronous job (used by `duplicate_task`/`duplicate_project`).
- **Params:** `job_gid` (str, req), `opt_fields`
- **Endpoint:** `GET /jobs/{job_gid}`
- **Returns:** Job object with `status` (`not_started`/`in_progress`/`succeeded`/`failed`), `resource_subtype`, and the result reference (`new_task`/`new_project`/`new_project_template`) when complete.

---

### Tier 2: Teams (4 tools)

#### `asana_list_teams`
List teams in a workspace/organization (teams the token's user can see).
- **Params:** `workspace_gid` (str, req — default workspace), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /workspaces/{workspace_gid}/teams` (canonical; `/organizations/{gid}/teams` is a legacy alias for the same data)

#### `asana_get_team`
Get a single team.
- **Params:** `team_gid` (str, req), `opt_fields`
- **Endpoint:** `GET /teams/{team_gid}`

#### `asana_add_user_to_team`
Add a user to a team.
- **Params:** `team_gid` (str, req), `user` (str, req — user GID or email or `"me"`)
- **Endpoint:** `POST /teams/{team_gid}/addUser` — body `{"data": {"user": "..."}}`

#### `asana_remove_user_from_team`
Remove a user from a team.
- **Params:** `team_gid` (str, req), `user` (str, req)
- **Endpoint:** `POST /teams/{team_gid}/removeUser` — body `{"data": {"user": "..."}}`

---

### Tier 3: Projects (7 tools)

#### `asana_create_project`
Create a project in a workspace or team.
- **Params:** `name` (str, req), `workspace_gid` (str, opt — default), `team_gid` (str, opt — required if workspace is an org), `notes` (str, opt), `color` (str, opt), `public` (bool, opt), `default_view` (str, opt: `list`/`board`/`calendar`/`timeline`), `due_on` (str, opt), `start_on` (str, opt), `opt_fields`
- **Endpoint:** `POST /projects` — body `{"data": {"name":..., "workspace":..., "team":...}}`

#### `asana_get_project`
- **Params:** `project_gid` (str, req), `opt_fields`
- **Endpoint:** `GET /projects/{project_gid}`

#### `asana_update_project`
- **Params:** `project_gid` (str, req), plus optional `name`, `notes`, `color`, `archived` (bool), `public` (bool), `default_view`, `due_on`, `start_on`, `opt_fields`. At least one mutable field required.
- **Endpoint:** `PUT /projects/{project_gid}`

#### `asana_delete_project`
- **Params:** `project_gid` (str, req)
- **Endpoint:** `DELETE /projects/{project_gid}`

#### `asana_list_projects`
List projects in a workspace or team, optionally filtered by archived.
- **Params:** `workspace_gid` (str, opt — default), `team_gid` (str, opt), `archived` (bool, opt), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /projects` with query `workspace`/`team`/`archived`

#### `asana_duplicate_project`
- **Params:** `project_gid` (str, req), `name` (str, req — name of the new project), `team_gid` (str, opt), `include` (str, opt — comma list e.g. `members,task_notes`), `schedule_dates` (dict, opt)
- **Endpoint:** `POST /projects/{project_gid}/duplicate`
- **Async:** Returns a **Job** object (`resource_type: "job"`, `status: in_progress`), NOT the new project. Poll completion with `asana_get_job` using `job.gid`; the duplicated project GID appears in `job.new_project` once `status: succeeded`.

#### `asana_get_project_task_counts`
Get task counts for a project (requires explicit `opt_fields`).
- **Params:** `project_gid` (str, req), `opt_fields` (str, opt — defaults to all count fields)
- **Endpoint:** `GET /projects/{project_gid}/task_counts`

---

### Tier 4: Sections (6 tools)

#### `asana_create_section`
- **Params:** `project_gid` (str, req), `name` (str, req), `insert_before` (str, opt — section GID), `insert_after` (str, opt), `opt_fields`
- **Endpoint:** `POST /projects/{project_gid}/sections`

#### `asana_get_section`
- **Params:** `section_gid` (str, req), `opt_fields`
- **Endpoint:** `GET /sections/{section_gid}`

#### `asana_update_section`
- **Params:** `section_gid` (str, req), `name` (str, opt), `opt_fields`
- **Endpoint:** `PUT /sections/{section_gid}`

#### `asana_delete_section`
- **Params:** `section_gid` (str, req)
- **Endpoint:** `DELETE /sections/{section_gid}`

#### `asana_list_sections`
- **Params:** `project_gid` (str, req), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /projects/{project_gid}/sections`

#### `asana_add_task_to_section`
Move a task into a section (and optionally position it).
- **Params:** `section_gid` (str, req), `task_gid` (str, req), `insert_before` (str, opt — task GID), `insert_after` (str, opt)
- **Endpoint:** `POST /sections/{section_gid}/addTask` — body `{"data": {"task": "..."}}`

---

### Tier 5: Tasks — Core (13 tools)

#### `asana_create_task`
- **Params:** `name` (str, req), `workspace_gid` (str, opt — default; required unless `projects` given), `projects` (list[str], opt), `parent` (str, opt — make this a subtask), `assignee` (str, opt — GID/email/`me`), `notes` (str, opt), `html_notes` (str, opt), `due_on` (str, opt), `due_at` (str, opt), `start_on` (str, opt), `completed` (bool, opt), `followers` (list[str], opt), `tags` (list[str], opt), `custom_fields` (dict, opt), `opt_fields`
- **Endpoint:** `POST /tasks`

#### `asana_get_task`
- **Params:** `task_gid` (str, req), `opt_fields`
- **Endpoint:** `GET /tasks/{task_gid}`

#### `asana_update_task`
- **Params:** `task_gid` (str, req), plus optional `name`, `notes`, `html_notes`, `assignee`, `completed` (bool), `due_on`, `due_at`, `start_on`, `custom_fields` (dict), `opt_fields`. At least one mutable field required.
- **Endpoint:** `PUT /tasks/{task_gid}`

#### `asana_delete_task`
- **Params:** `task_gid` (str, req)
- **Endpoint:** `DELETE /tasks/{task_gid}`

#### `asana_list_tasks`
List tasks scoped by project, section, tag, or assignee+workspace.
- **Params:** `project_gid` (str, opt), `section_gid` (str, opt), `tag_gid` (str, opt), `assignee` (str, opt — requires `workspace_gid`), `workspace_gid` (str, opt — default), `completed_since` (str, opt), `modified_since` (str, opt), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /tasks` (with `project`/`section`/`tag`/`assignee`+`workspace` query)
- **Container rule (per Asana `getTasks`):** You must supply **exactly one** scoping selector — `project`, OR `section`, OR `tag`, OR `assignee` (and `assignee` additionally **requires** `workspace`; `assignee` alone is rejected). These selectors are **mutually exclusive**: combining them (e.g. `project` + `assignee`) returns a **400** from Asana. The helper therefore validates "exactly one of project/section/tag/assignee is set (raise if 0 or >1), and if `assignee` is set then `workspace` resolves." `completed_since`/`modified_since`/pagination are modifiers that combine freely with the chosen scope. (Note: a prior draft incorrectly described these as combinable; corrected here against the live API.)
- **Out of scope:** `user_task_list` (a user's "My Tasks") is fetched via the separate `GET /user_task_lists/{gid}/tasks` endpoint, not a `/tasks` query param; not exposed by this tool (acknowledged scope boundary).

#### `asana_search_tasks`
Advanced typeahead search within a workspace (paid plans).
- **Params:** `workspace_gid` (str, req — default), `text` (str, opt), `completed` (bool, opt), `assignee_any` (str, opt — comma GIDs), `projects_any` (str, opt), `tags_any` (str, opt), `due_on` (str, opt), `due_before` (str, opt), `due_after` (str, opt), `sort_by` (str, opt), `sort_ascending` (bool, opt), `limit`, `opt_fields`
- **Endpoint:** `GET /workspaces/{workspace_gid}/tasks/search`
- **Note:** Search uses query params (not offset pagination); document the separate rate-limit budget.

#### `asana_duplicate_task`
- **Params:** `task_gid` (str, req), `name` (str, req — name of the new task), `include` (str, opt — comma list)
- **Endpoint:** `POST /tasks/{task_gid}/duplicate`
- **Async:** Returns a **Job** object (not the new task). Poll with `asana_get_job` using `job.gid`; the duplicated task GID appears in `job.new_task` once `status: succeeded`.

#### `asana_add_task_to_project`
- **Params:** `task_gid` (str, req), `project_gid` (str, req), `section` (str, opt), `insert_before` (str, opt), `insert_after` (str, opt)
- **Endpoint:** `POST /tasks/{task_gid}/addProject`

#### `asana_remove_task_from_project`
- **Params:** `task_gid` (str, req), `project_gid` (str, req)
- **Endpoint:** `POST /tasks/{task_gid}/removeProject`

#### `asana_add_task_followers`
- **Params:** `task_gid` (str, req), `followers` (list[str], req — GIDs/emails)
- **Endpoint:** `POST /tasks/{task_gid}/addFollowers`

#### `asana_remove_task_followers`
- **Params:** `task_gid` (str, req), `followers` (list[str], req)
- **Endpoint:** `POST /tasks/{task_gid}/removeFollowers`

#### `asana_add_task_dependencies`
- **Params:** `task_gid` (str, req), `dependencies` (list[str], req — task GIDs this task depends on)
- **Endpoint:** `POST /tasks/{task_gid}/addDependencies`

#### `asana_add_task_dependents`
- **Params:** `task_gid` (str, req), `dependents` (list[str], req — task GIDs that depend on this task)
- **Endpoint:** `POST /tasks/{task_gid}/addDependents`

---

### Tier 6: Subtasks (3 tools)

#### `asana_create_subtask`
- **Params:** `parent_task_gid` (str, req), `name` (str, req), `assignee` (str, opt), `notes` (str, opt), `due_on` (str, opt), `completed` (bool, opt), `opt_fields`
- **Endpoint:** `POST /tasks/{parent_task_gid}/subtasks`

#### `asana_list_subtasks`
- **Params:** `task_gid` (str, req), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /tasks/{task_gid}/subtasks`

#### `asana_set_task_parent`
Re-parent a task (or detach with `parent=None`).
- **Params:** `task_gid` (str, req), `parent` (str | None, req), `insert_before` (str, opt), `insert_after` (str, opt)
- **Endpoint:** `POST /tasks/{task_gid}/setParent` — body `{"data": {"parent": "..."}}`

---

### Tier 7: Stories / Comments (5 tools)

#### `asana_create_story`
Add a comment to a task.
- **Params:** `task_gid` (str, req), `text` (str, opt), `html_text` (str, opt), `opt_fields`. One of `text`/`html_text` required.
- **Endpoint:** `POST /tasks/{task_gid}/stories`

#### `asana_get_story`
- **Params:** `story_gid` (str, req), `opt_fields`
- **Endpoint:** `GET /stories/{story_gid}`

#### `asana_list_stories`
- **Params:** `task_gid` (str, req), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /tasks/{task_gid}/stories`

#### `asana_update_story`
Edit a comment story (only `text`/`html_text` editable, only on comment stories you authored).
- **Params:** `story_gid` (str, req), `text` (str, opt), `html_text` (str, opt), `opt_fields`
- **Endpoint:** `PUT /stories/{story_gid}`

#### `asana_delete_story`
- **Params:** `story_gid` (str, req)
- **Endpoint:** `DELETE /stories/{story_gid}`

---

### Tier 8: Tags (7 tools)

#### `asana_create_tag`
- **Params:** `name` (str, req), `workspace_gid` (str, opt — default), `color` (str, opt), `opt_fields`
- **Endpoint:** `POST /tags`

#### `asana_get_tag`
- **Params:** `tag_gid` (str, req), `opt_fields`
- **Endpoint:** `GET /tags/{tag_gid}`

#### `asana_update_tag`
- **Params:** `tag_gid` (str, req), `name` (str, opt), `color` (str, opt), `opt_fields`
- **Endpoint:** `PUT /tags/{tag_gid}`

#### `asana_delete_tag`
- **Params:** `tag_gid` (str, req)
- **Endpoint:** `DELETE /tags/{tag_gid}`

#### `asana_list_tags`
- **Params:** `workspace_gid` (str, opt — default), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /tags` (query `workspace`)

#### `asana_add_tag_to_task`
- **Params:** `task_gid` (str, req), `tag_gid` (str, req)
- **Endpoint:** `POST /tasks/{task_gid}/addTag` — body `{"data": {"tag": "..."}}`

#### `asana_remove_tag_from_task`
- **Params:** `task_gid` (str, req), `tag_gid` (str, req)
- **Endpoint:** `POST /tasks/{task_gid}/removeTag` — body `{"data": {"tag": "..."}}`

---

### Tier 9: Attachments (4 tools)

#### `asana_list_attachments`
- **Params:** `task_gid` (str, req), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /attachments` (query `parent={task_gid}`)

#### `asana_get_attachment`
- **Params:** `attachment_gid` (str, req), `opt_fields`
- **Endpoint:** `GET /attachments/{attachment_gid}`

#### `asana_upload_attachment`
Upload a local file to a task (multipart — the one non-JSON-envelope endpoint).
- **Params:** `task_gid` (str, req), `file_path` (str, req), `file_name` (str, opt — overrides basename)
- **Endpoint:** `POST /attachments` — `multipart/form-data` with `parent` field + `file`

#### `asana_delete_attachment`
- **Params:** `attachment_gid` (str, req)
- **Endpoint:** `DELETE /attachments/{attachment_gid}`

---

### Tier 10: Custom Fields (4 tools)

#### `asana_list_custom_fields`
List custom field definitions in a workspace.
- **Params:** `workspace_gid` (str, opt — default), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /workspaces/{workspace_gid}/custom_fields`

#### `asana_get_custom_field`
- **Params:** `custom_field_gid` (str, req), `opt_fields`
- **Endpoint:** `GET /custom_fields/{custom_field_gid}`

#### `asana_create_custom_field`
- **Params:** `workspace_gid` (str, opt — default), `name` (str, req), `field_type` (str, req — `text`/`number`/`enum`/`multi_enum`/`date`/`people`), `enum_options` (list[str], opt — names for enum/multi_enum), `precision` (int, opt — number), `opt_fields`
- **Endpoint:** `POST /custom_fields` — body includes `workspace`, `name`, **`resource_subtype`** (the field type; the legacy `type` key is deprecated and `resource_subtype` takes precedence if both are sent — emit `resource_subtype`), optional `enum_options:[{name}]`

#### `asana_set_task_custom_field`
Convenience wrapper to set one custom field value on a task.
- **Params:** `task_gid` (str, req), `custom_field_gid` (str, req), `value` (str | int | float | list[str], req — option GID(s) for enum/multi_enum, raw value otherwise), `opt_fields`
- **Endpoint:** `PUT /tasks/{task_gid}` — body `{"data": {"custom_fields": {"<gid>": <value>}}}`

---

### Tier 11: Project Status Updates (4 tools)

#### `asana_create_status_update`
- **Params:** `parent_gid` (str, req — project/portfolio/goal GID), `text` (str, opt), `html_text` (str, opt), `status_type` (str, req — `on_track`/`at_risk`/`off_track`/`on_hold`/`complete`), `title` (str, opt), `opt_fields`
- **Endpoint:** `POST /status_updates` — body `{"data": {"parent":..., "status_type":..., "text":...}}`

#### `asana_get_status_update`
- **Params:** `status_update_gid` (str, req), `opt_fields`
- **Endpoint:** `GET /status_updates/{status_update_gid}`

#### `asana_list_status_updates`
- **Params:** `parent_gid` (str, req), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /status_updates` (query `parent`)

#### `asana_delete_status_update`
- **Params:** `status_update_gid` (str, req)
- **Endpoint:** `DELETE /status_updates/{status_update_gid}`

---

### Tier 12: Webhooks (4 tools)

#### `asana_create_webhook`
- **Params:** `resource_gid` (str, req — task/project/etc.), `target_url` (str, req — HTTPS endpoint), `filters` (list[dict], opt), `opt_fields`
- **Endpoint:** `POST /webhooks` — body `{"data": {"resource":..., "target":..., "filters":[...]}}`
- **Note:** Asana sends a handshake `X-Hook-Secret` to `target_url`; documented as a caller responsibility.

#### `asana_get_webhook`
- **Params:** `webhook_gid` (str, req), `opt_fields`
- **Endpoint:** `GET /webhooks/{webhook_gid}`

#### `asana_list_webhooks`
- **Params:** `workspace_gid` (str, opt in signature — default), `resource_gid` (str, opt — filter), `limit`, `offset`, `opt_fields`
- **Endpoint:** `GET /webhooks` (query `workspace` **required**, optional `resource`)
- **Note:** `workspace` is a **mandatory** query param for this endpoint. The param is only optional in our signature because it falls back to `ASANA_DEFAULT_WORKSPACE_ID`; if neither is supplied the helper must raise `ToolError` (via `_workspace()`), not call the API without it.

#### `asana_delete_webhook`
- **Params:** `webhook_gid` (str, req)
- **Endpoint:** `DELETE /webhooks/{webhook_gid}`

---

## Tool Count Summary

| Tier | Category | Tools |
|------|----------|-------|
| 1 | Workspaces, Users & Jobs | 6 |
| 2 | Teams | 4 |
| 3 | Projects | 7 |
| 4 | Sections | 6 |
| 5 | Tasks — Core | 13 |
| 6 | Subtasks | 3 |
| 7 | Stories / Comments | 5 |
| 8 | Tags | 7 |
| 9 | Attachments | 4 |
| 10 | Custom Fields | 4 |
| 11 | Status Updates | 4 |
| 12 | Webhooks | 4 |
| **Total** | | **67** |

---

## Implementation Architecture

### Singleton HTTP Client Pattern (consistent with Notion/HubSpot)

```python
_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    global _client
    if not ASANA_ACCESS_TOKEN:
        raise ToolError("ASANA_ACCESS_TOKEN not configured.")
    if _client is None:
        _client = httpx.AsyncClient(
            base_url="https://app.asana.com/api/1.0",
            headers={
                "Authorization": f"Bearer {ASANA_ACCESS_TOKEN}",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
    return _client
```

### Helper Functions Needed

1. **`_success(status_code: int, **kw) -> str`** — Uniform success serializer, identical to the repo convention: `json.dumps({"status": "success", "status_code": status_code, **kw})`. **Every** tool returns through this (matches `notion_tool._success`, `hubspot_tool._success`). Tools do NOT return raw API JSON.
2. **`_req(method, path, *, data=None, params=None, files=None) -> tuple[dict|list, dict|None]`** — Core request wrapper. Wraps non-multipart bodies as `{"data": data}`, unwraps responses from `{"data": ...}`, returns a `(payload, next_page)` pair where `payload` is the unwrapped data and `next_page` is the Asana `next_page` object (or `None`). Handles 429 + the error envelope.
3. **`_clean(d: dict) -> dict`** — drop `None`-valued keys before building a request body (so optional params are omitted, not sent as null). (Local helper; mirrors hubspot's `_props` None-filter — naming differs per-file, which is acceptable since helpers are file-local across the repo.)
4. **`_workspace(workspace_gid) -> str`** — resolve a workspace GID, falling back to `ASANA_DEFAULT_WORKSPACE_ID`; raise `ToolError` if neither present.
5. **`_opt(params, opt_fields)`** — attach `opt_fields` to query params when provided.

### Response Shape Decision (matches repo `_success()` convention)
The repo's structured integrations (notion, hubspot, etc.) **always** wrap output via `_success(status_code, **kw)` → `json.dumps({"status": "success", "status_code": sc, ...})`, surfacing collections as **flat keyword args** (`data=...`, `count=...`, plus a cursor field like `has_more`/`next_cursor`/`after`). This integration follows the same pattern — it does NOT return raw unwrapped `data` or a nested `{"data":..,"next_page":..}` blob.

- **Single-object endpoints:** `return _success(resp.status_code, data=<unwrapped data object>)`.
- **Collection endpoints:** `return _success(200, data=<unwrapped list>, count=len(list), next_offset=<next_page.offset or None>)` — `next_offset` is Asana's opaque offset token (or `null` when no more pages). This mirrors notion/hubspot's flat `data`+`count`+cursor shape, adapted to Asana's offset model.
- **Search endpoint:** has no `next_page`; return `_success(200, data=..., count=...)` with no `next_offset` (document that search is not offset-paginated).
- **Async duplicate endpoints:** return the Job object via `_success(..., data=<job>)`; callers poll with `asana_get_job`.
- Errors: Asana returns `{"errors": [{"message": "...", "help": "..."}]}`. The helper extracts the first `message` and raises `ToolError` (never returns a `_success` envelope for ≥400).

### Error Handling
- **400:** Invalid request (bad field, missing required) — surface Asana's `errors[0].message`.
- **401:** Invalid/expired token.
- **402:** Payment required (feature needs a paid plan — e.g. advanced search, some custom fields).
- **403:** Forbidden (no access to resource).
- **404:** Not found.
- **429:** Rate limited — include `Retry-After` seconds in the message.
- **500/503:** Asana service error.

### Config Addition (config.py)

```python
# Asana
ASANA_ACCESS_TOKEN: str | None = os.getenv("ASANA_ACCESS_TOKEN")
ASANA_DEFAULT_WORKSPACE_ID: str | None = os.getenv("ASANA_DEFAULT_WORKSPACE_ID")
```

### Registration (tools/__init__.py)

```python
from mcp_toolbox.tools import (..., asana_tool, ...)
# in register_all_tools:
asana_tool.register_tools(mcp)
```

---

## Testing Strategy

### Unit Tests (tests/test_asana_tool.py)
- Mock `httpx.AsyncClient` responses for all 67 tools (respx or monkeypatched `request`).
- Verify the `{"data": {...}}` request envelope is built correctly (L2 contract-style body assertions, matching the repo's recent testing discipline).
- Verify response unwrapping from `{"data": ...}` for single + collection.
- Verify `opt_fields` and pagination (`limit`/`offset`) pass-through as query params.
- Verify `_clean` drops `None` params (optional fields omitted, not null).
- Verify default-workspace fallback (`ASANA_DEFAULT_WORKSPACE_ID`) and the `ToolError` when no workspace resolves.
- Verify multipart attachment upload sets `parent` + `file` and does NOT JSON-wrap.
- Verify error handling: 429 (`Retry-After`), 402 (paid feature), 404, 401; missing `ASANA_ACCESS_TOKEN` raises immediately.

### Key Test Scenarios
1. `create_task` with `projects` omits `workspace` correctly / with neither raises.
2. `list_tasks` validates "exactly one scope" (project/section/tag, or assignee) — raises on 0 selectors AND on >1 (since Asana 400s on combined scopes); `assignee` requires `workspace` (defaulted).
3. `set_task_custom_field` builds `{"custom_fields": {gid: value}}` for enum (option gid), multi_enum (list), text/number.
4. `add_task_to_section` posts `{"data": {"task": gid}}` to `/sections/{gid}/addTask`.
5. `create_story` requires one of text/html_text.
6. Search tool hits `/workspaces/{gid}/tasks/search` with flattened `*.any` params.
7. Upload attachment reads a real temp file and sends multipart.

---

## Dependencies
- **httpx** — Already a project dependency (no new packages).
- **No SDK** — Direct HTTP, fully async, consistent with the rest of the toolbox.

## Files to Create/Modify

| File | Action |
|------|--------|
| `src/mcp_toolbox/tools/asana_tool.py` | Create — 67 tools + helpers |
| `src/mcp_toolbox/config.py` | Modify — Add `ASANA_ACCESS_TOKEN`, `ASANA_DEFAULT_WORKSPACE_ID` |
| `src/mcp_toolbox/tools/__init__.py` | Modify — Import + register asana tools |
| `tests/test_asana_tool.py` | Create — Unit tests for all 67 tools |
| `CLAUDE.md` | Modify — Add Asana to source layout + integrations section |

---

## References
- Asana API reference: https://developers.asana.com/reference/rest-api-reference
- Input/output options (opt_fields): https://developers.asana.com/docs/input-output-options
- Pagination: https://developers.asana.com/docs/pagination
- Rate limits: https://developers.asana.com/docs/rate-limits
- Personal access tokens: https://developers.asana.com/docs/personal-access-token
- Tasks: https://developers.asana.com/reference/tasks
- Stories: https://developers.asana.com/reference/stories
- Custom fields: https://developers.asana.com/reference/custom-fields
- Attachments (upload): https://developers.asana.com/reference/createattachmentforobject
- Search: https://developers.asana.com/reference/searchtasksforworkspace
- Jobs (async duplicate polling): https://developers.asana.com/reference/jobs
- Webhooks: https://developers.asana.com/docs/webhooks
