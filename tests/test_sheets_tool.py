"""Tests for Google Sheets tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.sheets_tool import register_tools

BASE = "https://sheets.googleapis.com/v4/spreadsheets"
SID = "spreadsheet123"


def _r(result) -> dict:
    return json.loads(result[0][0].text)


def _ok(result) -> None:
    assert _r(result)["status"] == "success"


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_creds = type("C", (), {
        "valid": True, "token": "tok", "refresh": lambda self, r: None,
    })()
    with patch(
        "mcp_toolbox.tools.sheets_tool.GOOGLE_SERVICE_ACCOUNT_JSON",
        "/fake/key.json",
    ), patch(
        "mcp_toolbox.tools.sheets_tool.GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID",
        SID,
    ), patch(
        "mcp_toolbox.tools.sheets_tool._credentials", mock_creds,
    ), patch(
        "mcp_toolbox.tools.sheets_tool._client", None,
    ):
        register_tools(mcp)
        yield mcp


# --- Auth/Error ---

@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with patch(
        "mcp_toolbox.tools.sheets_tool.GOOGLE_SERVICE_ACCOUNT_JSON", None,
    ), patch(
        "mcp_toolbox.tools.sheets_tool.GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID",
        None,
    ), patch(
        "mcp_toolbox.tools.sheets_tool._credentials", None,
    ), patch(
        "mcp_toolbox.tools.sheets_tool._client", None,
    ):
        register_tools(mcp)
        with pytest.raises(Exception, match="GOOGLE_SERVICE_ACCOUNT_JSON"):
            await mcp.call_tool("sheets_read_values", {
                "range": "A1", "spreadsheet_id": "test",
            })


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit(server):
    respx.get(f"{BASE}/{SID}/values/A1").mock(
        return_value=httpx.Response(429),
    )
    with pytest.raises(Exception, match="rate limit"):
        await server.call_tool("sheets_read_values", {"range": "A1"})


@pytest.mark.asyncio
@respx.mock
async def test_api_error(server):
    respx.get(f"{BASE}/{SID}/values/Bad!Range").mock(
        return_value=httpx.Response(
            400,
            json={"error": {"message": "Invalid range"}},
        ),
    )
    with pytest.raises(Exception, match="Invalid range"):
        await server.call_tool("sheets_read_values", {"range": "Bad!Range"})


# --- Tier 1: Spreadsheet Operations ---

@pytest.mark.asyncio
@respx.mock
async def test_create_spreadsheet(server):
    respx.post(f"{BASE}/").mock(
        return_value=httpx.Response(200, json={"spreadsheetId": "new1"}),
    )
    _ok(await server.call_tool(
        "sheets_create_spreadsheet", {"title": "Test"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_get_spreadsheet(server):
    respx.get(f"{BASE}/{SID}").mock(
        return_value=httpx.Response(200, json={"spreadsheetId": SID}),
    )
    _ok(await server.call_tool("sheets_get_spreadsheet", {}))


@pytest.mark.asyncio
@respx.mock
async def test_batch_update_spreadsheet(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool(
        "sheets_batch_update_spreadsheet",
        {"requests": [{"addSheet": {"properties": {"title": "X"}}}]},
    ))


# --- Tier 2: Sheet Operations ---

@pytest.mark.asyncio
@respx.mock
async def test_add_sheet(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": [{}]}),
    )
    _ok(await server.call_tool("sheets_add_sheet", {"title": "New"}))


@pytest.mark.asyncio
@respx.mock
async def test_delete_sheet(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool("sheets_delete_sheet", {"sheet_id": 1}))


@pytest.mark.asyncio
@respx.mock
async def test_copy_sheet(server):
    respx.post(f"{BASE}/{SID}/sheets/0:copyTo").mock(
        return_value=httpx.Response(200, json={"sheetId": 99}),
    )
    _ok(await server.call_tool("sheets_copy_sheet", {
        "sheet_id": 0, "destination_spreadsheet_id": "other",
    }))


@pytest.mark.asyncio
@respx.mock
async def test_rename_sheet(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool(
        "sheets_rename_sheet", {"sheet_id": 0, "title": "Renamed"},
    ))


# --- Tier 3: Cell/Range Value Operations ---

@pytest.mark.asyncio
@respx.mock
async def test_read_values(server):
    respx.get(f"{BASE}/{SID}/values/Sheet1!A1:B2").mock(
        return_value=httpx.Response(200, json={
            "range": "Sheet1!A1:B2", "values": [["a", "b"]],
        }),
    )
    _ok(await server.call_tool(
        "sheets_read_values", {"range": "Sheet1!A1:B2"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_write_values(server):
    respx.put(f"{BASE}/{SID}/values/Sheet1!A1:B2").mock(
        return_value=httpx.Response(200, json={"updatedCells": 4}),
    )
    _ok(await server.call_tool("sheets_write_values", {
        "range": "Sheet1!A1:B2",
        "values": [["a", "b"], ["c", "d"]],
    }))


@pytest.mark.asyncio
@respx.mock
async def test_append_values(server):
    respx.post(f"{BASE}/{SID}/values/Sheet1!A:D:append").mock(
        return_value=httpx.Response(200, json={"updates": {}}),
    )
    _ok(await server.call_tool("sheets_append_values", {
        "range": "Sheet1!A:D",
        "values": [["e", "f"]],
    }))


@pytest.mark.asyncio
@respx.mock
async def test_clear_values(server):
    respx.post(f"{BASE}/{SID}/values/Sheet1!A1:B2:clear").mock(
        return_value=httpx.Response(200, json={"clearedRange": "Sheet1!A1:B2"}),
    )
    _ok(await server.call_tool(
        "sheets_clear_values", {"range": "Sheet1!A1:B2"},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_batch_get_values(server):
    respx.get(f"{BASE}/{SID}/values:batchGet").mock(
        return_value=httpx.Response(200, json={"valueRanges": []}),
    )
    _ok(await server.call_tool(
        "sheets_batch_get_values", {"ranges": ["A1:B2", "C1:D2"]},
    ))


@pytest.mark.asyncio
@respx.mock
async def test_batch_update_values(server):
    respx.post(f"{BASE}/{SID}/values:batchUpdate").mock(
        return_value=httpx.Response(200, json={"totalUpdatedCells": 2}),
    )
    _ok(await server.call_tool("sheets_batch_update_values", {
        "data": [{"range": "A1", "values": [["x"]]}],
    }))


@pytest.mark.asyncio
@respx.mock
async def test_batch_clear_values(server):
    respx.post(f"{BASE}/{SID}/values:batchClear").mock(
        return_value=httpx.Response(200, json={"clearedRanges": []}),
    )
    _ok(await server.call_tool(
        "sheets_batch_clear_values", {"ranges": ["A1:B2"]},
    ))


# --- Tier 4: Formatting ---

@pytest.mark.asyncio
@respx.mock
async def test_format_cells(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool("sheets_format_cells", {
        "sheet_id": 0, "start_row": 0, "end_row": 1,
        "start_column": 0, "end_column": 5, "bold": True,
    }))


@pytest.mark.asyncio
async def test_format_cells_no_props(server):
    with pytest.raises(Exception, match="At least one formatting"):
        await server.call_tool("sheets_format_cells", {
            "sheet_id": 0, "start_row": 0, "end_row": 1,
            "start_column": 0, "end_column": 5,
        })


@pytest.mark.asyncio
@respx.mock
async def test_update_borders(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool("sheets_update_borders", {
        "sheet_id": 0, "start_row": 0, "end_row": 5,
        "start_column": 0, "end_column": 5, "top_style": "SOLID",
    }))


@pytest.mark.asyncio
async def test_update_borders_no_style(server):
    with pytest.raises(Exception, match="At least one border"):
        await server.call_tool("sheets_update_borders", {
            "sheet_id": 0, "start_row": 0, "end_row": 5,
            "start_column": 0, "end_column": 5,
        })


@pytest.mark.asyncio
@respx.mock
async def test_merge_cells(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool("sheets_merge_cells", {
        "sheet_id": 0, "start_row": 0, "end_row": 2,
        "start_column": 0, "end_column": 3,
    }))


@pytest.mark.asyncio
@respx.mock
async def test_unmerge_cells(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool("sheets_unmerge_cells", {
        "sheet_id": 0, "start_row": 0, "end_row": 2,
        "start_column": 0, "end_column": 3,
    }))


@pytest.mark.asyncio
@respx.mock
async def test_auto_resize(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool("sheets_auto_resize", {
        "sheet_id": 0, "dimension": "COLUMNS",
        "start_index": 0, "end_index": 5,
    }))


# --- Tier 5: Named Ranges ---

@pytest.mark.asyncio
@respx.mock
async def test_add_named_range(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": [{}]}),
    )
    _ok(await server.call_tool("sheets_add_named_range", {
        "name": "MyRange", "sheet_id": 0,
        "start_row": 0, "end_row": 10,
        "start_column": 0, "end_column": 4,
    }))


@pytest.mark.asyncio
@respx.mock
async def test_update_named_range(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool("sheets_update_named_range", {
        "named_range_id": "nr1", "name": "Renamed",
    }))


@pytest.mark.asyncio
async def test_update_named_range_no_fields(server):
    with pytest.raises(Exception, match="At least name or range"):
        await server.call_tool(
            "sheets_update_named_range", {"named_range_id": "nr1"},
        )


@pytest.mark.asyncio
@respx.mock
async def test_delete_named_range(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool(
        "sheets_delete_named_range", {"named_range_id": "nr1"},
    ))


# --- Tier 6: Filters ---

@pytest.mark.asyncio
@respx.mock
async def test_set_basic_filter(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool("sheets_set_basic_filter", {
        "sheet_id": 0, "start_row": 0, "end_row": 100,
        "start_column": 0, "end_column": 5,
    }))


@pytest.mark.asyncio
@respx.mock
async def test_clear_basic_filter(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool(
        "sheets_clear_basic_filter", {"sheet_id": 0},
    ))


# --- Tier 7: Charts ---

@pytest.mark.asyncio
@respx.mock
async def test_add_chart(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": [{}]}),
    )
    _ok(await server.call_tool("sheets_add_chart", {
        "sheet_id": 0, "chart_type": "LINE",
        "source_start_row": 0, "source_end_row": 10,
        "source_start_column": 0, "source_end_column": 3,
    }))


@pytest.mark.asyncio
async def test_add_chart_too_few_columns(server):
    with pytest.raises(Exception, match="at least 2 columns"):
        await server.call_tool("sheets_add_chart", {
            "sheet_id": 0, "chart_type": "LINE",
            "source_start_row": 0, "source_end_row": 10,
            "source_start_column": 0, "source_end_column": 1,
        })


# --- Tier 8: Protection ---

@pytest.mark.asyncio
@respx.mock
async def test_protect_range(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": [{}]}),
    )
    _ok(await server.call_tool("sheets_protect_range", {
        "sheet_id": 0, "start_row": 0, "end_row": 1,
        "start_column": 0, "end_column": 10,
    }))


@pytest.mark.asyncio
@respx.mock
async def test_unprotect_range(server):
    respx.post(f"{BASE}/{SID}:batchUpdate").mock(
        return_value=httpx.Response(200, json={"replies": []}),
    )
    _ok(await server.call_tool(
        "sheets_unprotect_range", {"protected_range_id": 123},
    ))


# --- Default spreadsheet ID ---

@pytest.mark.asyncio
async def test_no_spreadsheet_id():
    mcp = FastMCP("test")
    mock_creds = type("C", (), {
        "valid": True, "token": "tok", "refresh": lambda self, r: None,
    })()
    with patch(
        "mcp_toolbox.tools.sheets_tool.GOOGLE_SERVICE_ACCOUNT_JSON",
        "/fake/key.json",
    ), patch(
        "mcp_toolbox.tools.sheets_tool.GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID",
        None,
    ), patch(
        "mcp_toolbox.tools.sheets_tool._credentials", mock_creds,
    ), patch(
        "mcp_toolbox.tools.sheets_tool._client", None,
    ):
        register_tools(mcp)
        with pytest.raises(Exception, match="No spreadsheet_id"):
            await mcp.call_tool("sheets_read_values", {"range": "A1"})
