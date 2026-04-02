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


# --- Error Handling ---


@pytest.mark.asyncio
async def test_client_error():
    mcp = FastMCP("test")
    mock_client = MagicMock()
    error_response = {
        "Error": {"Code": "AccessDeniedException", "Message": "Not authorized"}
    }
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
            "Version": 1,
            "LastModifiedDate": datetime(2025, 1, 1, tzinfo=timezone.utc),
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
