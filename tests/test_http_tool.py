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
    route = respx.get("https://api.example.com/users").mock(
        return_value=httpx.Response(200, json={"users": []})
    )
    result = await server.call_tool("http_request", {
        "method": "GET", "url": "https://api.example.com/users",
    })
    data = _get_result_data(result)
    assert data["status_code"] == 200
    assert data["body"] == {"users": []}
    assert data["truncated"] is False
    # Contract: GET with no body
    req = route.calls[0].request
    assert req.method == "GET"
    assert str(req.url) == "https://api.example.com/users"
    assert req.content == b""


@pytest.mark.asyncio
@respx.mock
async def test_request_post_json_body(server):
    route = respx.post("https://api.example.com/items").mock(
        return_value=httpx.Response(201, json={"id": "123"})
    )
    result = await server.call_tool("http_request", {
        "method": "POST", "url": "https://api.example.com/items",
        "json_body": {"name": "test"},
    })
    data = _get_result_data(result)
    assert data["status_code"] == 201
    # Contract: JSON body sent correctly
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body == {"name": "test"}
    assert req.headers["content-type"] == "application/json"


@pytest.mark.asyncio
@respx.mock
async def test_request_with_auth_header(server):
    route = respx.get("https://api.example.com/me").mock(
        return_value=httpx.Response(200, json={"name": "John"})
    )
    result = await server.call_tool("http_request", {
        "method": "GET", "url": "https://api.example.com/me",
        "auth_header": "Bearer test-token",
    })
    assert _get_result_data(result)["status_code"] == 200
    # Contract: Authorization header sent
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer test-token"


@pytest.mark.asyncio
@respx.mock
async def test_request_with_params(server):
    route = respx.get("https://api.example.com/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    result = await server.call_tool("http_request", {
        "method": "GET", "url": "https://api.example.com/search",
        "params": {"q": "test", "limit": "10"},
    })
    assert _get_result_data(result)["status_code"] == 200
    # Contract: query params appended to URL
    req = route.calls[0].request
    assert "q=test" in str(req.url)
    assert "limit=10" in str(req.url)


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
    route = respx.get("https://example.com").mock(
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
    # Contract: GET with no body
    req = route.calls[0].request
    assert req.method == "GET"
    assert req.content == b""


@pytest.mark.asyncio
@respx.mock
async def test_request_binary_response(server):
    route = respx.get("https://example.com/img.png").mock(
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
    # Contract: GET request with no body
    req = route.calls[0].request
    assert req.method == "GET"
    assert str(req.url) == "https://example.com/img.png"


@pytest.mark.asyncio
@respx.mock
async def test_request_truncation(server):
    route = respx.get("https://example.com/big").mock(
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
    # Contract: request was a simple GET
    req = route.calls[0].request
    assert req.method == "GET"
    assert str(req.url) == "https://example.com/big"


@pytest.mark.asyncio
@respx.mock
async def test_request_4xx_returned_not_error(server):
    route = respx.get("https://api.example.com/missing").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )
    result = await server.call_tool("http_request", {
        "method": "GET", "url": "https://api.example.com/missing",
    })
    data = _get_result_data(result)
    assert data["status_code"] == 404
    # Contract: request was a simple GET
    req = route.calls[0].request
    assert req.method == "GET"
    assert str(req.url) == "https://api.example.com/missing"


# --- http_request_form ---


@pytest.mark.asyncio
@respx.mock
async def test_form_post(server):
    route = respx.post("https://oauth.example.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "abc"})
    )
    result = await server.call_tool("http_request_form", {
        "url": "https://oauth.example.com/token",
        "data": {"grant_type": "client_credentials", "client_id": "xxx"},
    })
    data = _get_result_data(result)
    assert data["status_code"] == 200
    # Contract: form-encoded body sent correctly
    req = route.calls[0].request
    form_data = dict(httpx.QueryParams(req.content.decode()))
    assert form_data["grant_type"] == "client_credentials"
    assert form_data["client_id"] == "xxx"
    assert "application/x-www-form-urlencoded" in req.headers["content-type"]


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
    route = respx.get("https://example.com/report.pdf").mock(
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
    # Contract: GET request to correct URL
    req = route.calls[0].request
    assert req.method == "GET"
    assert str(req.url) == "https://example.com/report.pdf"


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
    route = respx.get("https://example.com/missing").mock(
        return_value=httpx.Response(404, text="Not Found")
    )
    save_path = str(tmp_path / "file.txt")
    result = await server.call_tool("http_download", {
        "url": "https://example.com/missing",
        "save_path": save_path,
    })
    data = _get_result_data(result)
    assert data["status_code"] == 404
    # Contract: GET request to correct URL
    req = route.calls[0].request
    assert req.method == "GET"
    assert str(req.url) == "https://example.com/missing"


# --- http_upload ---


@pytest.mark.asyncio
@respx.mock
async def test_upload_file(server, tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello upload")
    route = respx.post("https://api.example.com/upload").mock(
        return_value=httpx.Response(200, json={"id": "f123"})
    )
    result = await server.call_tool("http_upload", {
        "url": "https://api.example.com/upload",
        "file_path": str(test_file),
    })
    data = _get_result_data(result)
    assert data["status_code"] == 200
    # Contract: multipart upload with correct field name and file content
    req = route.calls[0].request
    assert req.method == "POST"
    assert "multipart/form-data" in req.headers["content-type"]
    body_str = req.content.decode("utf-8", errors="replace")
    assert "Hello upload" in body_str
    assert 'name="file"' in body_str
    assert 'filename="test.txt"' in body_str


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
    route = respx.post("https://api.example.com/process").mock(
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
    # Contract: multipart upload with custom field name and extra fields
    req = route.calls[0].request
    assert "multipart/form-data" in req.headers["content-type"]
    body_str = req.content.decode("utf-8", errors="replace")
    assert 'name="image"' in body_str
    assert 'filename="img.jpg"' in body_str
    assert 'name="size"' in body_str
    assert "auto" in body_str
