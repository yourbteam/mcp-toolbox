# Task 01: Project Scaffolding - Implementation Plan

## Overview
Implement the scaffolding for `mcp-toolbox` in 6 sequential steps. Each step produces verifiable output before moving to the next.

---

## Step 1: Project Configuration Files

Create the foundational config files at the project root.

### 1a. `pyproject.toml`
```toml
[project]
name = "mcp-toolbox"
version = "0.1.0"
description = "MCP server providing external API integrations for LLM clients"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "mcp[cli]>=1.6.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
    "pyright>=1.1.0",
]

[project.scripts]
mcp-toolbox = "mcp_toolbox.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
target-version = "py310"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]

[tool.pyright]
pythonVersion = "3.10"
typeCheckingMode = "basic"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### 1b. `.python-version`
```
3.10
```

### 1c. `.gitignore`
Standard Python gitignore covering:
- `__pycache__/`, `*.pyc`, `*.pyo`
- `.venv/`, `venv/`, `env/`
- `.env` (not `.env.example`)
- `dist/`, `build/`, `*.egg-info/`
- IDE files: `.vscode/`, `.idea/`
- `uv.lock` — **include in repo** (not gitignored)
- `.ruff_cache/`, `.pyright/`

### 1d. `.env.example`
```env
# MCP Toolbox Configuration
# Copy to .env and fill in values for local development
# For Claude Desktop: set these in claude_desktop_config.json "env" field

LOG_LEVEL=INFO

# Add API keys for integrations below as they are added
# EXAMPLE_API_KEY=your-key-here
```

**Verify:** Files exist, no syntax errors.

---

## Step 2: Source Package Structure

Create `src/mcp_toolbox/` with core modules.

### 2a. `src/mcp_toolbox/__init__.py`
```python
"""MCP Toolbox - External API integrations for LLM clients."""

__version__ = "0.1.0"
```

### 2b. `src/mcp_toolbox/config.py`
```python
"""Configuration management for MCP Toolbox."""

import os
from pathlib import Path
from typing import Literal, cast

from dotenv import load_dotenv

# Load .env for local development; in production, env vars come from host config
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

LOG_LEVEL: LogLevel = cast(LogLevel, os.getenv("LOG_LEVEL", "INFO"))
```

Key decisions:
- Uses absolute path resolution (`Path(__file__).resolve()`) to locate `.env` relative to the package, avoiding the working-directory caveat from R6
- Simple module-level constants — no class needed at this stage
- Future API keys follow the same `os.getenv()` pattern

### 2c. `src/mcp_toolbox/server.py`
```python
"""MCP Toolbox server — main entry point."""

from mcp.server.fastmcp import FastMCP

from mcp_toolbox.config import LOG_LEVEL
from mcp_toolbox.tools import register_all_tools

mcp = FastMCP("mcp-toolbox", log_level=LOG_LEVEL)

register_all_tools(mcp)


def main() -> None:
    """Run the MCP server (STDIO transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
```

Key decisions:
- `mcp` instance created at module level so tools can reference it during registration
- `register_all_tools()` keeps server.py clean — one import per concern
- `main()` function used by `[project.scripts]` entry point

### 2d. `src/mcp_toolbox/__main__.py`
```python
"""Allow running as: python -m mcp_toolbox."""

from mcp_toolbox.server import main

main()
```

---

## Step 3: Tools Package

### 3a. `src/mcp_toolbox/tools/__init__.py`
```python
"""Tool registration hub — imports all tool modules and registers them."""

from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools import example_tool


def register_all_tools(mcp: FastMCP) -> None:
    """Register all tool modules with the MCP server."""
    example_tool.register_tools(mcp)
```

Adding a new integration: create `new_tool.py`, import it here, call `new_tool.register_tools(mcp)`.

### 3b. `src/mcp_toolbox/tools/example_tool.py`
```python
"""Example tool — validates the scaffolding works end-to-end."""

import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_tools(mcp: FastMCP) -> None:
    """Register example tools with the MCP server."""

    @mcp.tool()
    async def hello(name: str = "World") -> str:
        """Say hello. Use this to verify the MCP server is working."""
        logger.info("hello tool called with name=%s", name)
        return f"Hello, {name}! MCP Toolbox is running."

    @mcp.tool()
    async def add(a: float, b: float) -> float:
        """Add two numbers together."""
        return a + b
```

Key decisions:
- Two simple tools: one string-based, one numeric — validates schema generation for different types
- No external dependencies — this tool is purely for scaffolding validation
- `register_tools()` follows the convention from R3
- Demonstrates the logging pattern (R6a): `logger = logging.getLogger(__name__)` — future integration tools should log API calls and errors similarly

---

## Step 4: Tests

### 4a. `tests/__init__.py`
Empty file.

### 4b. `tests/test_server.py`
```python
"""Tests for server initialization."""

from mcp_toolbox.server import mcp


def test_server_name():
    assert mcp.name == "mcp-toolbox"


def test_server_has_tools():
    # After import, tools should be registered
    tools = mcp._tool_manager._tools
    assert len(tools) > 0
```

### 4c. `tests/test_example_tool.py`
```python
"""Tests for the example tool."""

import pytest
from mcp_toolbox.tools.example_tool import register_tools
from mcp.server.fastmcp import FastMCP


@pytest.fixture
def server():
    mcp = FastMCP("test")
    register_tools(mcp)
    return mcp


@pytest.mark.asyncio
async def test_hello_default(server):
    # Call the tool function directly
    result = await server.call_tool("hello", {"name": "World"})
    assert "Hello, World!" in str(result)


@pytest.mark.asyncio
async def test_hello_custom(server):
    result = await server.call_tool("hello", {"name": "Claude"})
    assert "Hello, Claude!" in str(result)


@pytest.mark.asyncio
async def test_add(server):
    result = await server.call_tool("add", {"a": 2.5, "b": 3.5})
    assert "6.0" in str(result)
```

**Note:** The exact assertion patterns may need adjustment based on how `call_tool` returns results (text content wrapper vs raw value). Will verify during implementation and adjust.

---

## Step 5: Documentation

### 5a. `README.md`
Update the existing README with:
- Project description (what it is, what it does)
- Prerequisites (Python 3.10+, uv)
- Quick start (clone, `uv sync`, `uv run mcp-toolbox`)
- Development (run tests, lint, type check)
- Claude Desktop configuration example:
  ```json
  {
    "mcpServers": {
      "mcp-toolbox": {
        "command": "uv",
        "args": ["--directory", "/absolute/path/to/mcp-toolbox", "run", "mcp-toolbox"],
        "env": {
          "LOG_LEVEL": "INFO"
        }
      }
    }
  }
  ```
- Adding new tools (brief guide referencing the convention)

### 5b. `CLAUDE.md`
Project-specific Claude Code context:
- Project name and purpose
- Tech stack (Python, MCP SDK, FastMCP)
- Key commands (`uv sync`, `uv run mcp-toolbox`, `uv run pytest`, `uv run ruff check`)
- Source layout summary
- Tool module convention (register_tools pattern)
- Link to Tasks/ for tracking

---

## Step 6: Initialize & Validate

### 6a. Install dependencies
```bash
uv sync --dev --all-extras
```

### 6b. Run validation checks
```bash
# Success Criteria 1: Dependencies install
uv sync

# Success Criteria 4: Tests pass
uv run pytest

# Success Criteria 2: Server starts (will block on STDIO, Ctrl+C to exit)
# Verify no import errors or crashes on startup
uv run mcp-toolbox &
sleep 2
kill %1

# Linting and type checking
uv run ruff check src/ tests/
uv run pyright src/
```

### 6c. Verify with MCP Inspector (manual)
```bash
# Success Criteria 3: Tools discoverable
mcp dev src/mcp_toolbox/server.py
```
- Confirm `hello` and `add` tools appear in the Inspector
- Call `hello` with `name: "Test"` → expect `"Hello, Test! MCP Toolbox is running."`
- Call `add` with `a: 2, b: 3` → expect `5.0`

---

## Execution Order

| Order | Step | Requirement | Depends On |
|-------|------|-------------|------------|
| 1 | Project config files | R1 | — |
| 2 | Source package structure | R2, R6, R6a | Step 1 |
| 3 | Tools package | R3 | Step 2 |
| 4 | Tests | R7 | Steps 2-3 |
| 5 | Documentation | R8 | Steps 1-3 |
| 6 | Initialize & validate | All SC | Steps 1-5 |

Steps 4 and 5 are independent and can be done in parallel.

---

## Risk Notes

- **Test assertions:** `call_tool` return format may differ from expectations — adjust assertions during implementation based on actual SDK behavior
- **`_tool_manager` access:** Internal API used in `test_server.py` — may break on SDK updates. Acceptable for scaffolding validation; refine later if needed
- **uv version:** Assumes `uv` is installed globally. If not, Step 6 will fail — add install instruction to README
