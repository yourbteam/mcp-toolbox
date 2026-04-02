"""Tests for Generic HTTP tools."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.http_tool import register_tools


def _get_result_data(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    register_tools(mcp)
    return mcp


# --- http_request ---


@pytest.mark.asyncio
@respx.mock
async def test_request_get_json(server):
    respx.get("https://api.example.com/users").mock(
        return_value=httpx.Response(200, json={"users": []})
    )
    result = await server.call_tool("http_request", {
        "method": "GET", "url": "https://api.example.com/users",
    })
    data = _get_result_data(result)
    assert data["status_code"] == 200
    assert data["body"] == {"users": []}
    assert data["truncated"] is False


@pytest.mark.asyncio
@respx.mock
async def test_request_post_json_body(server):
    respx.post("https://api.example.com/items").mock(
        return_value=httpx.Response(201, json={"id": "123"})
    )
    result = await server.call_tool("http_request", {
        "method": "POST", "url": "https://api.example.com/items",
        "json_body": {"name": "test"},
    })
    data = _get_result_data(result)
    assert data["status_code"] == 201


@pytest.mark.asyncio
@respx.mock
async def test_request_with_auth_header(server):
    respx.get("https://api.example.com/me").mock(
        return_value=httpx.Response(200, json={"name": "John"})
    )
    result = await server.call_tool("http_request", {
        "method": "GET", "url": "https://api.example.com/me",
        "auth_header": "Bearer test-token",
    })
    assert _get_result_data(result)["status_code"] == 200


@pytest.mark.asyncio
@respx.mock
async def test_request_with_params(server):
    respx.get("https://api.example.com/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    result = await server.call_tool("http_request", {
        "method": "GET", "url": "https://api.example.com/search",
        "params": {"q": "test", "limit": "10"},
    })
    assert _get_result_data(result)["status_code"] == 200


@pytest.mark.asyncio
async def test_request_invalid_method(server):
    with pytest.raises(Exception, match="Invalid HTTP method"):
        await server.call_tool("http_request", {
            "method": "INVALID", "url": "https://example.com",
        })


@pytest.mark.asyncio
async def test_request_invalid_url(server):
    with pytest.raises(Exception, match="must start with http"):
        await server.call_tool("http_request", {
            "method": "GET", "url": "ftp://example.com",
        })


@pytest.mark.asyncio
async def test_request_both_bodies(server):
    with pytest.raises(Exception, match="Cannot provide both"):
        await server.call_tool("http_request", {
            "method": "POST", "url": "https://example.com",
            "json_body": {"a": 1}, "text_body": "hello",
        })


@pytest.mark.asyncio
@respx.mock
async def test_request_text_response(server):
    respx.get("https://example.com").mock(
        return_value=httpx.Response(
            200, text="Hello World",
            headers={"content-type": "text/plain"},
        )
    )
    result = await server.call_tool("http_request", {
        "method": "GET", "url": "https://example.com",
    })
    data = _get_result_data(result)
    assert data["body"] == "Hello World"


@pytest.mark.asyncio
@respx.mock
async def test_request_binary_response(server):
    respx.get("https://example.com/img.png").mock(
        return_value=httpx.Response(
            200, content=b"\x89PNG\r\n",
            headers={"content-type": "image/png"},
        )
    )
    result = await server.call_tool("http_request", {
        "method": "GET", "url": "https://example.com/img.png",
    })
    data = _get_result_data(result)
    assert "Binary content" in data["body"]


@pytest.mark.asyncio
@respx.mock
async def test_request_truncation(server):
    respx.get("https://example.com/big").mock(
        return_value=httpx.Response(
            200, text="x" * 1000,
            headers={"content-type": "text/plain"},
        )
    )
    result = await server.call_tool("http_request", {
        "method": "GET", "url": "https://example.com/big",
        "max_response_size": 100,
    })
    data = _get_result_data(result)
    assert data["truncated"] is True
    assert len(data["body"]) == 100


@pytest.mark.asyncio
@respx.mock
async def test_request_4xx_returned_not_error(server):
    respx.get("https://api.example.com/missing").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )
    result = await server.call_tool("http_request", {
        "method": "GET", "url": "https://api.example.com/missing",
    })
    data = _get_result_data(result)
    assert data["status_code"] == 404


# --- http_request_form ---


@pytest.mark.asyncio
@respx.mock
async def test_form_post(server):
    respx.post("https://oauth.example.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "abc"})
    )
    result = await server.call_tool("http_request_form", {
        "url": "https://oauth.example.com/token",
        "data": {"grant_type": "client_credentials", "client_id": "xxx"},
    })
    data = _get_result_data(result)
    assert data["status_code"] == 200


@pytest.mark.asyncio
async def test_form_empty_data(server):
    with pytest.raises(Exception, match="non-empty dict"):
        await server.call_tool("http_request_form", {
            "url": "https://example.com", "data": {},
        })


# --- http_download ---


@pytest.mark.asyncio
@respx.mock
async def test_download_file(server, tmp_path):
    content = b"PDF file content here"
    respx.get("https://example.com/report.pdf").mock(
        return_value=httpx.Response(
            200, content=content,
            headers={"content-type": "application/pdf"},
        )
    )
    save_path = str(tmp_path / "report.pdf")
    result = await server.call_tool("http_download", {
        "url": "https://example.com/report.pdf",
        "save_path": save_path,
    })
    data = _get_result_data(result)
    assert data["status_code"] == 200
    assert data["file_size_bytes"] == len(content)
    assert Path(save_path).read_bytes() == content


@pytest.mark.asyncio
@respx.mock
async def test_download_exceeds_max_size(server, tmp_path):
    respx.get("https://example.com/huge").mock(
        return_value=httpx.Response(
            200, content=b"x" * 2000,
            headers={"content-type": "application/octet-stream"},
        )
    )
    save_path = tmp_path / "huge.bin"
    with pytest.raises(Exception, match="max_file_size"):
        await server.call_tool("http_download", {
            "url": "https://example.com/huge",
            "save_path": str(save_path),
            "max_file_size": 500,
        })
    # Partial file should be cleaned up
    assert not save_path.exists()


@pytest.mark.asyncio
async def test_download_parent_missing(server):
    with pytest.raises(Exception, match="Parent directory"):
        await server.call_tool("http_download", {
            "url": "https://example.com/file",
            "save_path": "/nonexistent/dir/file.txt",
        })


@pytest.mark.asyncio
@respx.mock
async def test_download_http_error(server, tmp_path):
    respx.get("https://example.com/missing").mock(
        return_value=httpx.Response(404, text="Not Found")
    )
    save_path = str(tmp_path / "file.txt")
    result = await server.call_tool("http_download", {
        "url": "https://example.com/missing",
        "save_path": save_path,
    })
    data = _get_result_data(result)
    assert data["status_code"] == 404


# --- http_upload ---


@pytest.mark.asyncio
@respx.mock
async def test_upload_file(server, tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello upload")
    respx.post("https://api.example.com/upload").mock(
        return_value=httpx.Response(200, json={"id": "f123"})
    )
    result = await server.call_tool("http_upload", {
        "url": "https://api.example.com/upload",
        "file_path": str(test_file),
    })
    data = _get_result_data(result)
    assert data["status_code"] == 200


@pytest.mark.asyncio
async def test_upload_file_not_found(server):
    with pytest.raises(Exception, match="File not found"):
        await server.call_tool("http_upload", {
            "url": "https://example.com/upload",
            "file_path": "/nonexistent/file.txt",
        })


@pytest.mark.asyncio
@respx.mock
async def test_upload_with_extra_fields(server, tmp_path):
    test_file = tmp_path / "img.jpg"
    test_file.write_bytes(b"\xff\xd8\xff")
    respx.post("https://api.example.com/process").mock(
        return_value=httpx.Response(200, json={"result": "ok"})
    )
    result = await server.call_tool("http_upload", {
        "url": "https://api.example.com/process",
        "file_path": str(test_file),
        "file_field_name": "image",
        "extra_fields": {"size": "auto"},
    })
    data = _get_result_data(result)
    assert data["status_code"] == 200
