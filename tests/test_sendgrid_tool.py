"""Tests for SendGrid tool integration."""

import json
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.sendgrid_tool import register_tools


def _mock_response(status_code=202, body=b"", headers=None):
    """Create a mock SendGrid API response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.body = body
    resp.headers = headers or {"X-Message-Id": "test-message-id-123"}
    return resp


def _get_result_data(result) -> dict:
    """Extract and parse JSON from call_tool result.

    call_tool returns (list[TextContent], dict). Access result[0][0].text
    to get the tool's JSON string output.
    """
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    """Create a test MCP server with SendGrid tools registered.

    Uses yield to keep config patches active for the duration of the test.
    Resets the cached _sg client between tests to prevent leakage.
    """
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.sendgrid_tool.SENDGRID_API_KEY", "SG.test-key"), \
         patch("mcp_toolbox.tools.sendgrid_tool.SENDGRID_FROM_EMAIL", "test@example.com"), \
         patch("mcp_toolbox.tools.sendgrid_tool.SENDGRID_FROM_NAME", "Test Sender"), \
         patch("mcp_toolbox.tools.sendgrid_tool._sg", None):
        register_tools(mcp)
        yield mcp


# --- Missing API Key ---


@pytest.mark.asyncio
async def test_send_email_missing_api_key():
    """Tools should raise ToolError when API key is not configured."""
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.sendgrid_tool.SENDGRID_API_KEY", None), \
         patch("mcp_toolbox.tools.sendgrid_tool.SENDGRID_FROM_EMAIL", "test@example.com"), \
         patch("mcp_toolbox.tools.sendgrid_tool._sg", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="SENDGRID_API_KEY"):
            await mcp.call_tool("send_email", {
                "to": "user@example.com",
                "subject": "Test",
                "body": "Hello",
            })


# --- Tier 1: Core Email Tools ---


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_send_email_success(mock_sg, server):
    mock_sg.send.return_value = _mock_response(202)

    result = await server.call_tool("send_email", {
        "to": "user@example.com",
        "subject": "Test Subject",
        "body": "Hello World",
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["status_code"] == 202
    mock_sg.send.assert_called_once()


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_send_email_with_cc_bcc(mock_sg, server):
    mock_sg.send.return_value = _mock_response(202)

    result = await server.call_tool("send_email", {
        "to": ["user1@example.com", "user2@example.com"],
        "subject": "Test",
        "body": "Hello",
        "cc": "cc@example.com",
        "bcc": ["bcc1@example.com", "bcc2@example.com"],
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_send_template_email_success(mock_sg, server):
    mock_sg.send.return_value = _mock_response(202)

    result = await server.call_tool("send_template_email", {
        "to": "user@example.com",
        "template_id": "d-abc123",
        "template_data": {"name": "John", "code": "XYZ"},
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_send_email_with_attachment(mock_sg, server, tmp_path):
    mock_sg.send.return_value = _mock_response(202)

    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello attachment")

    result = await server.call_tool("send_email_with_attachment", {
        "to": "user@example.com",
        "subject": "With attachment",
        "body": "See attached",
        "attachments": [{"file_path": str(test_file)}],
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    mock_sg.send.assert_called_once()


@pytest.mark.asyncio
async def test_send_email_with_attachment_missing_file(server):
    """Attachment with nonexistent file should fail."""
    with pytest.raises(Exception, match="not found"):
        await server.call_tool("send_email_with_attachment", {
            "to": "user@example.com",
            "subject": "Test",
            "body": "Test",
            "attachments": [{"file_path": "/nonexistent/file.txt"}],
        })


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_schedule_email_unix_timestamp(mock_sg, server):
    mock_sg.send.return_value = _mock_response(202)

    result = await server.call_tool("schedule_email", {
        "to": "user@example.com",
        "subject": "Scheduled",
        "body": "Future email",
        "send_at": 1735689600,
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["scheduled_for"] == 1735689600


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_schedule_email_iso_datetime(mock_sg, server):
    mock_sg.send.return_value = _mock_response(202)

    result = await server.call_tool("schedule_email", {
        "to": "user@example.com",
        "subject": "Scheduled",
        "body": "Future email",
        "send_at": "2025-01-01T12:00:00+00:00",
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


# --- Tier 2: Email Management Tools ---


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_list_templates(mock_sg, server):
    mock_sg.client.templates.get.return_value = _mock_response(
        200,
        json.dumps({"templates": [
            {"id": "d-1", "name": "Welcome", "updated_at": "2025-01-01"},
            {"id": "d-2", "name": "Reset", "updated_at": "2025-01-02"},
        ]}).encode(),
    )

    result = await server.call_tool("list_templates", {})
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["count"] == 2


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_get_template(mock_sg, server):
    mock_sg.client.templates._("d-123").get.return_value = _mock_response(
        200, json.dumps({"id": "d-123", "name": "Welcome"}).encode()
    )

    result = await server.call_tool("get_template", {"template_id": "d-123"})
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_get_email_stats(mock_sg, server):
    mock_sg.client.stats.get.return_value = _mock_response(
        200, json.dumps([{"date": "2025-01-01", "stats": []}]).encode()
    )

    result = await server.call_tool("get_email_stats", {
        "start_date": "2025-01-01",
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_get_bounces(mock_sg, server):
    mock_sg.client.suppression.bounces.get.return_value = _mock_response(
        200, json.dumps([{"email": "bad@example.com", "reason": "550"}]).encode()
    )

    result = await server.call_tool("get_bounces", {})
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["count"] == 1


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_get_spam_reports(mock_sg, server):
    mock_sg.client.suppression.spam_reports.get.return_value = _mock_response(
        200, json.dumps([{"email": "spam@example.com"}]).encode()
    )

    result = await server.call_tool("get_spam_reports", {})
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["count"] == 1


@pytest.mark.asyncio
async def test_manage_suppressions_add_invalid_type(server):
    """Adding to bounces should fail — only global_unsubscribes supports add."""
    with pytest.raises(Exception, match="Cannot manually add"):
        await server.call_tool("manage_suppressions", {
            "action": "add",
            "suppression_type": "bounces",
            "emails": ["test@example.com"],
        })


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_manage_suppressions_add_global(mock_sg, server):
    mock_sg.client.asm.suppressions._("global").post.return_value = _mock_response(201)

    result = await server.call_tool("manage_suppressions", {
        "action": "add",
        "suppression_type": "global_unsubscribes",
        "emails": ["unsub@example.com"],
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


# --- Tier 3: Contact Management Tools ---


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_add_contacts(mock_sg, server):
    mock_sg.client.marketing.contacts.put.return_value = _mock_response(
        202, json.dumps({"job_id": "job-123"}).encode()
    )

    result = await server.call_tool("add_contacts", {
        "contacts": [
            {"email": "john@example.com", "first_name": "John"},
            {"email": "jane@example.com", "first_name": "Jane"},
        ],
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["job_id"] == "job-123"
    assert result_data["contacts_count"] == 2


@pytest.mark.asyncio
async def test_add_contacts_missing_email(server):
    """Contacts without 'email' field should fail."""
    with pytest.raises(Exception, match="email"):
        await server.call_tool("add_contacts", {
            "contacts": [{"first_name": "John"}],
        })


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_search_contacts(mock_sg, server):
    mock_sg.client.marketing.contacts.search.post.return_value = _mock_response(
        200,
        json.dumps({
            "result": [{"email": "john@example.com", "first_name": "John"}],
            "contact_count": 1,
        }).encode(),
    )

    result = await server.call_tool("search_contacts", {
        "query": "email = 'john@example.com'",
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"
    assert result_data["count"] == 1


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_get_contact(mock_sg, server):
    mock_sg.client.marketing.contacts._("contact-uuid").get.return_value = _mock_response(
        200, json.dumps({"id": "contact-uuid", "email": "john@example.com"}).encode()
    )

    result = await server.call_tool("get_contact", {"contact_id": "contact-uuid"})
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_manage_lists_create(mock_sg, server):
    mock_sg.client.marketing.lists.post.return_value = _mock_response(
        201, json.dumps({"id": "list-abc", "name": "VIPs"}).encode()
    )

    result = await server.call_tool("manage_lists", {
        "action": "create",
        "name": "VIPs",
    })
    result_data = _get_result_data(result)
    assert result_data["status"] == "success"


@pytest.mark.asyncio
async def test_manage_lists_create_missing_name(server):
    """Creating a list without a name should fail."""
    with pytest.raises(Exception, match="name"):
        await server.call_tool("manage_lists", {"action": "create"})


# --- API Error Handling ---


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_send_email_api_error(mock_sg, server):
    """API errors should be converted to ToolError."""
    mock_sg.send.side_effect = Exception("403 Forbidden: insufficient permissions")

    with pytest.raises(Exception, match="SendGrid API error"):
        await server.call_tool("send_email", {
            "to": "user@example.com",
            "subject": "Test",
            "body": "Hello",
        })


@pytest.mark.asyncio
@patch("mcp_toolbox.tools.sendgrid_tool._sg")
async def test_list_templates_api_error(mock_sg, server):
    """Management API errors should be converted to ToolError."""
    mock_sg.client.templates.get.side_effect = Exception("429 Too Many Requests")

    with pytest.raises(Exception, match="SendGrid API error"):
        await server.call_tool("list_templates", {})
