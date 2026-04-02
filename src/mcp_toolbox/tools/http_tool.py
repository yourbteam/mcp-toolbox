"""Generic HTTP tools — call any REST API without a dedicated integration."""

import json
import logging
import mimetypes
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


def _parse_response(response: httpx.Response, max_size: int) -> dict:
    """Parse an httpx response into a serializable dict."""
    elapsed_ms = int(response.elapsed.total_seconds() * 1000)
    resp_headers = dict(response.headers)
    content_type = response.headers.get("content-type", "")
    truncated = False

    if "application/json" in content_type:
        try:
            body = response.json()
            body_str = json.dumps(body)
            if len(body_str) > max_size:
                body = body_str[:max_size]
                truncated = True
        except Exception:
            body = response.text[:max_size]
            truncated = len(response.text) > max_size
    elif content_type.startswith("text/") or "xml" in content_type:
        body = response.text[:max_size]
        truncated = len(response.text) > max_size
    else:
        body = (
            f"[Binary content: {len(response.content)} bytes, "
            f"Content-Type: {content_type}]"
        )

    return {
        "status_code": response.status_code,
        "headers": resp_headers,
        "body": body,
        "elapsed_ms": elapsed_ms,
        "truncated": truncated,
    }


def register_tools(mcp: FastMCP) -> None:
    """Register generic HTTP tools."""

    @mcp.tool()
    async def http_request(
        method: str,
        url: str,
        headers: dict | None = None,
        json_body: dict | list | None = None,
        text_body: str | None = None,
        params: dict | None = None,
        timeout: float = 30.0,
        auth_header: str | None = None,
        max_response_size: int = 50000,
        follow_redirects: bool = True,
    ) -> str:
        """Make an HTTP request to any URL. The generic escape hatch for REST APIs.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS)
            url: Full URL including scheme
            headers: Custom request headers
            json_body: JSON request body (mutually exclusive with text_body)
            text_body: Raw text request body (mutually exclusive with json_body)
            params: URL query parameters
            timeout: Request timeout in seconds (max 300)
            auth_header: Authorization header value (e.g., Bearer token)
            max_response_size: Max response body chars to return (default 50000)
            follow_redirects: Follow HTTP redirects (default true)
        """
        method = method.upper()
        valid = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
        if method not in valid:
            raise ToolError(f"Invalid HTTP method: {method}. Must be one of {valid}")
        if not url.startswith(("http://", "https://")):
            raise ToolError("URL must start with http:// or https://")
        if json_body is not None and text_body is not None:
            raise ToolError("Cannot provide both json_body and text_body")

        timeout = max(1.0, min(timeout, 300.0))
        req_headers = dict(headers or {})
        if auth_header:
            req_headers["Authorization"] = auth_header

        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=follow_redirects
            ) as client:
                response = await client.request(
                    method, url,
                    headers=req_headers,
                    json=json_body,
                    content=text_body,
                    params=params,
                )
        except httpx.TimeoutException:
            raise ToolError(f"Request timed out after {timeout}s") from None
        except httpx.HTTPError as e:
            raise ToolError(f"HTTP request failed: {e}") from e

        return json.dumps(_parse_response(response, max_response_size))

    @mcp.tool()
    async def http_request_form(
        url: str,
        data: dict,
        headers: dict | None = None,
        auth_header: str | None = None,
        timeout: float = 30.0,
        max_response_size: int = 50000,
        follow_redirects: bool = True,
    ) -> str:
        """POST with form-encoded data (application/x-www-form-urlencoded).

        Args:
            url: Full URL including scheme
            data: Form fields as key-value pairs
            headers: Custom request headers
            auth_header: Authorization header value
            timeout: Request timeout in seconds (max 300)
            max_response_size: Max response body chars to return
            follow_redirects: Follow HTTP redirects
        """
        if not url.startswith(("http://", "https://")):
            raise ToolError("URL must start with http:// or https://")
        if not data:
            raise ToolError("data must be a non-empty dict of form fields")

        timeout = max(1.0, min(timeout, 300.0))
        req_headers = dict(headers or {})
        if auth_header:
            req_headers["Authorization"] = auth_header

        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=follow_redirects
            ) as client:
                response = await client.post(url, data=data, headers=req_headers)
        except httpx.TimeoutException:
            raise ToolError(f"Request timed out after {timeout}s") from None
        except httpx.HTTPError as e:
            raise ToolError(f"HTTP request failed: {e}") from e

        return json.dumps(_parse_response(response, max_response_size))

    @mcp.tool()
    async def http_download(
        url: str,
        save_path: str,
        headers: dict | None = None,
        auth_header: str | None = None,
        timeout: float = 60.0,
        max_file_size: int = 104857600,
        follow_redirects: bool = True,
    ) -> str:
        """Download a file from a URL to a local path (streamed).

        Args:
            url: URL of the file to download
            save_path: Local path to save the file (parent dir must exist)
            headers: Custom request headers
            auth_header: Authorization header value
            timeout: Request timeout in seconds (max 600)
            max_file_size: Max download size in bytes (default 100MB, max 500MB)
            follow_redirects: Follow HTTP redirects
        """
        if not url.startswith(("http://", "https://")):
            raise ToolError("URL must start with http:// or https://")

        save = Path(save_path).resolve()
        if not save.parent.exists():
            raise ToolError(f"Parent directory does not exist: {save.parent}")

        timeout = max(1.0, min(timeout, 600.0))
        max_file_size = min(max_file_size, 500 * 1024 * 1024)

        req_headers = dict(headers or {})
        if auth_header:
            req_headers["Authorization"] = auth_header

        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=follow_redirects
            ) as client:
                async with client.stream("GET", url, headers=req_headers) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode(errors="replace")[:5000]
                        return json.dumps({
                            "status_code": response.status_code, "error": body,
                        })

                    total = 0
                    with open(save, "wb") as f:
                        async for chunk in response.aiter_bytes(8192):
                            total += len(chunk)
                            if total > max_file_size:
                                raise ToolError(
                                    f"Download exceeds max_file_size "
                                    f"({max_file_size} bytes). Aborted."
                                )
                            f.write(chunk)

                    content_type = response.headers.get("content-type", "unknown")
                    elapsed_ms = int(response.elapsed.total_seconds() * 1000)
        except httpx.TimeoutException:
            raise ToolError(f"Download timed out after {timeout}s") from None
        except httpx.HTTPError as e:
            raise ToolError(f"Download failed: {e}") from e

        return json.dumps({
            "status_code": response.status_code,
            "save_path": str(save),
            "file_size_bytes": total,
            "content_type": content_type,
            "elapsed_ms": elapsed_ms,
        })

    @mcp.tool()
    async def http_upload(
        url: str,
        file_path: str,
        file_field_name: str = "file",
        mime_type: str | None = None,
        extra_fields: dict | None = None,
        headers: dict | None = None,
        auth_header: str | None = None,
        timeout: float = 60.0,
        max_response_size: int = 50000,
        follow_redirects: bool = True,
    ) -> str:
        """Upload a file via multipart/form-data POST.

        Args:
            url: Upload endpoint URL
            file_path: Local path of the file to upload
            file_field_name: Form field name for the file (default "file")
            mime_type: MIME type (auto-detected if not provided)
            extra_fields: Additional form fields
            headers: Custom request headers
            auth_header: Authorization header value
            timeout: Request timeout in seconds (max 600)
            max_response_size: Max response body chars to return
            follow_redirects: Follow HTTP redirects
        """
        if not url.startswith(("http://", "https://")):
            raise ToolError("URL must start with http:// or https://")

        fp = Path(file_path).resolve()
        if not fp.is_file():
            raise ToolError(f"File not found or not a file: {fp}")

        file_size = fp.stat().st_size
        if file_size > 100 * 1024 * 1024:
            raise ToolError(f"File too large: {file_size} bytes (max 100MB)")

        if mime_type is None:
            mime_type = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"

        timeout = max(1.0, min(timeout, 600.0))
        req_headers = dict(headers or {})
        if auth_header:
            req_headers["Authorization"] = auth_header

        try:
            with open(fp, "rb") as f:
                files = {file_field_name: (fp.name, f, mime_type)}
                async with httpx.AsyncClient(
                    timeout=timeout, follow_redirects=follow_redirects
                ) as client:
                    response = await client.post(
                        url, files=files,
                        data=extra_fields or {},
                        headers=req_headers,
                    )
        except httpx.TimeoutException:
            raise ToolError(f"Upload timed out after {timeout}s") from None
        except httpx.HTTPError as e:
            raise ToolError(f"Upload failed: {e}") from e

        return json.dumps(_parse_response(response, max_response_size))
