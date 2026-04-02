# Task 08: AWS SSM Parameter Store - Implementation Plan

## Overview
Implement 13 AWS Systems Manager Parameter Store tools using `boto3` with `asyncio.to_thread()` for async wrapping. Native boto3 credential chain — no explicit credential passing.

**Final state:** 196 tools total (183 existing + 13 new).

---

## Step 1: Dependencies & Configuration

### 1a. Add `boto3` to `pyproject.toml`
```toml
dependencies = [
    ...
    "boto3>=1.34.0",
]
```

### 1b. Add AWS config to `config.py`
Append after Key Vault variables:
```python
# AWS (optional — boto3 reads credentials from env/config/IAM automatically)
AWS_ACCESS_KEY_ID: str | None = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY: str | None = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION: str | None = os.getenv("AWS_DEFAULT_REGION")
```

### 1c. Update `.env.example`
```env
# AWS Parameter Store Integration (boto3 auto-resolves from env/config/IAM)
# AWS_ACCESS_KEY_ID=AKIA...
# AWS_SECRET_ACCESS_KEY=your-secret-key
# AWS_DEFAULT_REGION=us-east-1
```

### 1d. Add pyright exclusion
Add `"src/mcp_toolbox/tools/aws_ssm_tool.py"` to pyright exclude list.

---

## Step 2: Tool Module Foundation

Create `src/mcp_toolbox/tools/aws_ssm_tool.py`:

```python
"""AWS Systems Manager Parameter Store integration."""

import asyncio
import json
import logging
from datetime import datetime

import boto3
from botocore.exceptions import ClientError
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import AWS_ACCESS_KEY_ID, AWS_DEFAULT_REGION, AWS_SECRET_ACCESS_KEY

logger = logging.getLogger(__name__)

_ssm_client = None


def _get_client():
    """Get or create the boto3 SSM client. Uses native credential chain."""
    global _ssm_client
    if _ssm_client is None:
        kwargs = {}
        if AWS_ACCESS_KEY_ID:
            kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
        if AWS_SECRET_ACCESS_KEY:
            kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
        if AWS_DEFAULT_REGION:
            kwargs["region_name"] = AWS_DEFAULT_REGION
        try:
            _ssm_client = boto3.client("ssm", **kwargs)
        except Exception as e:
            raise ToolError(f"Failed to create AWS SSM client: {e}") from e
    return _ssm_client


def _serialize(obj):
    """JSON-serialize boto3 responses (handles datetime objects)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    return obj


def _success(status_code: int, **kwargs) -> str:
    return json.dumps({"status": "success", "status_code": status_code, **_serialize(kwargs)})


async def _call(method, **kwargs):
    """Call a boto3 SSM method via asyncio.to_thread with error handling."""
    client = _get_client()
    fn = getattr(client, method)
    try:
        return await asyncio.to_thread(fn, **kwargs)
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        raise ToolError(f"AWS SSM error ({error_code}): {error_msg}") from e
    except Exception as e:
        raise ToolError(f"AWS SSM request failed: {e}") from e


def register_tools(mcp: FastMCP) -> None:
    """Register all AWS SSM Parameter Store tools."""

    logger.info("Registering AWS SSM Parameter Store tools")

    # --- Parameter CRUD (Step 3) ---
    # --- History & Versioning (Step 4) ---
    # --- Tagging (Step 5) ---
```

Key design decisions:
- **`_call(method, **kwargs)`** — generic helper that calls any boto3 SSM method by name via `asyncio.to_thread()`. Handles `ClientError` uniformly.
- **`_serialize()`** — recursively converts `datetime` objects to ISO strings for JSON compatibility
- **`_success()`** — runs `_serialize` on all kwargs before JSON encoding
- **No explicit credential passing** unless config vars are set — preserves boto3 native chain

---

## Step 3: Parameter CRUD (7 tools)

```python
    @mcp.tool()
    async def aws_ssm_put_parameter(
        name: str,
        value: str,
        type: str = "String",
        description: str | None = None,
        overwrite: bool = True,
    ) -> str:
        """Create or update an AWS SSM parameter.

        Args:
            name: Parameter name (supports / hierarchy, e.g. /app/prod/db-pass)
            value: Parameter value
            type: String, StringList, or SecureString (default String)
            description: Parameter description
            overwrite: Overwrite if exists (default true)
        """
        kwargs: dict = {
            "Name": name, "Value": value, "Type": type, "Overwrite": overwrite,
        }
        if description is not None:
            kwargs["Description"] = description
        result = await _call("put_parameter", **kwargs)
        return _success(200, version=result.get("Version"), tier=result.get("Tier"))

    @mcp.tool()
    async def aws_ssm_get_parameter(name: str) -> str:
        """Get an AWS SSM parameter value (decrypts SecureString).

        Args:
            name: Parameter name
        """
        result = await _call("get_parameter", Name=name, WithDecryption=True)
        param = result.get("Parameter", {})
        return _success(200, data=param)

    @mcp.tool()
    async def aws_ssm_get_parameters(names: list[str]) -> str:
        """Get multiple AWS SSM parameters by name (max 10).

        Args:
            names: Parameter names (max 10)
        """
        result = await _call("get_parameters", Names=names, WithDecryption=True)
        return _success(
            200,
            data=result.get("Parameters", []),
            invalid=result.get("InvalidParameters", []),
        )

    @mcp.tool()
    async def aws_ssm_get_parameters_by_path(
        path: str,
        recursive: bool = True,
        max_results: int = 10,
    ) -> str:
        """Get AWS SSM parameters under a hierarchy path.

        Args:
            path: Path prefix (e.g., /myapp/prod/)
            recursive: Include sub-paths (default true)
            max_results: Max results (default 10)
        """
        result = await _call(
            "get_parameters_by_path",
            Path=path, Recursive=recursive,
            WithDecryption=True, MaxResults=max_results,
        )
        params = result.get("Parameters", [])
        return _success(200, data=params, count=len(params))

    @mcp.tool()
    async def aws_ssm_describe_parameters(
        max_results: int = 50,
        name_prefix: str | None = None,
    ) -> str:
        """List AWS SSM parameters (metadata only, no values).

        Args:
            max_results: Max results (default 50)
            name_prefix: Filter by name prefix
        """
        kwargs: dict = {"MaxResults": max_results}
        if name_prefix:
            kwargs["ParameterFilters"] = [
                {"Key": "Name", "Option": "BeginsWith", "Values": [name_prefix]}
            ]
        result = await _call("describe_parameters", **kwargs)
        params = result.get("Parameters", [])
        return _success(200, data=params, count=len(params))

    @mcp.tool()
    async def aws_ssm_delete_parameter(name: str) -> str:
        """Delete an AWS SSM parameter.

        Args:
            name: Parameter name
        """
        await _call("delete_parameter", Name=name)
        return _success(200, deleted_parameter=name)

    @mcp.tool()
    async def aws_ssm_delete_parameters(names: list[str]) -> str:
        """Delete multiple AWS SSM parameters (max 10).

        Args:
            names: Parameter names (max 10)
        """
        result = await _call("delete_parameters", Names=names)
        return _success(
            200,
            deleted=result.get("DeletedParameters", []),
            invalid=result.get("InvalidParameters", []),
        )
```

---

## Step 4: History & Versioning (3 tools)

```python
    @mcp.tool()
    async def aws_ssm_get_parameter_history(
        name: str,
        max_results: int = 50,
    ) -> str:
        """Get version history of an AWS SSM parameter.

        Args:
            name: Parameter name
            max_results: Max results (default 50)
        """
        result = await _call(
            "get_parameter_history",
            Name=name, WithDecryption=True, MaxResults=max_results,
        )
        params = result.get("Parameters", [])
        return _success(200, data=params, count=len(params))

    @mcp.tool()
    async def aws_ssm_label_parameter_version(
        name: str,
        version: int,
        labels: list[str],
    ) -> str:
        """Attach labels to a specific parameter version.

        Args:
            name: Parameter name
            version: Parameter version number
            labels: Labels to attach
        """
        result = await _call(
            "label_parameter_version",
            Name=name, ParameterVersion=version, Labels=labels,
        )
        return _success(
            200,
            invalid_labels=result.get("InvalidLabels", []),
            version=version,
        )

    @mcp.tool()
    async def aws_ssm_unlabel_parameter_version(
        name: str,
        version: int,
        labels: list[str],
    ) -> str:
        """Remove labels from a parameter version.

        Args:
            name: Parameter name
            version: Parameter version number
            labels: Labels to remove
        """
        result = await _call(
            "unlabel_parameter_version",
            Name=name, ParameterVersion=version, Labels=labels,
        )
        return _success(
            200,
            removed_labels=result.get("RemovedLabels", []),
            invalid_labels=result.get("InvalidLabels", []),
        )
```

---

## Step 5: Tagging (3 tools)

```python
    @mcp.tool()
    async def aws_ssm_add_tags(name: str, tags: list[dict]) -> str:
        """Add tags to an AWS SSM parameter.

        Args:
            name: Parameter name
            tags: Tags as [{"Key": "k", "Value": "v"}]
        """
        await _call(
            "add_tags_to_resource",
            ResourceType="Parameter", ResourceId=name, Tags=tags,
        )
        return _success(200, message="Tags added", parameter=name)

    @mcp.tool()
    async def aws_ssm_remove_tags(name: str, tag_keys: list[str]) -> str:
        """Remove tags from an AWS SSM parameter.

        Args:
            name: Parameter name
            tag_keys: Tag keys to remove
        """
        await _call(
            "remove_tags_from_resource",
            ResourceType="Parameter", ResourceId=name, TagKeys=tag_keys,
        )
        return _success(200, message="Tags removed", parameter=name)

    @mcp.tool()
    async def aws_ssm_list_tags(name: str) -> str:
        """List tags on an AWS SSM parameter.

        Args:
            name: Parameter name
        """
        result = await _call(
            "list_tags_for_resource",
            ResourceType="Parameter", ResourceId=name,
        )
        tags = result.get("TagList", [])
        return _success(200, data=tags, count=len(tags))
```

---

## Step 6: Registration

```python
from mcp_toolbox.tools import (
    aws_ssm_tool,
    clickup_tool,
    example_tool,
    keyvault_tool,
    o365_tool,
    sendgrid_tool,
    teams_tool,
)


def register_all_tools(mcp: FastMCP) -> None:
    example_tool.register_tools(mcp)
    sendgrid_tool.register_tools(mcp)
    clickup_tool.register_tools(mcp)
    o365_tool.register_tools(mcp)
    teams_tool.register_tools(mcp)
    keyvault_tool.register_tools(mcp)
    aws_ssm_tool.register_tools(mcp)
```

---

## Step 7: Tests

Create `tests/test_aws_ssm_tool.py`. Mock the boto3 client directly — no respx needed.

### Fixture

```python
"""Tests for AWS SSM Parameter Store tool integration."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.aws_ssm_tool import register_tools


def _get_result_data(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_client = MagicMock()
    with patch("mcp_toolbox.tools.aws_ssm_tool._ssm_client", mock_client):
        register_tools(mcp)
        yield mcp, mock_client
```

### Tests (13 tools + error tests)

```python
# --- Auth/Error ---

@pytest.mark.asyncio
async def test_client_error():
    mcp = FastMCP("test")
    mock_client = MagicMock()
    error_response = {"Error": {"Code": "AccessDeniedException", "Message": "Not authorized"}}
    mock_client.get_parameter.side_effect = ClientError(error_response, "GetParameter")
    with patch("mcp_toolbox.tools.aws_ssm_tool._ssm_client", mock_client):
        register_tools(mcp)
        with pytest.raises(Exception, match="AWS SSM error.*AccessDeniedException"):
            await mcp.call_tool("aws_ssm_get_parameter", {"name": "/test"})


# --- Parameter CRUD ---

@pytest.mark.asyncio
async def test_put_parameter(server):
    mcp, mock_client = server
    mock_client.put_parameter.return_value = {"Version": 1, "Tier": "Standard"}
    result = await mcp.call_tool("aws_ssm_put_parameter", {
        "name": "/app/key", "value": "secret",
    })
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["version"] == 1


@pytest.mark.asyncio
async def test_get_parameter(server):
    mcp, mock_client = server
    mock_client.get_parameter.return_value = {
        "Parameter": {
            "Name": "/app/key", "Type": "String", "Value": "secret",
            "Version": 1, "LastModifiedDate": datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
    }
    result = await mcp.call_tool("aws_ssm_get_parameter", {"name": "/app/key"})
    data = _get_result_data(result)
    assert data["status"] == "success"
    assert data["data"]["Value"] == "secret"


@pytest.mark.asyncio
async def test_get_parameters(server):
    mcp, mock_client = server
    mock_client.get_parameters.return_value = {
        "Parameters": [{"Name": "/a", "Value": "1"}],
        "InvalidParameters": ["/b"],
    }
    result = await mcp.call_tool("aws_ssm_get_parameters", {"names": ["/a", "/b"]})
    data = _get_result_data(result)
    assert len(data["data"]) == 1
    assert data["invalid"] == ["/b"]


@pytest.mark.asyncio
async def test_get_parameters_by_path(server):
    mcp, mock_client = server
    mock_client.get_parameters_by_path.return_value = {
        "Parameters": [{"Name": "/app/prod/key", "Value": "v"}],
    }
    result = await mcp.call_tool("aws_ssm_get_parameters_by_path", {"path": "/app/prod/"})
    data = _get_result_data(result)
    assert data["count"] == 1


@pytest.mark.asyncio
async def test_describe_parameters(server):
    mcp, mock_client = server
    mock_client.describe_parameters.return_value = {
        "Parameters": [{"Name": "/app/key", "Type": "String"}],
    }
    result = await mcp.call_tool("aws_ssm_describe_parameters", {})
    data = _get_result_data(result)
    assert data["count"] == 1


@pytest.mark.asyncio
async def test_delete_parameter(server):
    mcp, mock_client = server
    mock_client.delete_parameter.return_value = {}
    result = await mcp.call_tool("aws_ssm_delete_parameter", {"name": "/app/key"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
async def test_delete_parameters(server):
    mcp, mock_client = server
    mock_client.delete_parameters.return_value = {
        "DeletedParameters": ["/a"], "InvalidParameters": ["/b"],
    }
    result = await mcp.call_tool("aws_ssm_delete_parameters", {"names": ["/a", "/b"]})
    data = _get_result_data(result)
    assert data["deleted"] == ["/a"]


# --- History & Versioning ---

@pytest.mark.asyncio
async def test_get_parameter_history(server):
    mcp, mock_client = server
    mock_client.get_parameter_history.return_value = {
        "Parameters": [
            {"Name": "/app/key", "Version": 1, "Value": "old",
             "LastModifiedDate": datetime(2025, 1, 1, tzinfo=timezone.utc)},
        ],
    }
    result = await mcp.call_tool("aws_ssm_get_parameter_history", {"name": "/app/key"})
    data = _get_result_data(result)
    assert data["count"] == 1


@pytest.mark.asyncio
async def test_label_parameter_version(server):
    mcp, mock_client = server
    mock_client.label_parameter_version.return_value = {"InvalidLabels": []}
    result = await mcp.call_tool("aws_ssm_label_parameter_version", {
        "name": "/app/key", "version": 1, "labels": ["prod"],
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
async def test_unlabel_parameter_version(server):
    mcp, mock_client = server
    mock_client.unlabel_parameter_version.return_value = {
        "RemovedLabels": ["prod"], "InvalidLabels": [],
    }
    result = await mcp.call_tool("aws_ssm_unlabel_parameter_version", {
        "name": "/app/key", "version": 1, "labels": ["prod"],
    })
    data = _get_result_data(result)
    assert data["removed_labels"] == ["prod"]


# --- Tagging ---

@pytest.mark.asyncio
async def test_add_tags(server):
    mcp, mock_client = server
    mock_client.add_tags_to_resource.return_value = {}
    result = await mcp.call_tool("aws_ssm_add_tags", {
        "name": "/app/key", "tags": [{"Key": "env", "Value": "prod"}],
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
async def test_remove_tags(server):
    mcp, mock_client = server
    mock_client.remove_tags_from_resource.return_value = {}
    result = await mcp.call_tool("aws_ssm_remove_tags", {
        "name": "/app/key", "tag_keys": ["env"],
    })
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
async def test_list_tags(server):
    mcp, mock_client = server
    mock_client.list_tags_for_resource.return_value = {
        "TagList": [{"Key": "env", "Value": "prod"}],
    }
    result = await mcp.call_tool("aws_ssm_list_tags", {"name": "/app/key"})
    data = _get_result_data(result)
    assert data["count"] == 1
```

---

## Step 8: Update test_server.py

Add all 13 SSM tool names and update count to 196:

```python
        # AWS SSM tools (13)
        "aws_ssm_put_parameter", "aws_ssm_get_parameter",
        "aws_ssm_get_parameters", "aws_ssm_get_parameters_by_path",
        "aws_ssm_describe_parameters",
        "aws_ssm_delete_parameter", "aws_ssm_delete_parameters",
        "aws_ssm_get_parameter_history",
        "aws_ssm_label_parameter_version", "aws_ssm_unlabel_parameter_version",
        "aws_ssm_add_tags", "aws_ssm_remove_tags", "aws_ssm_list_tags",
```

Total assertion: `assert len(tools) == 196`

---

## Step 9: Documentation & Validation

### 9a. Update CLAUDE.md

### 9b. Run validation
```bash
uv sync --dev --all-extras
uv run pytest -v
uv run ruff check src/ tests/
uv run pyright src/
```

---

## Execution Order

| Order | Step | Tools | Depends On |
|-------|------|-------|------------|
| 1 | Dependencies & config | — | — |
| 2 | Foundation | helpers | Step 1 |
| 3 | Parameter CRUD | 7 | Step 2 |
| 4 | History & Versioning | 3 | Step 2 |
| 5 | Tagging | 3 | Step 2 |
| 6 | Registration | — | Steps 3-5 |
| 7 | Tests | 14 | Steps 3-6 |
| 8 | test_server.py | — | Steps 3-6 |
| 9 | Docs & validation | — | Steps 1-8 |

Steps 3-5 are independent.

---

## Risk Notes

- **boto3 credential chain:** If no credentials are configured anywhere (no env vars, no `~/.aws/credentials`, no IAM role), boto3 raises `NoCredentialsError` at call time. The `_call()` helper catches this via the generic `Exception` handler and converts to `ToolError`.
- **`type` parameter shadowing:** `aws_ssm_put_parameter` uses `type` as a parameter name (Python builtin). Same as ClickUp views — ruff `A` ruleset is not enabled, so no linting error.
- **datetime serialization:** boto3 responses include `datetime` objects (e.g., `LastModifiedDate`). The `_serialize()` helper recursively converts these to ISO strings. Tests verify this with `datetime(2025, 1, 1)` in mock responses.
- **`_call()` generic helper:** Unlike other tool modules that have `_request()` calling httpx, this module uses `_call(method_name, **kwargs)` which calls `getattr(client, method)`. This is more flexible but means typos in method names would fail at runtime, not import time.
