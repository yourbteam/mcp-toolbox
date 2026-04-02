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
├── config.py              # Environment loading (LOG_LEVEL, SendGrid, ClickUp, O365 keys)
└── tools/                 # One file per integration
    ├── __init__.py        # register_all_tools() hub
    ├── example_tool.py    # hello + add (scaffolding validation)
    ├── sendgrid_tool.py   # 14 SendGrid tools (email, management, contacts)
    ├── clickup_tool.py    # 81 ClickUp tools (full API v2 coverage)
    └── o365_tool.py       # 19 O365 tools (send, read, drafts, folders)
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

## Tool Module Convention
Each integration file in `tools/` must:
1. Define async tool functions with full type hints
2. Export a `register_tools(mcp: FastMCP)` function
3. Use `logging.getLogger(__name__)` for observability
4. Use `ToolError` from `mcp.server.fastmcp.exceptions` for error responses

## Task Tracking
See `Tasks/` folder — each task has `analysis.md` (requirements) and `plan.md` (implementation).

## Memory
- [Task Execution Workflow](feedback_task_workflow.md) — Create Tasks/subfolder with analysis.md and plan.md for each task
- [MCP Toolbox Project Overview](project_mcp_toolbox.md) — Python MCP server providing external API integrations for LLM clients
- [Testing Discipline](feedback_testing_discipline.md) — Every feature must include tests, pass them, then pass full regression before moving on
- [Memory Sync to CLAUDE.md](feedback_memory_sync.md) — Whenever memory is added/updated, sync the Memory section in CLAUDE.md to match
- [Memory Sync on Git Pull](feedback_memory_git_pull_sync.md) — After git pull, check CLAUDE.md for new memory entries from other machines and sync locally
