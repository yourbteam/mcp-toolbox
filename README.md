# mcp-toolbox

MCP server providing external API integrations for LLM clients. Connect your AI tools to external APIs through a single MCP server.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager

## Quick Start

```bash
# Install dependencies
uv sync --dev --all-extras

# Run the server
uv run mcp-toolbox
```

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check src/ tests/

# Type check
uv run pyright src/

# MCP Inspector (interactive tool testing)
mcp dev src/mcp_toolbox/server.py
```

## Configuration

Copy `.env.example` to `.env` for local development:

```bash
cp .env.example .env
```

For Claude Desktop, add to your `claude_desktop_config.json`:

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

## Adding New Tools

1. Create a new file in `src/mcp_toolbox/tools/` (e.g., `my_api.py`)
2. Implement your tools and a `register_tools(mcp)` function:

```python
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def my_tool(param: str) -> str:
        """Description of what this tool does."""
        logger.info("my_tool called with param=%s", param)
        # Your API integration here
        return "result"
```

3. Register it in `src/mcp_toolbox/tools/__init__.py`:

```python
from mcp_toolbox.tools import my_api

def register_all_tools(mcp: FastMCP) -> None:
    example_tool.register_tools(mcp)
    my_api.register_tools(mcp)  # Add this line
```

## Project Structure

```
src/mcp_toolbox/
├── __init__.py        # Package version
├── __main__.py        # python -m mcp_toolbox entry point
├── server.py          # FastMCP instance and tool registration
├── config.py          # Environment/config loading
└── tools/
    ├── __init__.py    # Tool registration hub
    └── example_tool.py # Example tools (hello, add)
```
