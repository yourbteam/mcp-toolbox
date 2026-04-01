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
├── server.py       # FastMCP instance, tool registration, main()
├── config.py       # Environment loading (LOG_LEVEL, API keys)
└── tools/          # One file per integration
    ├── __init__.py # register_all_tools() hub
    └── *.py        # Each exports register_tools(mcp: FastMCP)
```

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
