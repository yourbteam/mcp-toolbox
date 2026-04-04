"""Google Docs API v1 integration — documents, text, formatting, tables."""

import asyncio
import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import (
    GDOCS_DEFAULT_DOCUMENT_ID,
    GOOGLE_SERVICE_ACCOUNT_JSON,
)

logger = logging.getLogger(__name__)

_credentials = None
_client: httpx.AsyncClient | None = None

BASE = "https://docs.googleapis.com/v1/documents"


def _get_token() -> str:
    global _credentials
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ToolError(
            "GOOGLE_SERVICE_ACCOUNT_JSON not configured. "
            "Set it to the path of your service account "
            "JSON key file."
        )
    if _credentials is None:
        import google.auth.transport.requests
        from google.oauth2 import service_account

        _credentials = (
            service_account.Credentials
            .from_service_account_file(
                GOOGLE_SERVICE_ACCOUNT_JSON,
                scopes=[
                    "https://www.googleapis.com/auth/documents"
                ],
            )
        )
    if not _credentials.valid:
        import google.auth.transport.requests

        _credentials.refresh(
            google.auth.transport.requests.Request()
        )
    return _credentials.token


async def _get_client() -> httpx.AsyncClient:
    global _client
    token = await asyncio.to_thread(_get_token)
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=BASE, timeout=30.0
        )
    _client.headers["Authorization"] = f"Bearer {token}"
    return _client


def _did(override: str | None) -> str:
    did = override or GDOCS_DEFAULT_DOCUMENT_ID
    if not did:
        raise ToolError(
            "No document_id provided. Pass document_id "
            "or set GDOCS_DEFAULT_DOCUMENT_ID."
        )
    return did


def _location(
    index: int, segment_id: str = "",
) -> dict:
    loc: dict = {"index": index}
    if segment_id:
        loc["segmentId"] = segment_id
    return loc


def _range(
    start_index: int,
    end_index: int,
    segment_id: str = "",
) -> dict:
    r: dict = {
        "startIndex": start_index,
        "endIndex": end_index,
    }
    if segment_id:
        r["segmentId"] = segment_id
    return r


def _table_cell_location(
    table_start_index: int,
    row_index: int,
    column_index: int,
) -> dict:
    return {
        "tableStartLocation": {"index": table_start_index},
        "rowIndex": row_index,
        "columnIndex": column_index,
    }


def _table_range(
    table_start_index: int,
    row_index: int,
    column_index: int,
    row_span: int,
    column_span: int,
) -> dict:
    return {
        "tableCellLocation": _table_cell_location(
            table_start_index, row_index, column_index,
        ),
        "rowSpan": row_span,
        "columnSpan": column_span,
    }


def _pt(magnitude: float) -> dict:
    return {"magnitude": magnitude, "unit": "PT"}


async def _req(
    method: str,
    url: str,
    json_body: dict | None = None,
    params: dict | None = None,
) -> dict | list:
    client = await _get_client()
    kwargs: dict = {}
    if json_body is not None:
        kwargs["json"] = json_body
    if params:
        kwargs["params"] = params
    try:
        response = await client.request(
            method, url, **kwargs
        )
    except httpx.HTTPError as e:
        raise ToolError(
            f"Google Docs request failed: {e}"
        ) from e
    if response.status_code == 429:
        raise ToolError(
            "Google Docs rate limit exceeded. "
            "Retry after a short delay."
        )
    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
            msg = err.get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(
            f"Google Docs error "
            f"({response.status_code}): {msg}"
        )
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


async def _batch_update(
    document_id: str, requests: list[dict],
) -> dict:
    data = await _req(
        "POST",
        f"/{document_id}:batchUpdate",
        json_body={"requests": requests},
    )
    return data if isinstance(data, dict) else {"raw": data}


def register_tools(mcp: FastMCP) -> None:  # noqa: C901
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        logger.warning(
            "GOOGLE_SERVICE_ACCOUNT_JSON not set "
            "— Google Docs tools will fail."
        )

    # =========================================================
    # TIER 1: DOCUMENT OPERATIONS
    # =========================================================

    @mcp.tool()
    async def gdocs_create_document(
        title: str,
    ) -> str:
        """Create a new blank Google Docs document.
        Args:
            title: Document title
        """
        data = await _req(
            "POST", "", json_body={"title": title}
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdocs_get_document(
        document_id: str | None = None,
        suggestions_view_mode: str | None = None,
    ) -> str:
        """Get full document content and metadata.
        Args:
            document_id: Document ID (uses default if
                not provided)
            suggestions_view_mode: How to render
                suggestions: DEFAULT_FOR_CURRENT_ACCESS,
                SUGGESTIONS_INLINE,
                PREVIEW_SUGGESTIONS_ACCEPTED,
                PREVIEW_WITHOUT_SUGGESTIONS
        """
        did = _did(document_id)
        params: dict = {}
        if suggestions_view_mode is not None:
            params["suggestionsViewMode"] = (
                suggestions_view_mode
            )
        data = await _req(
            "GET", f"/{did}", params=params or None
        )
        return json.dumps(data)

    @mcp.tool()
    async def gdocs_batch_update(
        requests: list[dict],
        document_id: str | None = None,
    ) -> str:
        """Apply raw batchUpdate requests to a document.
        Args:
            requests: Array of request objects (see
                Google Docs API batchUpdate types)
            document_id: Document ID (uses default if
                not provided)
        """
        did = _did(document_id)
        result = await _batch_update(did, requests)
        return json.dumps(result)

    # =========================================================
    # TIER 2: TEXT CONTENT
    # =========================================================

    @mcp.tool()
    async def gdocs_insert_text(
        text: str,
        index: int,
        document_id: str | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Insert text at a specified index.
        Body starts at index 1. Use gdocs_get_document
        to find current indexes.
        Args:
            text: Text to insert
            index: 0-based index position (body starts
                at 1)
            document_id: Document ID (uses default if
                not provided)
            segment_id: Segment: empty for body, or
                header/footer/footnote ID
        """
        did = _did(document_id)
        req: dict = {
            "insertText": {
                "text": text,
                "location": _location(
                    index, segment_id or ""
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_delete_content(
        start_index: int,
        end_index: int,
        document_id: str | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Delete content within a specified range.
        Args:
            start_index: Start index (inclusive)
            end_index: End index (exclusive)
            document_id: Document ID (uses default if
                not provided)
            segment_id: Segment: empty for body, or
                header/footer/footnote ID
        """
        did = _did(document_id)
        req: dict = {
            "deleteContentRange": {
                "range": _range(
                    start_index,
                    end_index,
                    segment_id or "",
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_replace_all_text(
        find_text: str,
        replace_text: str,
        document_id: str | None = None,
        match_case: bool = True,
    ) -> str:
        """Find and replace all occurrences of text.
        Args:
            find_text: Text to search for
            replace_text: Replacement text
            document_id: Document ID (uses default if
                not provided)
            match_case: Case-sensitive search (default
                true)
        """
        did = _did(document_id)
        req: dict = {
            "replaceAllText": {
                "containsText": {
                    "text": find_text,
                    "matchCase": match_case,
                },
                "replaceText": replace_text,
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    # =========================================================
    # TIER 3: FORMATTING
    # =========================================================

    @mcp.tool()
    async def gdocs_update_text_style(
        start_index: int,
        end_index: int,
        document_id: str | None = None,
        bold: bool | None = None,
        italic: bool | None = None,
        underline: bool | None = None,
        strikethrough: bool | None = None,
        font_family: str | None = None,
        font_size_pt: float | None = None,
        foreground_color_red: float | None = None,
        foreground_color_green: float | None = None,
        foreground_color_blue: float | None = None,
        background_color_red: float | None = None,
        background_color_green: float | None = None,
        background_color_blue: float | None = None,
        link_url: str | None = None,
        small_caps: bool | None = None,
        superscript: bool | None = None,
        subscript: bool | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Update text formatting for a range.
        Args:
            start_index: Start index (inclusive)
            end_index: End index (exclusive)
            document_id: Document ID (uses default)
            bold: Set bold
            italic: Set italic
            underline: Set underline
            strikethrough: Set strikethrough
            font_family: Font name (e.g. Arial)
            font_size_pt: Font size in points
            foreground_color_red: Text color red 0-1
            foreground_color_green: Text color green 0-1
            foreground_color_blue: Text color blue 0-1
            background_color_red: Highlight red 0-1
            background_color_green: Highlight green 0-1
            background_color_blue: Highlight blue 0-1
            link_url: URL to link the text to
            small_caps: Set small caps
            superscript: Set superscript
            subscript: Set subscript
            segment_id: Segment ID (empty=body)
        """
        did = _did(document_id)
        style: dict = {}
        fields: list[str] = []

        if bold is not None:
            style["bold"] = bold
            fields.append("bold")
        if italic is not None:
            style["italic"] = italic
            fields.append("italic")
        if underline is not None:
            style["underline"] = underline
            fields.append("underline")
        if strikethrough is not None:
            style["strikethrough"] = strikethrough
            fields.append("strikethrough")
        if font_family is not None:
            style["weightedFontFamily"] = {
                "fontFamily": font_family
            }
            fields.append("weightedFontFamily")
        if font_size_pt is not None:
            style["fontSize"] = _pt(font_size_pt)
            fields.append("fontSize")
        if (
            foreground_color_red is not None
            or foreground_color_green is not None
            or foreground_color_blue is not None
        ):
            style["foregroundColor"] = {
                "color": {
                    "rgbColor": {
                        "red": foreground_color_red
                        or 0.0,
                        "green": foreground_color_green
                        or 0.0,
                        "blue": foreground_color_blue
                        or 0.0,
                    }
                }
            }
            fields.append("foregroundColor")
        if (
            background_color_red is not None
            or background_color_green is not None
            or background_color_blue is not None
        ):
            style["backgroundColor"] = {
                "color": {
                    "rgbColor": {
                        "red": background_color_red
                        or 0.0,
                        "green": background_color_green
                        or 0.0,
                        "blue": background_color_blue
                        or 0.0,
                    }
                }
            }
            fields.append("backgroundColor")
        if link_url is not None:
            style["link"] = {"url": link_url}
            fields.append("link")
        if small_caps is not None:
            style["smallCaps"] = small_caps
            fields.append("smallCaps")
        if superscript is not None and subscript is not None:
            raise ToolError(
                "Cannot set both superscript and subscript."
            )
        if superscript is not None:
            style["baselineOffset"] = (
                "SUPERSCRIPT" if superscript else "NONE"
            )
            fields.append("baselineOffset")
        if subscript is not None:
            style["baselineOffset"] = (
                "SUBSCRIPT" if subscript else "NONE"
            )
            fields.append("baselineOffset")

        if not fields:
            raise ToolError(
                "At least one style property must be set."
            )

        req: dict = {
            "updateTextStyle": {
                "range": _range(
                    start_index,
                    end_index,
                    segment_id or "",
                ),
                "textStyle": style,
                "fields": ",".join(fields),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_update_paragraph_style(
        start_index: int,
        end_index: int,
        document_id: str | None = None,
        named_style_type: str | None = None,
        alignment: str | None = None,
        line_spacing: float | None = None,
        space_above_pt: float | None = None,
        space_below_pt: float | None = None,
        indent_first_line_pt: float | None = None,
        indent_start_pt: float | None = None,
        indent_end_pt: float | None = None,
        keep_lines_together: bool | None = None,
        keep_with_next: bool | None = None,
        direction: str | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Update paragraph formatting for a range.
        Args:
            start_index: Start index (inclusive)
            end_index: End index (exclusive)
            document_id: Document ID (uses default)
            named_style_type: NORMAL_TEXT, TITLE,
                SUBTITLE, HEADING_1..HEADING_6
            alignment: START, CENTER, END, JUSTIFIED
            line_spacing: Percentage (100=single,
                200=double)
            space_above_pt: Space above in points
            space_below_pt: Space below in points
            indent_first_line_pt: First line indent pt
            indent_start_pt: Left/start indent in pt
            indent_end_pt: Right/end indent in pt
            keep_lines_together: No page break within
            keep_with_next: Keep with next paragraph
            direction: LEFT_TO_RIGHT or RIGHT_TO_LEFT
            segment_id: Segment ID (empty=body)
        """
        did = _did(document_id)
        style: dict = {}
        fields: list[str] = []

        if named_style_type is not None:
            style["namedStyleType"] = named_style_type
            fields.append("namedStyleType")
        if alignment is not None:
            style["alignment"] = alignment
            fields.append("alignment")
        if line_spacing is not None:
            style["lineSpacing"] = line_spacing
            fields.append("lineSpacing")
        if space_above_pt is not None:
            style["spaceAbove"] = _pt(space_above_pt)
            fields.append("spaceAbove")
        if space_below_pt is not None:
            style["spaceBelow"] = _pt(space_below_pt)
            fields.append("spaceBelow")
        if indent_first_line_pt is not None:
            style["indentFirstLine"] = _pt(
                indent_first_line_pt
            )
            fields.append("indentFirstLine")
        if indent_start_pt is not None:
            style["indentStart"] = _pt(indent_start_pt)
            fields.append("indentStart")
        if indent_end_pt is not None:
            style["indentEnd"] = _pt(indent_end_pt)
            fields.append("indentEnd")
        if keep_lines_together is not None:
            style["keepLinesTogether"] = (
                keep_lines_together
            )
            fields.append("keepLinesTogether")
        if keep_with_next is not None:
            style["keepWithNext"] = keep_with_next
            fields.append("keepWithNext")
        if direction is not None:
            style["direction"] = direction
            fields.append("direction")

        if not fields:
            raise ToolError(
                "At least one style property must be set."
            )

        req: dict = {
            "updateParagraphStyle": {
                "range": _range(
                    start_index,
                    end_index,
                    segment_id or "",
                ),
                "paragraphStyle": style,
                "fields": ",".join(fields),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    # =========================================================
    # TIER 4: STRUCTURAL ELEMENTS
    # =========================================================

    @mcp.tool()
    async def gdocs_insert_table(
        rows: int,
        columns: int,
        index: int,
        document_id: str | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Insert a table at a specified index.
        Args:
            rows: Number of rows
            columns: Number of columns
            index: Index position to insert the table
            document_id: Document ID (uses default)
            segment_id: Segment ID (empty=body)
        """
        did = _did(document_id)
        req: dict = {
            "insertTable": {
                "rows": rows,
                "columns": columns,
                "location": _location(
                    index, segment_id or ""
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_insert_table_row(
        table_start_index: int,
        row_index: int,
        column_index: int,
        document_id: str | None = None,
        insert_below: bool = True,
    ) -> str:
        """Insert a row into an existing table.
        Args:
            table_start_index: Start index of the table
            row_index: 0-based row index of ref cell
            column_index: 0-based column index of ref
                cell
            document_id: Document ID (uses default)
            insert_below: Insert below ref row (default
                true)
        """
        did = _did(document_id)
        req: dict = {
            "insertTableRow": {
                "tableCellLocation": _table_cell_location(
                    table_start_index,
                    row_index,
                    column_index,
                ),
                "insertBelow": insert_below,
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_insert_table_column(
        table_start_index: int,
        row_index: int,
        column_index: int,
        document_id: str | None = None,
        insert_right: bool = True,
    ) -> str:
        """Insert a column into an existing table.
        Args:
            table_start_index: Start index of the table
            row_index: 0-based row index of ref cell
            column_index: 0-based column index of ref
                cell
            document_id: Document ID (uses default)
            insert_right: Insert right of ref column
                (default true)
        """
        did = _did(document_id)
        req: dict = {
            "insertTableColumn": {
                "tableCellLocation": _table_cell_location(
                    table_start_index,
                    row_index,
                    column_index,
                ),
                "insertRight": insert_right,
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_delete_table_row(
        table_start_index: int,
        row_index: int,
        column_index: int,
        document_id: str | None = None,
    ) -> str:
        """Delete a row from a table.
        Args:
            table_start_index: Start index of the table
            row_index: 0-based row index of ref cell
            column_index: 0-based column index of ref
                cell
            document_id: Document ID (uses default)
        """
        did = _did(document_id)
        req: dict = {
            "deleteTableRow": {
                "tableCellLocation": _table_cell_location(
                    table_start_index,
                    row_index,
                    column_index,
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_delete_table_column(
        table_start_index: int,
        row_index: int,
        column_index: int,
        document_id: str | None = None,
    ) -> str:
        """Delete a column from a table.
        Args:
            table_start_index: Start index of the table
            row_index: 0-based row index of ref cell
            column_index: 0-based column index of ref
                cell
            document_id: Document ID (uses default)
        """
        did = _did(document_id)
        req: dict = {
            "deleteTableColumn": {
                "tableCellLocation": _table_cell_location(
                    table_start_index,
                    row_index,
                    column_index,
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_insert_inline_image(
        uri: str,
        index: int,
        document_id: str | None = None,
        width_pt: float | None = None,
        height_pt: float | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Insert an image from a URL at a specified
        index. Image URL must be publicly accessible.
        Args:
            uri: Public URL of the image
            index: Index position to insert the image
            document_id: Document ID (uses default)
            width_pt: Image width in points (72pt=1in)
            height_pt: Image height in points
            segment_id: Segment ID (empty=body)
        """
        did = _did(document_id)
        body: dict = {
            "uri": uri,
            "location": _location(
                index, segment_id or ""
            ),
        }
        if (
            width_pt is not None
            or height_pt is not None
        ):
            size: dict = {}
            if width_pt is not None:
                size["width"] = _pt(width_pt)
            if height_pt is not None:
                size["height"] = _pt(height_pt)
            body["objectSize"] = size
        req: dict = {"insertInlineImage": body}
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_insert_page_break(
        index: int,
        document_id: str | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Insert a page break at a specified index.
        Args:
            index: Index position for the page break
            document_id: Document ID (uses default)
            segment_id: Segment ID (empty=body)
        """
        did = _did(document_id)
        req: dict = {
            "insertPageBreak": {
                "location": _location(
                    index, segment_id or ""
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    # =========================================================
    # TIER 5: TABLE FORMATTING
    # =========================================================

    @mcp.tool()
    async def gdocs_update_table_column_properties(
        table_start_index: int,
        column_indices: list[int],
        width_pt: float,
        document_id: str | None = None,
        width_type: str = "EVENLY_DISTRIBUTED",
    ) -> str:
        """Set column width for table columns.
        Args:
            table_start_index: Start index of the table
            column_indices: 0-based column indices
            width_pt: Column width in points
            document_id: Document ID (uses default)
            width_type: EVENLY_DISTRIBUTED or
                FIXED_WIDTH
        """
        did = _did(document_id)
        req: dict = {
            "updateTableColumnProperties": {
                "tableStartLocation": {
                    "index": table_start_index
                },
                "columnIndices": column_indices,
                "tableColumnProperties": {
                    "widthType": width_type,
                    "width": _pt(width_pt),
                },
                "fields": "widthType,width",
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_update_table_cell_style(
        table_start_index: int,
        row_start: int,
        row_end: int,
        column_start: int,
        column_end: int,
        document_id: str | None = None,
        background_color_red: float | None = None,
        background_color_green: float | None = None,
        background_color_blue: float | None = None,
        padding_top_pt: float | None = None,
        padding_bottom_pt: float | None = None,
        padding_left_pt: float | None = None,
        padding_right_pt: float | None = None,
        content_alignment: str | None = None,
    ) -> str:
        """Update cell formatting for a range of cells.
        Args:
            table_start_index: Start index of the table
            row_start: Start row index (inclusive, 0)
            row_end: End row index (exclusive)
            column_start: Start column index (inclusive)
            column_end: End column index (exclusive)
            document_id: Document ID (uses default)
            background_color_red: Background red 0-1
            background_color_green: Background green 0-1
            background_color_blue: Background blue 0-1
            padding_top_pt: Top padding in points
            padding_bottom_pt: Bottom padding in points
            padding_left_pt: Left padding in points
            padding_right_pt: Right padding in points
            content_alignment: TOP, MIDDLE, or BOTTOM
        """
        did = _did(document_id)
        style: dict = {}
        fields: list[str] = []

        if (
            background_color_red is not None
            or background_color_green is not None
            or background_color_blue is not None
        ):
            style["backgroundColor"] = {
                "color": {
                    "rgbColor": {
                        "red": background_color_red
                        or 0.0,
                        "green": background_color_green
                        or 0.0,
                        "blue": background_color_blue
                        or 0.0,
                    }
                }
            }
            fields.append("backgroundColor")
        if padding_top_pt is not None:
            style["paddingTop"] = _pt(padding_top_pt)
            fields.append("paddingTop")
        if padding_bottom_pt is not None:
            style["paddingBottom"] = _pt(
                padding_bottom_pt
            )
            fields.append("paddingBottom")
        if padding_left_pt is not None:
            style["paddingLeft"] = _pt(padding_left_pt)
            fields.append("paddingLeft")
        if padding_right_pt is not None:
            style["paddingRight"] = _pt(
                padding_right_pt
            )
            fields.append("paddingRight")
        if content_alignment is not None:
            style["contentAlignment"] = (
                content_alignment
            )
            fields.append("contentAlignment")

        if not fields:
            raise ToolError(
                "At least one style property must be set."
            )

        row_span = row_end - row_start
        col_span = column_end - column_start
        req: dict = {
            "updateTableCellStyle": {
                "tableRange": _table_range(
                    table_start_index,
                    row_start,
                    column_start,
                    row_span,
                    col_span,
                ),
                "tableCellStyle": style,
                "fields": ",".join(fields),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_update_table_row_style(
        table_start_index: int,
        row_index: int,
        min_row_height_pt: float,
        document_id: str | None = None,
    ) -> str:
        """Update row height for a table row.
        Args:
            table_start_index: Start index of the table
            row_index: 0-based row index to update
            min_row_height_pt: Minimum row height in pt
            document_id: Document ID (uses default)
        """
        did = _did(document_id)
        req: dict = {
            "updateTableRowStyle": {
                "tableStartLocation": {
                    "index": table_start_index
                },
                "rowIndex": row_index,
                "tableRowStyle": {
                    "minRowHeight": _pt(
                        min_row_height_pt
                    ),
                },
                "fields": "minRowHeight",
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_merge_table_cells(
        table_start_index: int,
        row_index: int,
        column_index: int,
        row_span: int,
        column_span: int,
        document_id: str | None = None,
    ) -> str:
        """Merge a rectangular range of table cells.
        Args:
            table_start_index: Start index of the table
            row_index: 0-based row of top-left cell
            column_index: 0-based col of top-left cell
            row_span: Number of rows to merge
            column_span: Number of columns to merge
            document_id: Document ID (uses default)
        """
        did = _did(document_id)
        req: dict = {
            "mergeTableCells": {
                "tableRange": _table_range(
                    table_start_index,
                    row_index,
                    column_index,
                    row_span,
                    column_span,
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_unmerge_table_cells(
        table_start_index: int,
        row_index: int,
        column_index: int,
        row_span: int,
        column_span: int,
        document_id: str | None = None,
    ) -> str:
        """Unmerge previously merged table cells.
        Args:
            table_start_index: Start index of the table
            row_index: 0-based row of top-left cell
            column_index: 0-based col of top-left cell
            row_span: Number of rows in merged region
            column_span: Number of cols in merged region
            document_id: Document ID (uses default)
        """
        did = _did(document_id)
        req: dict = {
            "unmergeTableCells": {
                "tableRange": _table_range(
                    table_start_index,
                    row_index,
                    column_index,
                    row_span,
                    column_span,
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_pin_table_header_rows(
        table_start_index: int,
        pinned_header_row_count: int,
        document_id: str | None = None,
    ) -> str:
        """Pin rows as repeating header rows in a table.
        Args:
            table_start_index: Start index of the table
            pinned_header_row_count: Rows to pin (0 to
                unpin)
            document_id: Document ID (uses default)
        """
        did = _did(document_id)
        req: dict = {
            "pinTableHeaderRows": {
                "tableStartLocation": {
                    "index": table_start_index
                },
                "pinnedHeaderRowsCount": (
                    pinned_header_row_count
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    # =========================================================
    # TIER 6: NAMED RANGES
    # =========================================================

    @mcp.tool()
    async def gdocs_create_named_range(
        name: str,
        start_index: int,
        end_index: int,
        document_id: str | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Create a named range over a content range.
        Args:
            name: Name for the range
            start_index: Start index (inclusive)
            end_index: End index (exclusive)
            document_id: Document ID (uses default)
            segment_id: Segment ID (empty=body)
        """
        did = _did(document_id)
        req: dict = {
            "createNamedRange": {
                "name": name,
                "range": _range(
                    start_index,
                    end_index,
                    segment_id or "",
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_delete_named_range(
        document_id: str | None = None,
        named_range_id: str | None = None,
        name: str | None = None,
    ) -> str:
        """Delete a named range by ID or by name.
        Args:
            document_id: Document ID (uses default)
            named_range_id: Named range ID to delete
            name: Named range name to delete
        """
        if (
            named_range_id is None
            and name is None
        ):
            raise ToolError(
                "Provide named_range_id or name."
            )
        did = _did(document_id)
        body: dict = {}
        if named_range_id is not None:
            body["namedRangeId"] = named_range_id
        if name is not None:
            body["name"] = name
        req: dict = {"deleteNamedRange": body}
        result = await _batch_update(did, [req])
        return json.dumps(result)

    # =========================================================
    # TIER 7: LISTS / BULLETS
    # =========================================================

    @mcp.tool()
    async def gdocs_create_paragraph_bullets(
        start_index: int,
        end_index: int,
        bullet_preset: str,
        document_id: str | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Add bullet/numbered list formatting to
        paragraphs. Presets include
        BULLET_DISC_CIRCLE_SQUARE,
        NUMBERED_DECIMAL_ALPHA_ROMAN, etc.
        Args:
            start_index: Start index (inclusive)
            end_index: End index (exclusive)
            bullet_preset: Bullet preset name
            document_id: Document ID (uses default)
            segment_id: Segment ID (empty=body)
        """
        did = _did(document_id)
        req: dict = {
            "createParagraphBullets": {
                "range": _range(
                    start_index,
                    end_index,
                    segment_id or "",
                ),
                "bulletPreset": bullet_preset,
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_delete_paragraph_bullets(
        start_index: int,
        end_index: int,
        document_id: str | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Remove bullet/list formatting from
        paragraphs.
        Args:
            start_index: Start index (inclusive)
            end_index: End index (exclusive)
            document_id: Document ID (uses default)
            segment_id: Segment ID (empty=body)
        """
        did = _did(document_id)
        req: dict = {
            "deleteParagraphBullets": {
                "range": _range(
                    start_index,
                    end_index,
                    segment_id or "",
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    # =========================================================
    # TIER 8: SECTION & DOCUMENT STYLE
    # =========================================================

    @mcp.tool()
    async def gdocs_insert_section_break(
        index: int,
        document_id: str | None = None,
        section_type: str = "CONTINUOUS",
        segment_id: str | None = None,
    ) -> str:
        """Insert a section break at a specified index.
        Args:
            index: Index position for the section break
            document_id: Document ID (uses default)
            section_type: CONTINUOUS or NEXT_PAGE
            segment_id: Segment ID (empty=body)
        """
        did = _did(document_id)
        req: dict = {
            "insertSectionBreak": {
                "location": _location(
                    index, segment_id or ""
                ),
                "sectionType": section_type,
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_update_document_style(
        document_id: str | None = None,
        page_width_pt: float | None = None,
        page_height_pt: float | None = None,
        margin_top_pt: float | None = None,
        margin_bottom_pt: float | None = None,
        margin_left_pt: float | None = None,
        margin_right_pt: float | None = None,
        background_color_red: float | None = None,
        background_color_green: float | None = None,
        background_color_blue: float | None = None,
        use_first_page_header_footer: (
            bool | None
        ) = None,
        default_header_id: str | None = None,
        default_footer_id: str | None = None,
    ) -> str:
        """Update page-level document styles.
        Args:
            document_id: Document ID (uses default)
            page_width_pt: Page width in points
            page_height_pt: Page height in points
            margin_top_pt: Top margin in points
            margin_bottom_pt: Bottom margin in points
            margin_left_pt: Left margin in points
            margin_right_pt: Right margin in points
            background_color_red: Background red 0-1
            background_color_green: Background green 0-1
            background_color_blue: Background blue 0-1
            use_first_page_header_footer: First page
                has different header/footer
            default_header_id: Default header ID
            default_footer_id: Default footer ID
        """
        did = _did(document_id)
        style: dict = {}
        fields: list[str] = []

        if (
            page_width_pt is not None
            or page_height_pt is not None
        ):
            page_size: dict = {}
            if page_width_pt is not None:
                page_size["width"] = _pt(page_width_pt)
            if page_height_pt is not None:
                page_size["height"] = _pt(
                    page_height_pt
                )
            style["pageSize"] = page_size
            fields.append("pageSize")
        if margin_top_pt is not None:
            style["marginTop"] = _pt(margin_top_pt)
            fields.append("marginTop")
        if margin_bottom_pt is not None:
            style["marginBottom"] = _pt(
                margin_bottom_pt
            )
            fields.append("marginBottom")
        if margin_left_pt is not None:
            style["marginLeft"] = _pt(margin_left_pt)
            fields.append("marginLeft")
        if margin_right_pt is not None:
            style["marginRight"] = _pt(margin_right_pt)
            fields.append("marginRight")
        if (
            background_color_red is not None
            or background_color_green is not None
            or background_color_blue is not None
        ):
            style["background"] = {
                "color": {
                    "rgbColor": {
                        "red": background_color_red
                        or 0.0,
                        "green": background_color_green
                        or 0.0,
                        "blue": background_color_blue
                        or 0.0,
                    }
                }
            }
            fields.append("background")
        if use_first_page_header_footer is not None:
            style["useFirstPageHeaderFooter"] = (
                use_first_page_header_footer
            )
            fields.append("useFirstPageHeaderFooter")
        if default_header_id is not None:
            style["defaultHeaderId"] = (
                default_header_id
            )
            fields.append("defaultHeaderId")
        if default_footer_id is not None:
            style["defaultFooterId"] = (
                default_footer_id
            )
            fields.append("defaultFooterId")

        if not fields:
            raise ToolError(
                "At least one style property must be set."
            )

        req: dict = {
            "updateDocumentStyle": {
                "documentStyle": style,
                "fields": ",".join(fields),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_update_section_style(
        start_index: int,
        end_index: int,
        document_id: str | None = None,
        column_count: int | None = None,
        column_separator_style: str | None = None,
        content_direction: str | None = None,
        section_type: str | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Update section-level styles (columns, etc.).
        Args:
            start_index: Start index (inclusive)
            end_index: End index (exclusive)
            document_id: Document ID (uses default)
            column_count: Number of columns (1, 2, 3)
            column_separator_style: NONE or
                BETWEEN_EACH_COLUMN
            content_direction: LEFT_TO_RIGHT or
                RIGHT_TO_LEFT
            section_type: CONTINUOUS or NEXT_PAGE
            segment_id: Segment ID (empty=body)
        """
        did = _did(document_id)
        style: dict = {}
        fields: list[str] = []

        if column_count is not None:
            style["columnProperties"] = [
                {} for _ in range(column_count)
            ]
            fields.append("columnProperties")
        if column_separator_style is not None:
            style["columnSeparatorStyle"] = (
                column_separator_style
            )
            fields.append("columnSeparatorStyle")
        if content_direction is not None:
            style["contentDirection"] = (
                content_direction
            )
            fields.append("contentDirection")
        if section_type is not None:
            style["sectionType"] = section_type
            fields.append("sectionType")

        if not fields:
            raise ToolError(
                "At least one style property must be set."
            )

        req: dict = {
            "updateSectionStyle": {
                "range": _range(
                    start_index,
                    end_index,
                    segment_id or "",
                ),
                "sectionStyle": style,
                "fields": ",".join(fields),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    # =========================================================
    # TIER 9: HEADERS, FOOTERS & FOOTNOTES
    # =========================================================

    @mcp.tool()
    async def gdocs_create_header(
        section_break_index: int,
        document_id: str | None = None,
        type: str = "DEFAULT",
    ) -> str:
        """Create a header for a section.
        Args:
            section_break_index: Index of the section
                break (0 for first section)
            document_id: Document ID (uses default)
            type: DEFAULT or FIRST_PAGE
        """
        did = _did(document_id)
        req: dict = {
            "createHeader": {
                "sectionBreakLocation": {
                    "index": section_break_index,
                    "segmentId": "",
                },
                "type": type,
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_create_footer(
        section_break_index: int,
        document_id: str | None = None,
        type: str = "DEFAULT",
    ) -> str:
        """Create a footer for a section.
        Args:
            section_break_index: Index of the section
                break (0 for first section)
            document_id: Document ID (uses default)
            type: DEFAULT or FIRST_PAGE
        """
        did = _did(document_id)
        req: dict = {
            "createFooter": {
                "sectionBreakLocation": {
                    "index": section_break_index,
                    "segmentId": "",
                },
                "type": type,
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_delete_header(
        header_id: str,
        document_id: str | None = None,
    ) -> str:
        """Delete a header by ID.
        Args:
            header_id: Header ID to delete
            document_id: Document ID (uses default)
        """
        did = _did(document_id)
        req: dict = {
            "deleteHeader": {"headerId": header_id}
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_delete_footer(
        footer_id: str,
        document_id: str | None = None,
    ) -> str:
        """Delete a footer by ID.
        Args:
            footer_id: Footer ID to delete
            document_id: Document ID (uses default)
        """
        did = _did(document_id)
        req: dict = {
            "deleteFooter": {"footerId": footer_id}
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_create_footnote(
        index: int,
        document_id: str | None = None,
        segment_id: str | None = None,
    ) -> str:
        """Create a footnote at a specified index.
        Use gdocs_insert_text with the returned
        footnoteId as segment_id to add content.
        Args:
            index: Index for the footnote reference
            document_id: Document ID (uses default)
            segment_id: Segment ID (empty=body)
        """
        did = _did(document_id)
        req: dict = {
            "createFootnote": {
                "location": _location(
                    index, segment_id or ""
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    # =========================================================
    # TIER 10: REPLACE & IMAGE
    # =========================================================

    @mcp.tool()
    async def gdocs_replace_named_range_content(
        text: str,
        document_id: str | None = None,
        named_range_id: str | None = None,
        name: str | None = None,
    ) -> str:
        """Replace content of all instances of a named
        range.
        Args:
            text: Replacement text
            document_id: Document ID (uses default)
            named_range_id: Named range ID
            name: Named range name
        """
        if (
            named_range_id is None
            and name is None
        ):
            raise ToolError(
                "Provide named_range_id or name."
            )
        did = _did(document_id)
        body: dict = {"text": text}
        if named_range_id is not None:
            body["namedRangeId"] = named_range_id
        if name is not None:
            body["name"] = name
        req: dict = {
            "replaceNamedRangeContent": body
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)

    @mcp.tool()
    async def gdocs_replace_image(
        image_object_id: str,
        uri: str,
        document_id: str | None = None,
        image_replace_method: str = "CENTER_CROP",
    ) -> str:
        """Replace an existing inline image with a new
        image URL.
        Args:
            image_object_id: Object ID of image to
                replace (from inlineObjects in
                gdocs_get_document)
            uri: Public URL of the replacement image
            document_id: Document ID (uses default)
            image_replace_method: CENTER_CROP or
                SIZE_TO_FIT
        """
        did = _did(document_id)
        req: dict = {
            "replaceImage": {
                "imageObjectId": image_object_id,
                "uri": uri,
                "imageReplaceMethod": (
                    image_replace_method
                ),
            }
        }
        result = await _batch_update(did, [req])
        return json.dumps(result)
