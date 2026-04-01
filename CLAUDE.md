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
├── config.py              # Environment loading (LOG_LEVEL, SendGrid, ClickUp keys)
└── tools/                 # One file per integration
    ├── __init__.py        # register_all_tools() hub
    ├── example_tool.py    # hello + add (scaffolding validation)
    ├── sendgrid_tool.py   # 14 SendGrid tools (email, management, contacts)
    └── clickup_tool.py    # 25 ClickUp tools (tasks, comments, time, org)
```

## Integrations

### SendGrid (sendgrid_tool.py) — 14 tools
- **Tier 1 (Core Email):** send_email, send_template_email, send_email_with_attachment, schedule_email
- **Tier 2 (Management):** list_templates, get_template, get_email_stats, get_bounces, get_spam_reports, manage_suppressions
- **Tier 3 (Contacts):** add_contacts, search_contacts, get_contact, manage_lists
- **Config:** `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`, `SENDGRID_FROM_NAME`
- **SDK:** `sendgrid` v6.x (sync SDK, wrapped with `asyncio.to_thread()`)
- **Note:** pyright excludes this file due to SendGrid's dynamic fluent API being untyped

### ClickUp (clickup_tool.py) — 25 tools
- **Tier 1 (Core Tasks):** clickup_get_workspaces, clickup_get_spaces, clickup_get_lists, clickup_create_task, clickup_get_task, clickup_update_task, clickup_get_tasks, clickup_search_tasks, clickup_delete_task
- **Tier 2 (Details):** clickup_add_comment, clickup_get_comments, clickup_create_checklist, clickup_add_checklist_item, clickup_add_tag, clickup_remove_tag
- **Tier 3 (Time):** clickup_log_time, clickup_get_time_entries, clickup_start_timer, clickup_stop_timer
- **Tier 4 (Org):** clickup_create_space, clickup_create_list, clickup_create_folder, clickup_get_members, clickup_get_custom_fields, clickup_set_custom_field
- **Config:** `CLICKUP_API_TOKEN`, `CLICKUP_TEAM_ID`
- **HTTP:** Direct `httpx.AsyncClient` (no SDK, native async)
- **Note:** pyright excludes this file; timestamps in milliseconds

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
