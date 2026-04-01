# Task 01: Project Scaffolding - Analysis & Requirements

## Objective
Establish the foundational project structure for `mcp-toolbox`, a Python MCP server that centralizes external API integrations for consumption by other LLM/MCP clients.

---

## Research Findings

### SDK & Runtime Requirements
- **Official Package:** `mcp` on PyPI (includes FastMCP, the recommended server framework)
- **Python Version:** >= 3.10 required
- **Package Manager:** `uv` (modern, fast — recommended by the MCP ecosystem)
- **Build Backend:** `hatchling` via `pyproject.toml`

### Transport Options
| Transport | Use Case | Performance |
|-----------|----------|-------------|
| **STDIO** | Local development, Claude Desktop | 10,000+ ops/sec |
| **Streamable HTTP** | Production, multi-client | 100-1,000 ops/sec, scalable |
| **SSE** | Legacy — superseded by Streamable HTTP | Still functional but not recommended for new projects |

**Decision:** Support both STDIO (default/dev) and Streamable HTTP (production).

### Tool Registration Pattern
- **Import:** `from mcp.server.fastmcp import FastMCP` (bundled in the `mcp` SDK)
- Tools are registered using `@mcp.tool()` decorators
- FastMCP auto-generates JSON schemas from Python type hints and docstrings
- Async-first design — all tools should be `async` functions
- Tools must have fully typed parameters (no `*args`/`**kwargs`)
- Use `ToolError` from `mcp.server.fastmcp.exceptions` for structured error responses

> **Note:** The standalone `fastmcp` PyPI package (v3.0+) offers additional features like FileSystemProvider for automatic tool discovery. The `mcp[cli]` SDK bundles a compatible but more minimal FastMCP. If auto-discovery is desired later, switching to the standalone package is an upgrade path.

### Tool Organization (Multi-Integration Server)
The recommended pattern for a server with many API integrations:
- Separate module per integration under a `tools/` directory
- Each module exposes a `register_tools(mcp)` function
- `server.py` imports and wires all tool modules
- Business logic (API calls) stays in the tool modules, not in the server entry point

---

## Requirements

### R1: Project Configuration
- `pyproject.toml` with project metadata, dependencies, scripts entry point
- `.python-version` pinned to 3.10+
- `.gitignore` covering Python/venv/IDE artifacts
- `.env.example` for documenting required API keys

### R2: Source Layout
Follow the `src/` layout convention:
```
src/
  mcp_toolbox/
    __init__.py
    __main__.py        # Entry point: python -m mcp_toolbox
    server.py          # FastMCP instance creation and tool registration
    config.py          # Environment/config loading
    tools/
      __init__.py      # Tool module auto-discovery or explicit imports
```

### R3: Tool Module Convention
Each integration gets its own file under `tools/`:
```
tools/
  __init__.py
  example_tool.py     # Starter/example tool to validate the setup
```

Each tool module follows this contract:
- Contains the async business logic functions
- Exports a `register_tools(mcp: FastMCP)` function that decorates and registers tools
- Uses `ToolError` for error responses that should be visible to the LLM client

### R4: Entry Points
- **CLI:** `uv run mcp-toolbox` via `[project.scripts]`
- **Module:** `python -m mcp_toolbox` via `__main__.py`
- **Dev:** `mcp dev src/mcp_toolbox/server.py` for MCP Inspector

### R5: Dependencies
| Package | Purpose |
|---------|---------|
| `mcp[cli]` | MCP SDK + FastMCP + CLI tools |
| `httpx` | Async HTTP client for API integrations |
| `python-dotenv` | Environment variable loading |
| `pydantic` | Data validation (included with mcp, but explicit) |

| Dev Dependency | Purpose |
|----------------|---------|
| `pytest` | Test framework |
| `pytest-asyncio` | Async test support |
| `ruff` | Linting and formatting |
| `pyright` | Static type checking |

### R6: Configuration Management
- Use `python-dotenv` to load `.env` files for local development
- Centralize config in `config.py`
- `.env.example` documents all expected variables
- **Caveat:** When spawned by an MCP client (e.g., Claude Desktop), the working directory is not the project root, so `.env` auto-discovery will fail. For deployed usage, configure environment variables via the host's MCP config (e.g., `claude_desktop_config.json` `env` field) or use absolute paths in `config.py`

### R6a: Logging
- Use the SDK's built-in logging via `mcp.server.fastmcp.utilities.logging.get_logger()`
- `config.py` should expose a log-level setting (default: INFO)
- Tool modules should log key operations (API calls, errors) for observability

### R7: Testing Structure
```
tests/
  __init__.py
  test_server.py       # Server initialization tests
  test_example_tool.py # Example tool validation
```

### R8: Documentation
- `README.md` with project description, setup instructions, usage, and Claude Desktop configuration example
- `CLAUDE.md` with project-specific context for Claude Code sessions (follows existing portfolio convention)
- Existing `Tasks/` folder for task tracking (already in place)

---

## Target Directory Structure

```
mcp-toolbox/
├── README.md
├── CLAUDE.md                  # Project context for Claude Code
├── pyproject.toml
├── uv.lock                    # Generated by uv
├── .python-version
├── .gitignore
├── .env.example
├── Tasks/                     # Task tracking (exists)
│   └── 01-project-scaffolding/
│       ├── analysis.md        # This document
│       └── plan.md            # Implementation plan
├── src/
│   └── mcp_toolbox/
│       ├── __init__.py
│       ├── __main__.py
│       ├── server.py
│       ├── config.py
│       └── tools/
│           ├── __init__.py
│           └── example_tool.py
└── tests/
    ├── __init__.py
    ├── test_server.py
    └── test_example_tool.py
```

---

## Success Criteria
1. `uv sync` installs all dependencies without errors
2. `uv run mcp-toolbox` starts the server successfully
3. The example tool is discoverable and callable via MCP Inspector (`mcp dev`)
4. `uv run pytest` passes all tests
5. Project structure supports adding new integrations by dropping a new file in `tools/`
