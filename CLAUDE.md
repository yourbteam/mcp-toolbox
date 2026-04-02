# MCP Toolbox

## Project Overview
Python MCP server that centralizes external API integrations for LLM/MCP clients. Built with the official MCP Python SDK (FastMCP).

## Tech Stack
- **Language:** Python 3.10+
- **Framework:** MCP SDK (`mcp` package) with FastMCP
- **Package Manager:** uv
- **Build Backend:** hatchling
- **HTTP Client:** httpx (async)
- **Testing:** pytest + pytest-asyncio
- **Linting:** ruff
- **Type Checking:** pyright

## Key Commands
```bash
uv sync --dev --all-extras   # Install all dependencies
uv run mcp-toolbox           # Run server (STDIO)
uv run pytest                # Run tests
uv run ruff check src/ tests/ # Lint
uv run pyright src/          # Type check
mcp dev src/mcp_toolbox/server.py  # MCP Inspector
```

## Source Layout
```
src/mcp_toolbox/
├── server.py              # FastMCP instance, tool registration, main()
├── config.py              # Environment loading (all integration keys)
└── tools/                 # One file per integration
    ├── __init__.py        # register_all_tools() hub
    ├── example_tool.py    # hello + add (scaffolding validation)
    ├── sendgrid_tool.py   # 14 SendGrid tools (email, management, contacts)
    ├── clickup_tool.py    # 81 ClickUp tools (full API v2 coverage)
    ├── o365_tool.py       # 19 O365 tools (send, read, drafts, folders)
    ├── teams_tool.py      # 28 Teams tools (teams, channels, messages, meetings)
    ├── keyvault_tool.py   # 39 Key Vault tools (secrets, keys, certificates)
    ├── aws_ssm_tool.py    # 13 AWS SSM tools (Parameter Store)
    ├── slack_tool.py      # 28 Slack tools (messages, channels, users, reactions)
    ├── http_tool.py       # 4 Generic HTTP tools (request, form, download, upload)
    ├── calendar_tool.py   # 23 Calendar tools (events, scheduling, attachments)
    ├── hubspot_tool.py    # 43 HubSpot CRM tools (contacts, companies, deals, tickets)
    └── jira_tool.py       # 44 Jira tools (issues, boards, sprints, worklogs)
```

## Integrations

### SendGrid (sendgrid_tool.py) — 14 tools
- **Tier 1 (Core Email):** send_email, send_template_email, send_email_with_attachment, schedule_email
- **Tier 2 (Management):** list_templates, get_template, get_email_stats, get_bounces, get_spam_reports, manage_suppressions
- **Tier 3 (Contacts):** add_contacts, search_contacts, get_contact, manage_lists
- **Config:** `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`, `SENDGRID_FROM_NAME`
- **SDK:** `sendgrid` v6.x (sync SDK, wrapped with `asyncio.to_thread()`)
- **Note:** pyright excludes this file due to SendGrid's dynamic fluent API being untyped

### ClickUp (clickup_tool.py) — 81 tools
- **Core Tasks (9):** get_workspaces, get_spaces, get_lists, create/get/update/delete task, get_tasks, search_tasks
- **Task Details (6):** add/get comments, create checklist, add checklist item, add/remove tag
- **Time Tracking (9):** log/get/delete time, start/stop/get running timer, update/delete time entry
- **Space/Folder/List CRUD (10):** get/update/delete space, get/get_one/update/delete folder, get/update/delete list
- **Comments & Checklists (6):** update/delete comment, update/delete checklist, update/delete checklist item
- **Tags (4):** get/create/update/delete space tags
- **Goals (8):** CRUD goals + create/update/delete key results (Business+)
- **Time Entry Tags (4):** get/add/remove/rename time entry tags
- **Time Entry Details (2):** get time entry, get time entry history
- **Views (12):** get/create views at workspace/space/folder/list level, get/update/delete view, get view tasks
- **Webhooks (4):** get/create/update/delete webhooks
- **Custom Fields (2):** get fields, set/remove field values
- **Config:** `CLICKUP_API_TOKEN`, `CLICKUP_TEAM_ID`
- **HTTP:** Direct `httpx.AsyncClient` (no SDK, native async)
- **Note:** Timestamps in milliseconds; fully typed (pyright enabled)

### Office 365 (o365_tool.py) — 19 tools
- **Sending (5):** send_email, send_email_with_attachment, reply, reply_all, forward
- **Reading (5):** list_messages, get_message, search_messages, list_attachments, move_message
- **Drafts (5):** create_draft, update_draft, add_draft_attachment, send_draft, delete_draft
- **Folders (4):** get_folder, list_folders, create_folder, delete_folder
- **Config:** `O365_TENANT_ID`, `O365_CLIENT_ID`, `O365_CLIENT_SECRET`, `O365_USER_ID`
- **Auth:** OAuth2 client credentials via `msal` (auto-caching, asyncio.to_thread for sync calls)
- **HTTP:** Singleton `httpx.AsyncClient` with per-request Bearer token
- **Note:** pyright excludes this file (msal lacks type stubs)

### Microsoft Teams (teams_tool.py) — 28 tools
- **Teams Mgmt (9):** list/get/create/update/archive/unarchive teams, list/add/remove members
- **Channels (5):** list/get/create/update/delete channels
- **Messaging (5):** list/get messages, list replies, send webhook, delegated send (placeholder)
- **Meetings (4):** create/list/get/delete meetings (requires Application Access Policy)
- **Presence (2):** get presence, bulk presence
- **Chat Reading (3):** list chats, get chat, list chat messages (read-only)
- **Config:** `TEAMS_TENANT_ID`, `TEAMS_CLIENT_ID`, `TEAMS_CLIENT_SECRET` (falls back to O365 credentials)
- **Auth:** Same msal OAuth2 as O365; webhook tool uses separate httpx client (no auth)
- **Note:** App-only cannot send channel/chat messages via Graph API; use webhook for sending

### Azure Key Vault (keyvault_tool.py) — 39 tools
- **Secrets (11):** set, get, list, list_versions, update, delete, recover, purge, list_deleted, backup, restore
- **Keys (18):** create, get, list, list_versions, update, delete, recover, purge, list_deleted, rotate, encrypt, decrypt, sign, verify, wrap, unwrap, backup, restore
- **Certificates (10):** get, list, list_versions, create, import, update, delete, recover, purge, list_deleted
- **Config:** `KEYVAULT_URL` + `KEYVAULT_TENANT_ID/CLIENT_ID/CLIENT_SECRET` (falls back to O365)
- **Auth:** Own msal instance with `vault.azure.net` scope (separate from Graph API tokens)
- **Note:** Vault-specific base URL; api-version=7.4 auto-appended; pyright excluded (msal)

### AWS Parameter Store (aws_ssm_tool.py) — 13 tools
- **CRUD (7):** put, get, get_multiple, get_by_path, describe, delete, delete_multiple
- **Versioning (3):** get_history, label_version, unlabel_version
- **Tagging (3):** add_tags, remove_tags, list_tags
- **Config:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` (all optional — boto3 auto-resolves)
- **SDK:** `boto3` (sync, wrapped with `asyncio.to_thread`)
- **Note:** Free tier: 10,000 params; supports SecureString (KMS encrypted); hierarchical paths

### Slack (slack_tool.py) — 28 tools
- **Messaging (7):** send_message, send_dm, update, delete, schedule, channel_history, thread_replies
- **Channels (9):** list, get_info, create, archive, unarchive, invite, list_members, set_topic, set_purpose
- **Users (4):** list, get_info, find_by_email, get_presence
- **Reactions (3):** add, remove, get
- **Pins (3):** pin, unpin, list
- **Files (2):** upload, delete
- **Config:** `SLACK_BOT_TOKEN` (xoxb-...)
- **SDK:** `slack_sdk.WebClient` (sync, wrapped with `asyncio.to_thread`)

### Generic HTTP (http_tool.py) — 4 tools
- `http_request` — Any method/URL/headers/body (the escape hatch for any REST API)
- `http_request_form` — Form-encoded POST
- `http_download` — Stream download to file
- `http_upload` — Multipart file upload
- **Config:** None — everything per-request
- **Note:** Fresh httpx client per request (no singleton); response truncation at 50K chars

### MS Graph Calendar (calendar_tool.py) — 23 tools
- **Calendars (4):** list, get, create, delete
- **Events (5):** create, get, update, delete, list (calendarView)
- **Responses (3):** accept, decline, tentatively accept
- **Scheduling (2):** get free/busy schedule, find meeting times
- **Recurring (1):** list event instances
- **Actions (2):** forward, cancel
- **Attachments (4):** add, list, get, delete
- **Reminders (2):** snooze, dismiss
- **Config:** Reuses O365 credentials (no new config)
- **Auth:** Same msal + Graph API token as O365 email

### HubSpot CRM (hubspot_tool.py) — 43 tools
- **Contacts (6):** create, get, update, delete, list, search
- **Companies (6):** create, get, update, delete, list, search
- **Deals (6):** create, get, update, delete, list, search
- **Tickets (6):** create, get, update, delete, list, search
- **Notes (6):** create, get, list, update, delete, search
- **Associations (4):** create, remove, get, list types
- **Pipelines (2):** list pipelines, list stages
- **Owners (2):** list, get
- **Properties (3):** list, get, create
- **Batch (2):** batch create, batch update
- **Config:** `HUBSPOT_API_TOKEN`
- **HTTP:** Direct httpx with Bearer token auth

### Jira (jira_tool.py) — 44 tools
- **Issues (15):** create, get, update, delete, search (JQL), transition, assign, comments CRUD, attachments
- **Projects (2):** list, get
- **Boards (3):** list, get, get issues
- **Sprints (4):** list, get, get issues, move to sprint
- **Users (2):** search, get
- **Metadata (2):** list priorities, list statuses
- **Worklogs (4):** add, list, update, delete
- **Watchers (3):** get, add, remove
- **Issue Links (3):** create, delete, list types
- **Components (2):** list, create
- **Versions (2):** list, create
- **Labels (1):** list
- **Bulk (1):** bulk create issues
- **Config:** `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`
- **Auth:** Basic auth (email:token base64), dual API paths (platform v3 + agile v1.0)

## Tool Module Convention
Each integration file in `tools/` must:
1. Define async tool functions with full type hints
2. Export a `register_tools(mcp: FastMCP)` function
3. Use `logging.getLogger(__name__)` for observability
4. Use `ToolError` from `mcp.server.fastmcp.exceptions` for error responses

## Task Tracking
See `Tasks/` folder — each task has `analysis.md` (requirements) and `plan.md` (implementation).

## Memory
- [Task Execution Workflow](feedback_task_workflow.md) — Full end-to-end: create task, analysis, /verify-analysis, plan, /verify-plan, implement, commit, /review-fix-loop, push
- [MCP Toolbox Project Overview](project_mcp_toolbox.md) — Python MCP server providing external API integrations for LLM clients
- [Testing Discipline](feedback_testing_discipline.md) — Every feature must include tests, pass them, then pass full regression before moving on
- [Memory Sync to CLAUDE.md](feedback_memory_sync.md) — Whenever memory is added/updated, sync the Memory section in CLAUDE.md to match
- [Memory Sync on Git Pull](feedback_memory_git_pull_sync.md) — After git pull, check CLAUDE.md for new memory entries from other machines and sync locally
- [Never Stop Mid-Workflow](feedback_complete_workflow.md) — NEVER pause between workflow steps — execute the entire sequence without stopping or asking
