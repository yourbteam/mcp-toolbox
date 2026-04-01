"""Tests for the example tool."""

import pytest
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.example_tool import register_tools


@pytest.fixture
def server():
    mcp = FastMCP("test")
    register_tools(mcp)
    return mcp


@pytest.mark.asyncio
async def test_hello_default(server):
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
