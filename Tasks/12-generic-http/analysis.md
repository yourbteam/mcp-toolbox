# Task 12: Generic HTTP Tools - Analysis & Requirements

## Objective
Add a set of generic HTTP tools to mcp-toolbox that allow the MCP agent to call **any REST API** without needing a dedicated integration. This is the "escape hatch" — when no purpose-built tool exists, the agent can fall back to raw HTTP requests.

**Scope:** 4 tools covering standard requests, form-encoded POSTs, file downloads, and file uploads.

**Current toolbox total:** 224 tools. After this task: **228 tools**.

---

## Architecture Decisions

### A1: No Singleton Client — Fresh Client Per Request
Unlike other integrations (ClickUp, etc.) that use a shared `httpx.AsyncClient` with a fixed `base_url` and `Authorization` header, the generic HTTP tools hit **arbitrary URLs** with **arbitrary auth**. Each request creates a fresh `httpx.AsyncClient`, uses it for one request, then closes it. This avoids connection pool contamination across unrelated hosts.

```python
async with httpx.AsyncClient(timeout=timeout) as client:
    response = await client.request(method, url, ...)
```

### A2: No Configuration Required
These tools require **zero environment variables**. Everything — URL, headers, auth, body — is provided per-request by the MCP client. The tools always register and are always available.

### A3: Security Model
These tools can access **any URL** the host machine can reach, including localhost and internal networks. This is by design — the MCP client (LLM agent) controls what gets called. Security is enforced at the MCP client layer (user approval, tool call confirmation), not at the tool layer. The tool description will include a security note so the LLM is aware.

### A4: Response Truncation
HTTP responses can be arbitrarily large. To prevent blowing up MCP message sizes:
- Text/JSON responses are truncated to **50,000 characters** by default, with a `max_response_size` parameter to override.
- Binary responses (non-text content types) return only status code, headers, and content length — not the body.
- `http_download` writes to disk instead of returning body content.

### A5: Tool Module Structure
All 4 tools go in `src/mcp_toolbox/tools/http_tool.py` following the existing `register_tools(mcp)` convention. No config imports needed.

### A6: Error Handling
- Network errors (`httpx.HTTPError`) are caught and converted to `ToolError` with a clear message.
- Timeout errors (`httpx.TimeoutException`) get a specific message mentioning the timeout value.
- No HTTP status code is treated as an error by the tool — all responses (including 4xx/5xx) are returned to the agent. The agent decides what to do with error responses.
- Connection refused, DNS failures, TLS errors — all surfaced as `ToolError` with the exception message.

### A7: Response Format
All tools return a JSON-serialized string with consistent structure:
```python
# Success (any HTTP status — even 4xx/5xx)
{
    "status_code": 200,
    "headers": {"content-type": "application/json", ...},
    "body": "..." or {...},          # parsed JSON if content-type is JSON, else string
    "elapsed_ms": 142,
    "truncated": false
}

# Network/tool error (raised as ToolError, not returned)
ToolError("HTTP request failed: connection refused")
```

---

## Tool Specifications

### Tool 1: `http_request`

**Description:** Make a configurable HTTP request to any URL. This is the generic escape hatch for calling REST APIs that don't have a dedicated tool integration. Supports all standard HTTP methods, custom headers, JSON or text bodies, query parameters, and authentication. **Security note:** this tool can access any URL reachable from the host machine, including localhost and internal networks.

**Parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `method` | str | Yes | — | HTTP method: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`, `OPTIONS` |
| `url` | str | Yes | — | Full URL including scheme (e.g., `https://api.example.com/v1/users`) |
| `headers` | dict[str, str] | No | `None` | Custom request headers (e.g., `{"X-Custom": "value"}`) |
| `json_body` | dict or list | No | `None` | JSON request body. Sets `Content-Type: application/json` automatically. Mutually exclusive with `text_body`. |
| `text_body` | str | No | `None` | Raw text request body. Use for XML, plain text, or other non-JSON payloads. Mutually exclusive with `json_body`. |
| `params` | dict[str, str] | No | `None` | URL query parameters (appended to URL as `?key=value&...`) |
| `timeout` | float | No | `30.0` | Request timeout in seconds (max 300) |
| `auth_header` | str | No | `None` | Value for the `Authorization` header (e.g., `"Bearer eyJ..."` or `"Basic dXNlcjpwYXNz"` or `"token ghp_..."`) |
| `max_response_size` | int | No | `50000` | Maximum response body characters to return. Larger responses are truncated. |
| `follow_redirects` | bool | No | `true` | Whether to follow HTTP redirects (3xx responses) |

**Validation Rules:**
- `method` must be one of the 7 allowed values (case-insensitive, normalized to uppercase).
- `url` must start with `http://` or `https://`.
- `json_body` and `text_body` are mutually exclusive — providing both raises `ToolError`.
- `timeout` is clamped to the range `[1.0, 300.0]`.
- If `auth_header` is provided and `headers` also contains an `Authorization` key, `auth_header` takes precedence (overwrites).

**Returns:** JSON string with `status_code`, `headers` (dict), `body` (parsed JSON object if response is JSON, else string), `elapsed_ms` (int), and `truncated` (bool).

**Implementation Pattern:**
```python
@mcp.tool()
async def http_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json_body: dict | list | None = None,
    text_body: str | None = None,
    params: dict[str, str] | None = None,
    timeout: float = 30.0,
    auth_header: str | None = None,
    max_response_size: int = 50000,
    follow_redirects: bool = True,
) -> str:
    # Validate method
    method = method.upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        raise ToolError(f"Invalid HTTP method: {method}")

    # Validate URL
    if not url.startswith(("http://", "https://")):
        raise ToolError("URL must start with http:// or https://")

    # Validate body exclusivity
    if json_body is not None and text_body is not None:
        raise ToolError("Cannot provide both json_body and text_body")

    # Clamp timeout
    timeout = max(1.0, min(timeout, 300.0))

    # Build headers
    req_headers = dict(headers or {})
    if auth_header:
        req_headers["Authorization"] = auth_header

    # Make request
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=follow_redirects
        ) as client:
            response = await client.request(
                method,
                url,
                headers=req_headers,
                json=json_body,
                content=text_body,
                params=params,
            )
    except httpx.TimeoutException:
        raise ToolError(f"Request timed out after {timeout}s")
    except httpx.HTTPError as e:
        raise ToolError(f"HTTP request failed: {e}")

    # Build response
    elapsed_ms = int(response.elapsed.total_seconds() * 1000)
    resp_headers = dict(response.headers)

    # Parse body
    content_type = response.headers.get("content-type", "")
    truncated = False
    if "application/json" in content_type:
        try:
            body = response.json()
            # Check serialized size for truncation
            body_str = json.dumps(body)
            if len(body_str) > max_response_size:
                body = body_str[:max_response_size]
                truncated = True
        except Exception:
            body = response.text[:max_response_size]
            truncated = len(response.text) > max_response_size
    elif content_type.startswith("text/") or "xml" in content_type:
        body = response.text[:max_response_size]
        truncated = len(response.text) > max_response_size
    else:
        body = f"[Binary content: {len(response.content)} bytes, Content-Type: {content_type}]"

    return json.dumps({
        "status_code": response.status_code,
        "headers": resp_headers,
        "body": body,
        "elapsed_ms": elapsed_ms,
        "truncated": truncated,
    })
```

---

### Tool 2: `http_request_form`

**Description:** Send an HTTP POST request with form-encoded data (`application/x-www-form-urlencoded`). Use this for APIs that expect HTML form submissions, OAuth token endpoints, or other form-encoded payloads. **Security note:** this tool can access any URL reachable from the host machine.

**Parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | str | Yes | — | Full URL including scheme |
| `data` | dict[str, str] | Yes | — | Form fields as key-value pairs. Values are URL-encoded automatically. |
| `headers` | dict[str, str] | No | `None` | Custom request headers (in addition to auto-set `Content-Type`) |
| `auth_header` | str | No | `None` | Value for the `Authorization` header |
| `timeout` | float | No | `30.0` | Request timeout in seconds (max 300) |
| `max_response_size` | int | No | `50000` | Maximum response body characters to return |
| `follow_redirects` | bool | No | `true` | Whether to follow HTTP redirects |

**Validation Rules:**
- `url` must start with `http://` or `https://`.
- `data` must be a non-empty dict.
- `timeout` is clamped to `[1.0, 300.0]`.

**Returns:** Same format as `http_request` — JSON string with `status_code`, `headers`, `body`, `elapsed_ms`, `truncated`.

**Implementation Pattern:**
```python
@mcp.tool()
async def http_request_form(
    url: str,
    data: dict[str, str],
    headers: dict[str, str] | None = None,
    auth_header: str | None = None,
    timeout: float = 30.0,
    max_response_size: int = 50000,
    follow_redirects: bool = True,
) -> str:
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
        raise ToolError(f"Request timed out after {timeout}s")
    except httpx.HTTPError as e:
        raise ToolError(f"HTTP request failed: {e}")

    # ... same response parsing as http_request ...
```

---

### Tool 3: `http_download`

**Description:** Download a file from a URL and save it to a local file path. Streams the response to avoid loading large files into memory. Returns metadata about the download (status code, file size, content type) but not the file contents. **Security note:** this tool can write files to the local filesystem and access any URL reachable from the host machine.

**Parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | str | Yes | — | URL of the file to download |
| `save_path` | str | Yes | — | Local filesystem path to save the downloaded file (absolute or relative). Parent directory must exist. |
| `headers` | dict[str, str] | No | `None` | Custom request headers (e.g., `Accept`, `Range` for partial downloads) |
| `auth_header` | str | No | `None` | Value for the `Authorization` header |
| `timeout` | float | No | `60.0` | Request timeout in seconds (max 600 — longer default for large files) |
| `max_file_size` | int | No | `104857600` | Maximum download size in bytes (default 100MB). Download aborts if exceeded. |
| `follow_redirects` | bool | No | `true` | Whether to follow HTTP redirects |

**Validation Rules:**
- `url` must start with `http://` or `https://`.
- `save_path` parent directory must exist (checked before downloading).
- `timeout` is clamped to `[1.0, 600.0]`.
- `max_file_size` must be positive and at most 500MB (524,288,000 bytes).

**Returns:** JSON string with:
```json
{
    "status_code": 200,
    "save_path": "/absolute/path/to/file.pdf",
    "file_size_bytes": 1048576,
    "content_type": "application/pdf",
    "elapsed_ms": 2340
}
```

**Implementation Pattern:**
```python
@mcp.tool()
async def http_download(
    url: str,
    save_path: str,
    headers: dict[str, str] | None = None,
    auth_header: str | None = None,
    timeout: float = 60.0,
    max_file_size: int = 100 * 1024 * 1024,
    follow_redirects: bool = True,
) -> str:
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
                        "status_code": response.status_code,
                        "error": body,
                    })

                total = 0
                with open(save, "wb") as f:
                    async for chunk in response.aiter_bytes(8192):
                        total += len(chunk)
                        if total > max_file_size:
                            raise ToolError(
                                f"Download exceeds max_file_size ({max_file_size} bytes). Aborted."
                            )
                        f.write(chunk)
    except httpx.TimeoutException:
        raise ToolError(f"Download timed out after {timeout}s")
    except httpx.HTTPError as e:
        raise ToolError(f"Download failed: {e}")

    content_type = response.headers.get("content-type", "unknown")
    elapsed_ms = int(response.elapsed.total_seconds() * 1000)

    return json.dumps({
        "status_code": response.status_code,
        "save_path": str(save),
        "file_size_bytes": total,
        "content_type": content_type,
        "elapsed_ms": elapsed_ms,
    })
```

---

### Tool 4: `http_upload`

**Description:** Upload a file via HTTP multipart/form-data POST. Use this for APIs that accept file uploads (e.g., image processing services, document converters, file storage APIs). Can include additional form fields alongside the file. **Security note:** this tool can read files from the local filesystem and access any URL reachable from the host machine.

**Parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `url` | str | Yes | — | Upload endpoint URL |
| `file_path` | str | Yes | — | Local path of the file to upload. Must exist and be readable. |
| `file_field_name` | str | No | `"file"` | The form field name for the file (some APIs expect `"upload"`, `"attachment"`, etc.) |
| `mime_type` | str | No | `None` | MIME type of the file (e.g., `"image/png"`). Auto-detected from extension if not provided. |
| `extra_fields` | dict[str, str] | No | `None` | Additional form fields to include in the multipart request (e.g., `{"description": "My file"}`) |
| `headers` | dict[str, str] | No | `None` | Custom request headers (do NOT set `Content-Type` — httpx sets the multipart boundary automatically) |
| `auth_header` | str | No | `None` | Value for the `Authorization` header |
| `timeout` | float | No | `60.0` | Request timeout in seconds (max 600) |
| `max_response_size` | int | No | `50000` | Maximum response body characters to return |
| `follow_redirects` | bool | No | `true` | Whether to follow HTTP redirects |

**Validation Rules:**
- `url` must start with `http://` or `https://`.
- `file_path` must exist and be a file (not a directory).
- File size must not exceed 100MB.
- `timeout` is clamped to `[1.0, 600.0]`.

**Returns:** Same format as `http_request` — JSON string with `status_code`, `headers`, `body`, `elapsed_ms`, `truncated`.

**Implementation Pattern:**
```python
@mcp.tool()
async def http_upload(
    url: str,
    file_path: str,
    file_field_name: str = "file",
    mime_type: str | None = None,
    extra_fields: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    auth_header: str | None = None,
    timeout: float = 60.0,
    max_response_size: int = 50000,
    follow_redirects: bool = True,
) -> str:
    import mimetypes

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
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow_redirects) as client:
                response = await client.post(
                    url,
                    files=files,
                    data=extra_fields or {},
                    headers=req_headers,
                )
    except httpx.TimeoutException:
        raise ToolError(f"Upload timed out after {timeout}s")
    except httpx.HTTPError as e:
        raise ToolError(f"Upload failed: {e}")

    # ... same response parsing as http_request ...
```

---

## Testing Strategy

### Approach
Use `respx` (httpx mock library, already compatible) or `unittest.mock.patch` to mock HTTP responses. No real network calls in unit tests.

### Mock Pattern
```python
import respx
from httpx import Response

@respx.mock
async def test_http_request_get():
    respx.get("https://api.example.com/users").mock(
        return_value=Response(200, json={"users": []})
    )
    result = await server.call_tool("http_request", {
        "method": "GET",
        "url": "https://api.example.com/users",
    })
    data = json.loads(result)
    assert data["status_code"] == 200
    assert data["body"] == {"users": []}
```

### Test Coverage

**For `http_request`:**
1. Happy path — GET with JSON response
2. Happy path — POST with json_body
3. Happy path — PUT with text_body
4. Validation — invalid method raises ToolError
5. Validation — invalid URL raises ToolError
6. Validation — both json_body and text_body raises ToolError
7. Auth — auth_header sets Authorization
8. Auth — auth_header overrides headers["Authorization"]
9. Timeout — httpx.TimeoutException raised, clear error message
10. Network error — connection refused, DNS failure
11. Truncation — large response is truncated and truncated=true
12. Binary response — non-text content returns placeholder
13. Query params — params dict appended to URL
14. Redirects — follow_redirects=false stops on 301

**For `http_request_form`:**
1. Happy path — form-encoded POST
2. Validation — empty data dict raises ToolError
3. OAuth token endpoint pattern — real-world usage test

**For `http_download`:**
1. Happy path — download small file
2. Max file size — abort on oversized download
3. Parent directory missing — ToolError
4. HTTP error response — returns error body, does not create file
5. Timeout on large download

**For `http_upload`:**
1. Happy path — upload file with response
2. File not found — ToolError
3. File too large — ToolError
4. Custom field name and extra fields
5. MIME type auto-detection

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/tools/http_tool.py` | **New** | All 4 generic HTTP tools |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Import and register `http_tool` |
| `tests/test_http_tool.py` | **New** | Tests for all 4 tools |

**No changes needed to:**
- `pyproject.toml` — httpx is already a dependency
- `config.py` — no configuration required
- `.env.example` — no environment variables needed

---

## Dependencies

| Package | Purpose | Version | Status |
|---------|---------|---------|--------|
| `httpx` | Async HTTP client | Already in deps | No change |
| `respx` | httpx mocking for tests | `>=0.21.0` | Already in dev dependencies — no change needed |

No new runtime dependencies required.

---

## Usage Examples

### Example 1: Call a REST API with Bearer token
```
Tool: http_request
Args: {
    "method": "GET",
    "url": "https://api.github.com/user/repos",
    "auth_header": "Bearer ghp_xxxxxxxxxxxx",
    "params": {"per_page": "5", "sort": "updated"}
}
```

### Example 2: POST JSON to a webhook
```
Tool: http_request
Args: {
    "method": "POST",
    "url": "https://hooks.slack.com/services/T00/B00/xxx",
    "json_body": {"text": "Hello from MCP!"}
}
```

### Example 3: OAuth token exchange
```
Tool: http_request_form
Args: {
    "url": "https://oauth2.googleapis.com/token",
    "data": {
        "grant_type": "authorization_code",
        "code": "4/0AX4...",
        "client_id": "xxx.apps.googleusercontent.com",
        "client_secret": "GOCSPX-xxx",
        "redirect_uri": "http://localhost:8080/callback"
    }
}
```

### Example 4: Download a report
```
Tool: http_download
Args: {
    "url": "https://api.example.com/reports/monthly.pdf",
    "save_path": "/tmp/monthly-report.pdf",
    "auth_header": "Bearer eyJ..."
}
```

### Example 5: Upload an image for processing
```
Tool: http_upload
Args: {
    "url": "https://api.remove.bg/v1.0/removebg",
    "file_path": "/tmp/photo.jpg",
    "file_field_name": "image_file",
    "extra_fields": {"size": "auto"},
    "headers": {"X-Api-Key": "xxxxx"}
}
```

---

## Success Criteria

1. All 4 tools register and are discoverable via MCP Inspector
2. `http_request` can successfully call a public REST API (e.g., `https://httpbin.org/get`)
3. `http_request_form` can POST form data (e.g., `https://httpbin.org/post`)
4. `http_download` can download a file and save to disk
5. `http_upload` can upload a file via multipart POST
6. All tools handle timeouts, network errors, and large responses gracefully
7. All new tests pass and full regression suite remains green
8. **Toolbox total reaches 228** (224 existing + 4 new)

---

## Tool Summary (4 tools)

| # | Tool | Purpose |
|---|------|---------|
| 1 | `http_request` | General-purpose HTTP request (any method, any URL, JSON/text body) |
| 2 | `http_request_form` | POST with `application/x-www-form-urlencoded` body |
| 3 | `http_download` | Download a file from URL to local path (streamed) |
| 4 | `http_upload` | Upload a file via `multipart/form-data` POST |
