# Task 08: AWS Systems Manager Parameter Store Integration - Analysis & Requirements

## Objective
Add AWS Systems Manager Parameter Store as a tool integration in mcp-toolbox, providing free hierarchical configuration and encrypted secret storage (up to 10,000 parameters on the free Standard tier).

---

## API Technical Details

### AWS Systems Manager Parameter Store
- **Service:** AWS Systems Manager (SSM) — Parameter Store is a feature within it
- **SDK:** `boto3` (sync) — the official AWS Python SDK
- **Auth:** IAM credentials (access key + secret key + region)
- **Free tier:** Standard parameters — 10,000 params, 4KB max value, free

### Authentication — IAM Credentials
AWS SDKs use a credential chain that automatically reads from:
1. Environment variables: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`
2. `~/.aws/credentials` and `~/.aws/config` files
3. IAM instance profiles (EC2/ECS/Lambda)

For the MCP server, we use environment variables — same pattern as other integrations.

### Parameter Types
| Type | Description |
|------|-------------|
| `String` | Plaintext string value |
| `StringList` | Comma-separated list of strings |
| `SecureString` | Encrypted at rest using AWS KMS (free with default key) |

### Hierarchical Paths
Parameters support `/`-delimited hierarchical naming:
```
/myapp/prod/db-host          (String)
/myapp/prod/db-password      (SecureString)
/myapp/staging/api-key       (SecureString)
```
`GetParametersByPath` retrieves all parameters under a path prefix.

### Rate Limits

| Tier | Default TPS | Max TPS |
|------|-------------|---------|
| Standard (free) | 40 | 1,000 (increasable) |
| Advanced ($0.05/param/month) | 1,000 | 10,000 |

Throttling returns `ThrottlingException`. Standard exponential backoff applies.

### Versioning
- Every `PutParameter` call increments the version number (1, 2, 3...)
- `GetParameterHistory` returns all versions
- Labels can be attached to specific versions
- Up to 100 past versions retained

---

## Architecture Decisions

### A1: boto3 with asyncio.to_thread (no aioboto3)
`boto3` is synchronous. Rather than adding `aioboto3` (community package, adds `aiohttp` dependency), we wrap boto3 calls in `asyncio.to_thread()` — same pattern we use for `msal` in O365/Teams/Key Vault. This avoids adding a new async HTTP stack.

### A2: boto3 Client — Native Credential Chain
Let boto3 handle credential resolution natively. The AWS SDK automatically reads from:
1. Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`)
2. `~/.aws/credentials` and `~/.aws/config`
3. IAM instance profiles (EC2/ECS/Lambda)

We do NOT explicitly pass credentials in code — this preserves the full credential chain. Config.py defines optional override variables, but the client is created without them unless explicitly set:

```python
import boto3

_ssm_client = None

def _get_client():
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
            _ssm_client = boto3.client('ssm', **kwargs)
        except Exception as e:
            raise ToolError(f"Failed to create AWS SSM client: {e}") from e
    return _ssm_client
```

This means: if AWS env vars or `~/.aws/credentials` are configured, the tools work without any mcp-toolbox config. If the user wants to override, they set `AWS_*` vars in `.env`.

### A3: All boto3 Calls via asyncio.to_thread
Every tool wraps the sync boto3 call:
```python
result = await asyncio.to_thread(client.get_parameter, Name=name, WithDecryption=True)
```

### A4: Response Format
Same JSON convention: `{"status": "success", ...}`. boto3 responses contain non-serializable `datetime` objects — convert to ISO strings before JSON serialization.

### A5: Error Handling
boto3 raises `botocore.exceptions.ClientError` for API errors. Convert to `ToolError` with the AWS error code and message.

---

## Configuration Requirements

### Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `AWS_ACCESS_KEY_ID` | IAM access key | No (boto3 auto-resolves) | boto3 credential chain |
| `AWS_SECRET_ACCESS_KEY` | IAM secret key | No (boto3 auto-resolves) | boto3 credential chain |
| `AWS_DEFAULT_REGION` | AWS region (e.g., `us-east-1`) | No (boto3 auto-resolves) | boto3 config chain |

**Note:** These are standard AWS SDK environment variables that boto3 reads automatically. They are NOT required in config.py — boto3 also reads from `~/.aws/credentials`, IAM instance profiles, and ECS task roles. Config.py defines them as optional overrides only.

### Config Pattern
```python
AWS_ACCESS_KEY_ID: str | None = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY: str | None = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION: str | None = os.getenv("AWS_DEFAULT_REGION")
```

---

## Tool Specifications

### Parameter CRUD (7 tools)

#### `aws_ssm_put_parameter`
Create or update a parameter.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Parameter name (supports `/` hierarchy) |
| `value` | str | Yes | Parameter value |
| `type` | str | No | `String`, `StringList`, or `SecureString` (default `String`) |
| `description` | str | No | Parameter description |
| `overwrite` | bool | No | Overwrite if exists (default true) |

**Returns:** Version number.
**API:** `ssm.put_parameter()`

**Note:** Tags cannot be set via `PutParameter` when overwriting — AWS silently ignores them. Use `aws_ssm_add_tags` separately to manage tags. Also, AWS retains up to 100 versions per parameter. If the oldest version has a label, `PutParameter` will fail with `ParameterMaxVersionLimitExceeded` — remove the label first with `aws_ssm_unlabel_parameter_version`.

#### `aws_ssm_get_parameter`
Get a parameter value (decrypts SecureString automatically).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Parameter name |

**Returns:** Parameter with name, type, value, version.
**API:** `ssm.get_parameter(Name=name, WithDecryption=True)`

#### `aws_ssm_get_parameters`
Get multiple parameters by name in one call.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `names` | list[str] | Yes | Parameter names (max 10) |

**Returns:** List of parameters + list of invalid names.
**API:** `ssm.get_parameters(Names=names, WithDecryption=True)`

#### `aws_ssm_get_parameters_by_path`
Get all parameters under a hierarchy path.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | str | Yes | Path prefix (e.g., `/myapp/prod/`) |
| `recursive` | bool | No | Include sub-paths (default true) |
| `max_results` | int | No | Max results (default 10) |

**Returns:** List of parameters under the path.
**API:** `ssm.get_parameters_by_path(Path=path, Recursive=recursive, WithDecryption=True)`

#### `aws_ssm_describe_parameters`
List/search parameters (metadata only, no values).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `max_results` | int | No | Max results (default 50) |
| `name_prefix` | str | No | Filter by name prefix |

**Returns:** List of parameter metadata.
**API:** `ssm.describe_parameters()`

#### `aws_ssm_delete_parameter`
Delete a parameter.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Parameter name |

**Returns:** Confirmation.
**API:** `ssm.delete_parameter(Name=name)`

#### `aws_ssm_delete_parameters`
Delete multiple parameters in one call.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `names` | list[str] | Yes | Parameter names (max 10) |

**Returns:** List of deleted + invalid parameter names.
**API:** `ssm.delete_parameters(Names=names)`

---

### Parameter History & Versioning (3 tools)

#### `aws_ssm_get_parameter_history`
Get version history of a parameter.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Parameter name |
| `max_results` | int | No | Max results (default 50) |

**Returns:** List of parameter versions with values.
**API:** `ssm.get_parameter_history(Name=name, WithDecryption=True)`

#### `aws_ssm_label_parameter_version`
Attach a label to a specific parameter version.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Parameter name |
| `version` | int | Yes | Parameter version number |
| `labels` | list[str] | Yes | Labels to attach |

**Returns:** Confirmation with invalid labels (if any).
**API:** `ssm.label_parameter_version(Name=name, ParameterVersion=version, Labels=labels)`

#### `aws_ssm_unlabel_parameter_version`
Remove labels from a parameter version.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Parameter name |
| `version` | int | Yes | Parameter version number |
| `labels` | list[str] | Yes | Labels to remove |

**Returns:** Confirmation with removed/invalid labels.
**API:** `ssm.unlabel_parameter_version(Name=name, ParameterVersion=version, Labels=labels)`

---

### Tagging (3 tools)

#### `aws_ssm_add_tags`
Add tags to a parameter.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Parameter name |
| `tags` | list[dict] | Yes | Tags as `[{"Key": "k", "Value": "v"}]` |

**Returns:** Confirmation.
**API:** `ssm.add_tags_to_resource(ResourceType='Parameter', ResourceId=name, Tags=tags)`

#### `aws_ssm_remove_tags`
Remove tags from a parameter.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Parameter name |
| `tag_keys` | list[str] | Yes | Tag keys to remove |

**Returns:** Confirmation.
**API:** `ssm.remove_tags_from_resource(ResourceType='Parameter', ResourceId=name, TagKeys=tag_keys)`

#### `aws_ssm_list_tags`
List tags on a parameter.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Parameter name |

**Returns:** List of tags.
**API:** `ssm.list_tags_for_resource(ResourceType='Parameter', ResourceId=name)`

---

## Tool Summary (13 tools total)

### Parameter CRUD (7 tools)
1. `aws_ssm_put_parameter` — Create/update parameter
2. `aws_ssm_get_parameter` — Get parameter value (decrypts SecureString)
3. `aws_ssm_get_parameters` — Get multiple parameters
4. `aws_ssm_get_parameters_by_path` — Get by hierarchy path
5. `aws_ssm_describe_parameters` — List/search parameters (metadata)
6. `aws_ssm_delete_parameter` — Delete parameter
7. `aws_ssm_delete_parameters` — Delete multiple parameters

### History & Versioning (3 tools)
8. `aws_ssm_get_parameter_history` — Get version history
9. `aws_ssm_label_parameter_version` — Label a version
10. `aws_ssm_unlabel_parameter_version` — Remove labels from a version

### Tagging (3 tools)
11. `aws_ssm_add_tags` — Add tags
12. `aws_ssm_remove_tags` — Remove tags
13. `aws_ssm_list_tags` — List tags

---

## Dependencies

| Package | Purpose | Already in project? |
|---------|---------|-------------------|
| `boto3` | AWS SDK (sync) | **New** — add to runtime deps |

No new dev dependencies. `boto3` brings `botocore` and `s3transfer` as transitive deps.

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Modify | Add `boto3>=1.34.0` to dependencies |
| `src/mcp_toolbox/config.py` | Modify | Add AWS config variables |
| `.env.example` | Modify | Add AWS variables |
| `src/mcp_toolbox/tools/aws_ssm_tool.py` | **New** | All Parameter Store tools |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register aws_ssm_tool |
| `tests/test_aws_ssm_tool.py` | **New** | Tests for all 13 tools |
| `tests/test_server.py` | Modify | Update tool count to 196 |
| `CLAUDE.md` | Modify | Document AWS SSM integration |
| `pyproject.toml` | Modify | Add aws_ssm_tool.py to pyright exclude |

---

## Testing Strategy

### Approach
Use `unittest.mock.patch` to mock the `boto3.client` and its method calls. No `respx` needed — boto3 doesn't use httpx.

```python
from unittest.mock import MagicMock, patch

@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_client = MagicMock()
    with patch("mcp_toolbox.tools.aws_ssm_tool.AWS_ACCESS_KEY_ID", "AKIA..."), \
         patch("mcp_toolbox.tools.aws_ssm_tool.AWS_SECRET_ACCESS_KEY", "secret"), \
         patch("mcp_toolbox.tools.aws_ssm_tool.AWS_DEFAULT_REGION", "us-east-1"), \
         patch("mcp_toolbox.tools.aws_ssm_tool._ssm_client", mock_client):
        register_tools(mcp)
        yield mcp, mock_client
```

### Test Coverage
1. Happy path for every tool
2. Missing credentials → ToolError
3. AWS ClientError handling (parameter not found, access denied)
4. DateTime serialization (boto3 responses contain datetime objects)

---

## Success Criteria

1. `uv sync` installs `boto3` without errors
2. All 13 SSM tools register and are discoverable
3. Tools return meaningful errors when credentials are missing
4. boto3 datetime objects are properly serialized to JSON
5. New tests pass and full regression suite remains green
6. Total toolbox: 183 existing + 13 new = **196 tools**
