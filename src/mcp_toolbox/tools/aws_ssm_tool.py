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
    return json.dumps(
        {"status": "success", "status_code": status_code, **_serialize(kwargs)}
    )


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

    # --- Parameter CRUD ---

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
        next_token: str | None = None,
    ) -> str:
        """Get AWS SSM parameters under a hierarchy path.

        Args:
            path: Path prefix (e.g., /myapp/prod/)
            recursive: Include sub-paths (default true)
            max_results: Max results (default 10)
            next_token: Pagination token from previous response
        """
        kwargs: dict = {
            "Path": path, "Recursive": recursive,
            "WithDecryption": True, "MaxResults": max_results,
        }
        if next_token:
            kwargs["NextToken"] = next_token
        result = await _call("get_parameters_by_path", **kwargs)
        params = result.get("Parameters", [])
        return _success(
            200, data=params, count=len(params),
            next_token=result.get("NextToken"),
        )

    @mcp.tool()
    async def aws_ssm_describe_parameters(
        max_results: int = 50,
        name_prefix: str | None = None,
        next_token: str | None = None,
    ) -> str:
        """List AWS SSM parameters (metadata only, no values).

        Args:
            max_results: Max results (default 50)
            name_prefix: Filter by name prefix
            next_token: Pagination token from previous response
        """
        kwargs: dict = {"MaxResults": max_results}
        if next_token:
            kwargs["NextToken"] = next_token
        if name_prefix:
            kwargs["ParameterFilters"] = [
                {"Key": "Name", "Option": "BeginsWith", "Values": [name_prefix]}
            ]
        result = await _call("describe_parameters", **kwargs)
        params = result.get("Parameters", [])
        return _success(
            200, data=params, count=len(params),
            next_token=result.get("NextToken"),
        )

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

    # --- History & Versioning ---

    @mcp.tool()
    async def aws_ssm_get_parameter_history(
        name: str,
        max_results: int = 50,
        next_token: str | None = None,
    ) -> str:
        """Get version history of an AWS SSM parameter.

        Args:
            name: Parameter name
            max_results: Max results (default 50)
            next_token: Pagination token from previous response
        """
        kwargs: dict = {
            "Name": name, "WithDecryption": True, "MaxResults": max_results,
        }
        if next_token:
            kwargs["NextToken"] = next_token
        result = await _call("get_parameter_history", **kwargs)
        params = result.get("Parameters", [])
        return _success(
            200, data=params, count=len(params),
            next_token=result.get("NextToken"),
        )

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

    # --- Tagging ---

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
