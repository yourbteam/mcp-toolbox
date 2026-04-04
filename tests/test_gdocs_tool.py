"""Tests for Google Docs tool integration."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.gdocs_tool import register_tools

BASE = "https://docs.googleapis.com/v1/documents"
DID = "doc123"

BATCH_OK = httpx.Response(
    200, json={"replies": [{}]},
)


def _r(result) -> dict:
    return json.loads(result[0][0].text)


def _ok(result) -> None:
    data = _r(result)
    assert "replies" in data


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_creds = type("C", (), {
        "valid": True, "token": "tok",
        "refresh": lambda self, r: None,
    })()
    with patch(
        "mcp_toolbox.tools.gdocs_tool"
        ".GOOGLE_SERVICE_ACCOUNT_JSON",
        "/fake/key.json",
    ), patch(
        "mcp_toolbox.tools.gdocs_tool"
        ".GDOCS_DEFAULT_DOCUMENT_ID",
        DID,
    ), patch(
        "mcp_toolbox.tools.gdocs_tool._credentials",
        mock_creds,
    ), patch(
        "mcp_toolbox.tools.gdocs_tool._client",
        None,
    ):
        register_tools(mcp)
        yield mcp


# --- Auth/Error ---


@pytest.mark.asyncio
async def test_missing_config():
    mcp = FastMCP("test")
    with patch(
        "mcp_toolbox.tools.gdocs_tool"
        ".GOOGLE_SERVICE_ACCOUNT_JSON",
        None,
    ), patch(
        "mcp_toolbox.tools.gdocs_tool"
        ".GDOCS_DEFAULT_DOCUMENT_ID",
        None,
    ), patch(
        "mcp_toolbox.tools.gdocs_tool._credentials",
        None,
    ), patch(
        "mcp_toolbox.tools.gdocs_tool._client",
        None,
    ):
        register_tools(mcp)
        with pytest.raises(
            Exception,
            match="GOOGLE_SERVICE_ACCOUNT_JSON",
        ):
            await mcp.call_tool(
                "gdocs_get_document",
                {"document_id": "x"},
            )


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit(server):
    respx.get(f"{BASE}/{DID}").mock(
        return_value=httpx.Response(429),
    )
    with pytest.raises(
        Exception, match="rate limit",
    ):
        await server.call_tool(
            "gdocs_get_document", {},
        )


@pytest.mark.asyncio
@respx.mock
async def test_api_error(server):
    respx.get(f"{BASE}/{DID}").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "message": "Document not found",
                },
            },
        ),
    )
    with pytest.raises(
        Exception, match="Document not found",
    ):
        await server.call_tool(
            "gdocs_get_document", {},
        )


@pytest.mark.asyncio
@respx.mock
async def test_no_document_id_error(server):
    """Test _did raises when no ID provided."""
    mcp = FastMCP("test")
    mock_creds = type("C", (), {
        "valid": True, "token": "tok",
        "refresh": lambda self, r: None,
    })()
    with patch(
        "mcp_toolbox.tools.gdocs_tool"
        ".GOOGLE_SERVICE_ACCOUNT_JSON",
        "/fake/key.json",
    ), patch(
        "mcp_toolbox.tools.gdocs_tool"
        ".GDOCS_DEFAULT_DOCUMENT_ID",
        None,
    ), patch(
        "mcp_toolbox.tools.gdocs_tool._credentials",
        mock_creds,
    ), patch(
        "mcp_toolbox.tools.gdocs_tool._client",
        None,
    ):
        register_tools(mcp)
        with pytest.raises(
            Exception, match="document_id",
        ):
            await mcp.call_tool(
                "gdocs_insert_text",
                {"text": "hi", "index": 1},
            )


# ==========================================
# TIER 1: DOCUMENT OPERATIONS (3 tools)
# ==========================================


@pytest.mark.asyncio
@respx.mock
async def test_create_document(server):
    route = respx.post(f"{BASE}/").mock(
        return_value=httpx.Response(200, json={
            "documentId": "new1",
            "title": "My Doc",
        }),
    )
    r = _r(await server.call_tool(
        "gdocs_create_document",
        {"title": "My Doc"},
    ))
    assert r["documentId"] == "new1"
    body = json.loads(route.calls[0].request.content)
    assert body["title"] == "My Doc"


@pytest.mark.asyncio
@respx.mock
async def test_get_document(server):
    respx.get(f"{BASE}/{DID}").mock(
        return_value=httpx.Response(200, json={
            "documentId": DID,
            "title": "Test Doc",
            "body": {"content": []},
        }),
    )
    r = _r(await server.call_tool(
        "gdocs_get_document", {},
    ))
    assert r["documentId"] == DID


@pytest.mark.asyncio
@respx.mock
async def test_get_document_with_view_mode(server):
    respx.get(f"{BASE}/{DID}").mock(
        return_value=httpx.Response(200, json={
            "documentId": DID,
        }),
    )
    _r(await server.call_tool(
        "gdocs_get_document", {
            "suggestions_view_mode":
                "SUGGESTIONS_INLINE",
        },
    ))


@pytest.mark.asyncio
@respx.mock
async def test_batch_update(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_batch_update", {
            "requests": [
                {"insertText": {
                    "text": "hi",
                    "location": {"index": 1},
                }},
            ],
        },
    ))
    body = json.loads(route.calls[0].request.content)
    assert "requests" in body
    assert "insertText" in body["requests"][0]


# ==========================================
# TIER 2: TEXT CONTENT (3 tools)
# ==========================================


@pytest.mark.asyncio
@respx.mock
async def test_insert_text(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_insert_text", {
            "text": "Hello World",
            "index": 1,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "insertText" in req0
    assert req0["insertText"]["text"] == "Hello World"
    assert req0["insertText"]["location"]["index"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_insert_text_with_segment(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_insert_text", {
            "text": "Header text",
            "index": 1,
            "segment_id": "kix.header1",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "insertText" in req0
    assert req0["insertText"]["text"] == "Header text"
    loc = req0["insertText"]["location"]
    assert loc["index"] == 1
    assert loc["segmentId"] == "kix.header1"


@pytest.mark.asyncio
@respx.mock
async def test_delete_content(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_delete_content", {
            "start_index": 1,
            "end_index": 10,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "deleteContentRange" in req0
    rng = req0["deleteContentRange"]["range"]
    assert rng["startIndex"] == 1
    assert rng["endIndex"] == 10


@pytest.mark.asyncio
@respx.mock
async def test_replace_all_text(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_replace_all_text", {
            "find_text": "foo",
            "replace_text": "bar",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "replaceAllText" in req0
    assert req0["replaceAllText"]["containsText"]["text"] == "foo"
    assert req0["replaceAllText"]["replaceText"] == "bar"


# ==========================================
# TIER 3: FORMATTING (2 tools)
# ==========================================


@pytest.mark.asyncio
@respx.mock
async def test_update_text_style(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_text_style", {
            "start_index": 1,
            "end_index": 5,
            "bold": True,
            "italic": True,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "updateTextStyle" in req0
    ts = req0["updateTextStyle"]
    assert ts["textStyle"]["bold"] is True
    assert ts["textStyle"]["italic"] is True
    assert ts["range"]["startIndex"] == 1
    assert ts["range"]["endIndex"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_update_text_style_font(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_text_style", {
            "start_index": 1,
            "end_index": 5,
            "font_family": "Arial",
            "font_size_pt": 14.0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "updateTextStyle" in req0
    ts = req0["updateTextStyle"]["textStyle"]
    assert ts["weightedFontFamily"]["fontFamily"] == "Arial"
    assert ts["fontSize"]["magnitude"] == 14.0


@pytest.mark.asyncio
@respx.mock
async def test_update_text_style_colors(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_text_style", {
            "start_index": 1,
            "end_index": 5,
            "foreground_color_red": 1.0,
            "background_color_blue": 0.5,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    ts = req0["updateTextStyle"]["textStyle"]
    fg = ts["foregroundColor"]["color"]["rgbColor"]
    assert fg["red"] == 1.0
    bg = ts["backgroundColor"]["color"]["rgbColor"]
    assert bg["blue"] == 0.5


@pytest.mark.asyncio
@respx.mock
async def test_update_text_style_link(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_text_style", {
            "start_index": 1,
            "end_index": 5,
            "link_url": "https://example.com",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    ts = req0["updateTextStyle"]["textStyle"]
    assert ts["link"]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_update_text_style_no_fields(server):
    with pytest.raises(
        Exception, match="style property",
    ):
        await server.call_tool(
            "gdocs_update_text_style", {
                "start_index": 1,
                "end_index": 5,
            },
        )


@pytest.mark.asyncio
@respx.mock
async def test_update_paragraph_style(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_paragraph_style", {
            "start_index": 1,
            "end_index": 10,
            "alignment": "CENTER",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "updateParagraphStyle" in req0
    ps = req0["updateParagraphStyle"]
    assert ps["paragraphStyle"]["alignment"] == "CENTER"
    assert ps["range"]["startIndex"] == 1
    assert ps["range"]["endIndex"] == 10


@pytest.mark.asyncio
@respx.mock
async def test_update_paragraph_style_heading(
    server,
):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_paragraph_style", {
            "start_index": 1,
            "end_index": 10,
            "named_style_type": "HEADING_1",
            "line_spacing": 150.0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    ps = req0["updateParagraphStyle"]["paragraphStyle"]
    assert ps["namedStyleType"] == "HEADING_1"
    assert ps["lineSpacing"] == 150.0


@pytest.mark.asyncio
async def test_update_paragraph_style_no_fields(
    server,
):
    with pytest.raises(
        Exception, match="style property",
    ):
        await server.call_tool(
            "gdocs_update_paragraph_style", {
                "start_index": 1,
                "end_index": 10,
            },
        )


# ==========================================
# TIER 4: STRUCTURAL ELEMENTS (7 tools)
# ==========================================


@pytest.mark.asyncio
@respx.mock
async def test_insert_table(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_insert_table", {
            "rows": 3,
            "columns": 2,
            "index": 1,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "insertTable" in req0
    assert req0["insertTable"]["rows"] == 3
    assert req0["insertTable"]["columns"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_insert_table_row(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_insert_table_row", {
            "table_start_index": 5,
            "row_index": 0,
            "column_index": 0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "insertTableRow" in req0
    loc = req0["insertTableRow"]["tableCellLocation"]
    assert loc["tableStartLocation"]["index"] == 5
    assert loc["rowIndex"] == 0
    assert loc["columnIndex"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_insert_table_column(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_insert_table_column", {
            "table_start_index": 5,
            "row_index": 0,
            "column_index": 0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "insertTableColumn" in req0
    loc = req0["insertTableColumn"]["tableCellLocation"]
    assert loc["tableStartLocation"]["index"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_delete_table_row(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_delete_table_row", {
            "table_start_index": 5,
            "row_index": 1,
            "column_index": 0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "deleteTableRow" in req0
    loc = req0["deleteTableRow"]["tableCellLocation"]
    assert loc["rowIndex"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_delete_table_column(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_delete_table_column", {
            "table_start_index": 5,
            "row_index": 0,
            "column_index": 1,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "deleteTableColumn" in req0
    loc = req0["deleteTableColumn"]["tableCellLocation"]
    assert loc["columnIndex"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_insert_inline_image(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_insert_inline_image", {
            "uri": "https://example.com/img.png",
            "index": 1,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "insertInlineImage" in req0
    img = req0["insertInlineImage"]
    assert img["uri"] == "https://example.com/img.png"
    assert img["location"]["index"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_insert_inline_image_sized(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_insert_inline_image", {
            "uri": "https://example.com/img.png",
            "index": 1,
            "width_pt": 200.0,
            "height_pt": 150.0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    img = req0["insertInlineImage"]
    assert img["objectSize"]["width"]["magnitude"] == 200.0
    assert img["objectSize"]["height"]["magnitude"] == 150.0


@pytest.mark.asyncio
@respx.mock
async def test_insert_page_break(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_insert_page_break", {
            "index": 10,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "insertPageBreak" in req0
    assert req0["insertPageBreak"]["location"]["index"] == 10


# ==========================================
# TIER 5: TABLE FORMATTING (6 tools)
# ==========================================


@pytest.mark.asyncio
@respx.mock
async def test_update_table_column_properties(
    server,
):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_table_column_properties", {
            "table_start_index": 5,
            "column_indices": [0, 1],
            "width_pt": 100.0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "updateTableColumnProperties" in req0
    tcp = req0["updateTableColumnProperties"]
    assert tcp["columnIndices"] == [0, 1]
    assert tcp["tableColumnProperties"]["width"]["magnitude"] == 100.0


@pytest.mark.asyncio
@respx.mock
async def test_update_table_cell_style(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_table_cell_style", {
            "table_start_index": 5,
            "row_start": 0,
            "row_end": 1,
            "column_start": 0,
            "column_end": 2,
            "background_color_red": 0.9,
            "padding_top_pt": 4.0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "updateTableCellStyle" in req0
    tcs = req0["updateTableCellStyle"]
    bg = tcs["tableCellStyle"]["backgroundColor"]["color"]["rgbColor"]
    assert bg["red"] == 0.9
    assert tcs["tableCellStyle"]["paddingTop"]["magnitude"] == 4.0


@pytest.mark.asyncio
async def test_update_table_cell_style_no_fields(
    server,
):
    with pytest.raises(
        Exception, match="style property",
    ):
        await server.call_tool(
            "gdocs_update_table_cell_style", {
                "table_start_index": 5,
                "row_start": 0,
                "row_end": 1,
                "column_start": 0,
                "column_end": 2,
            },
        )


@pytest.mark.asyncio
@respx.mock
async def test_update_table_row_style(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_table_row_style", {
            "table_start_index": 5,
            "row_index": 0,
            "min_row_height_pt": 36.0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "updateTableRowStyle" in req0
    trs = req0["updateTableRowStyle"]
    assert trs["rowIndex"] == 0
    assert trs["tableRowStyle"]["minRowHeight"]["magnitude"] == 36.0


@pytest.mark.asyncio
@respx.mock
async def test_merge_table_cells(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_merge_table_cells", {
            "table_start_index": 5,
            "row_index": 0,
            "column_index": 0,
            "row_span": 2,
            "column_span": 2,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "mergeTableCells" in req0
    tr = req0["mergeTableCells"]["tableRange"]
    assert tr["rowSpan"] == 2
    assert tr["columnSpan"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_unmerge_table_cells(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_unmerge_table_cells", {
            "table_start_index": 5,
            "row_index": 0,
            "column_index": 0,
            "row_span": 2,
            "column_span": 2,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "unmergeTableCells" in req0
    tr = req0["unmergeTableCells"]["tableRange"]
    assert tr["rowSpan"] == 2
    assert tr["columnSpan"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_pin_table_header_rows(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_pin_table_header_rows", {
            "table_start_index": 5,
            "pinned_header_row_count": 1,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "pinTableHeaderRows" in req0
    assert req0["pinTableHeaderRows"]["pinnedHeaderRowsCount"] == 1


# ==========================================
# TIER 6: NAMED RANGES (2 tools)
# ==========================================


@pytest.mark.asyncio
@respx.mock
async def test_create_named_range(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_create_named_range", {
            "name": "my_range",
            "start_index": 1,
            "end_index": 10,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "createNamedRange" in req0
    assert req0["createNamedRange"]["name"] == "my_range"


@pytest.mark.asyncio
@respx.mock
async def test_delete_named_range_by_id(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_delete_named_range", {
            "named_range_id": "nr123",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "deleteNamedRange" in req0
    assert req0["deleteNamedRange"]["namedRangeId"] == "nr123"


@pytest.mark.asyncio
@respx.mock
async def test_delete_named_range_by_name(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_delete_named_range", {
            "name": "my_range",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "deleteNamedRange" in req0
    assert req0["deleteNamedRange"]["name"] == "my_range"


@pytest.mark.asyncio
async def test_delete_named_range_no_id_or_name(
    server,
):
    with pytest.raises(
        Exception,
        match="named_range_id or name",
    ):
        await server.call_tool(
            "gdocs_delete_named_range", {},
        )


# ==========================================
# TIER 7: LISTS / BULLETS (2 tools)
# ==========================================


@pytest.mark.asyncio
@respx.mock
async def test_create_paragraph_bullets(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_create_paragraph_bullets", {
            "start_index": 1,
            "end_index": 20,
            "bullet_preset":
                "BULLET_DISC_CIRCLE_SQUARE",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "createParagraphBullets" in req0
    assert req0["createParagraphBullets"]["bulletPreset"] == "BULLET_DISC_CIRCLE_SQUARE"


@pytest.mark.asyncio
@respx.mock
async def test_delete_paragraph_bullets(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_delete_paragraph_bullets", {
            "start_index": 1,
            "end_index": 20,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "deleteParagraphBullets" in req0
    rng = req0["deleteParagraphBullets"]["range"]
    assert rng["startIndex"] == 1
    assert rng["endIndex"] == 20


# ==========================================
# TIER 8: SECTION & DOCUMENT STYLE (3 tools)
# ==========================================


@pytest.mark.asyncio
@respx.mock
async def test_insert_section_break(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_insert_section_break", {
            "index": 10,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "insertSectionBreak" in req0
    assert req0["insertSectionBreak"]["location"]["index"] == 10
    assert req0["insertSectionBreak"]["sectionType"] == "CONTINUOUS"


@pytest.mark.asyncio
@respx.mock
async def test_insert_section_break_next_page(
    server,
):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_insert_section_break", {
            "index": 10,
            "section_type": "NEXT_PAGE",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert req0["insertSectionBreak"]["sectionType"] == "NEXT_PAGE"


@pytest.mark.asyncio
@respx.mock
async def test_update_document_style(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_document_style", {
            "margin_top_pt": 72.0,
            "margin_bottom_pt": 72.0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "updateDocumentStyle" in req0
    ds = req0["updateDocumentStyle"]["documentStyle"]
    assert ds["marginTop"]["magnitude"] == 72.0
    assert ds["marginBottom"]["magnitude"] == 72.0


@pytest.mark.asyncio
@respx.mock
async def test_update_document_style_page_size(
    server,
):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_document_style", {
            "page_width_pt": 612.0,
            "page_height_pt": 792.0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    ds = req0["updateDocumentStyle"]["documentStyle"]
    assert ds["pageSize"]["width"]["magnitude"] == 612.0
    assert ds["pageSize"]["height"]["magnitude"] == 792.0


@pytest.mark.asyncio
async def test_update_document_style_no_fields(
    server,
):
    with pytest.raises(
        Exception, match="style property",
    ):
        await server.call_tool(
            "gdocs_update_document_style", {},
        )


@pytest.mark.asyncio
@respx.mock
async def test_update_section_style(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_update_section_style", {
            "start_index": 1,
            "end_index": 50,
            "column_count": 2,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "updateSectionStyle" in req0
    ss = req0["updateSectionStyle"]
    assert len(ss["sectionStyle"]["columnProperties"]) == 2
    assert ss["range"]["startIndex"] == 1


@pytest.mark.asyncio
async def test_update_section_style_no_fields(
    server,
):
    with pytest.raises(
        Exception, match="style property",
    ):
        await server.call_tool(
            "gdocs_update_section_style", {
                "start_index": 1,
                "end_index": 50,
            },
        )


# ==========================================
# TIER 9: HEADERS, FOOTERS & FOOTNOTES
#         (5 tools)
# ==========================================


@pytest.mark.asyncio
@respx.mock
async def test_create_header(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_create_header", {
            "section_break_index": 0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "createHeader" in req0


@pytest.mark.asyncio
@respx.mock
async def test_create_footer(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_create_footer", {
            "section_break_index": 0,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "createFooter" in req0
    assert req0["createFooter"]["type"] == "DEFAULT"


@pytest.mark.asyncio
@respx.mock
async def test_delete_header(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_delete_header", {
            "header_id": "kix.hdr1",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "deleteHeader" in req0
    assert req0["deleteHeader"]["headerId"] == "kix.hdr1"


@pytest.mark.asyncio
@respx.mock
async def test_delete_footer(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_delete_footer", {
            "footer_id": "kix.ftr1",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "deleteFooter" in req0
    assert req0["deleteFooter"]["footerId"] == "kix.ftr1"


@pytest.mark.asyncio
@respx.mock
async def test_create_footnote(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_create_footnote", {
            "index": 5,
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "createFootnote" in req0
    assert req0["createFootnote"]["location"]["index"] == 5


# ==========================================
# TIER 10: REPLACE & IMAGE (2 tools)
# ==========================================


@pytest.mark.asyncio
@respx.mock
async def test_replace_named_range_content_by_id(
    server,
):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_replace_named_range_content", {
            "text": "new content",
            "named_range_id": "nr123",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "replaceNamedRangeContent" in req0
    rnr = req0["replaceNamedRangeContent"]
    assert rnr["text"] == "new content"
    assert rnr["namedRangeId"] == "nr123"


@pytest.mark.asyncio
@respx.mock
async def test_replace_named_range_content_by_name(
    server,
):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_replace_named_range_content", {
            "text": "new content",
            "name": "my_range",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    rnr = req0["replaceNamedRangeContent"]
    assert rnr["text"] == "new content"
    assert rnr["name"] == "my_range"


@pytest.mark.asyncio
async def test_replace_named_range_no_id_or_name(
    server,
):
    with pytest.raises(
        Exception,
        match="named_range_id or name",
    ):
        await server.call_tool(
            "gdocs_replace_named_range_content", {
                "text": "new content",
            },
        )


@pytest.mark.asyncio
@respx.mock
async def test_replace_image(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_replace_image", {
            "image_object_id": "kix.img1",
            "uri": "https://example.com/new.png",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert "replaceImage" in req0
    assert req0["replaceImage"]["imageObjectId"] == "kix.img1"
    assert req0["replaceImage"]["uri"] == "https://example.com/new.png"


@pytest.mark.asyncio
@respx.mock
async def test_replace_image_size_to_fit(server):
    route = respx.post(
        f"{BASE}/{DID}:batchUpdate",
    ).mock(return_value=BATCH_OK)
    _ok(await server.call_tool(
        "gdocs_replace_image", {
            "image_object_id": "kix.img1",
            "uri": "https://example.com/new.png",
            "image_replace_method": "SIZE_TO_FIT",
        },
    ))
    body = json.loads(route.calls[0].request.content)
    req0 = body["requests"][0]
    assert req0["replaceImage"]["imageReplaceMethod"] == "SIZE_TO_FIT"
