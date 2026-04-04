"""Google Sheets integration — spreadsheet, sheet, values, formatting, charts."""

import asyncio
import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import (
    GOOGLE_SERVICE_ACCOUNT_JSON,
    GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID,
)

logger = logging.getLogger(__name__)

_credentials = None
_client: httpx.AsyncClient | None = None

BASE = "https://sheets.googleapis.com/v4/spreadsheets"


def _get_token() -> str:
    global _credentials
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ToolError(
            "GOOGLE_SERVICE_ACCOUNT_JSON not configured. "
            "Set it to the path of your service account JSON key file."
        )
    if _credentials is None:
        import google.auth.transport.requests
        from google.oauth2 import service_account

        _credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
    if not _credentials.valid:
        import google.auth.transport.requests

        _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token


async def _get_client() -> httpx.AsyncClient:
    global _client
    token = await asyncio.to_thread(_get_token)
    if _client is None:
        _client = httpx.AsyncClient(base_url=BASE, timeout=30.0)
    _client.headers["Authorization"] = f"Bearer {token}"
    return _client


def _success(sc: int, **kw) -> str:
    return json.dumps({"status": "success", "status_code": sc, **kw})


def _sid(override: str | None) -> str:
    sid = override or GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID
    if not sid:
        raise ToolError(
            "No spreadsheet_id provided. Pass spreadsheet_id or set "
            "GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID."
        )
    return sid


def _grid_range(
    sheet_id: int,
    start_row: int | None = None,
    end_row: int | None = None,
    start_column: int | None = None,
    end_column: int | None = None,
) -> dict:
    gr: dict = {"sheetId": sheet_id}
    if start_row is not None:
        gr["startRowIndex"] = start_row
    if end_row is not None:
        gr["endRowIndex"] = end_row
    if start_column is not None:
        gr["startColumnIndex"] = start_column
    if end_column is not None:
        gr["endColumnIndex"] = end_column
    return gr


async def _req(
    method: str, url: str, json_body: dict | None = None,
    params: dict | None = None,
) -> dict | list:
    client = await _get_client()
    kwargs: dict = {}
    if json_body is not None:
        kwargs["json"] = json_body
    if params:
        kwargs["params"] = params
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"Google Sheets request failed: {e}") from e
    if response.status_code == 429:
        raise ToolError("Google Sheets rate limit exceeded.")
    if response.status_code >= 400:
        try:
            err = response.json().get("error", {})
            msg = err.get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(
            f"Google Sheets error ({response.status_code}): {msg}"
        )
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


async def _batch_update(spreadsheet_id: str, requests: list[dict]) -> dict:
    data = await _req(
        "POST", f"/{spreadsheet_id}:batchUpdate",
        json_body={"requests": requests},
    )
    return data if isinstance(data, dict) else {"raw": data}


def register_tools(mcp: FastMCP) -> None:
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        logger.warning(
            "GOOGLE_SERVICE_ACCOUNT_JSON not set — Sheets tools will fail."
        )

    # === TIER 1: SPREADSHEET OPERATIONS ===

    @mcp.tool()
    async def sheets_create_spreadsheet(
        title: str,
        sheet_titles: list[str] | None = None,
        locale: str | None = None,
        time_zone: str | None = None,
    ) -> str:
        """Create a new Google Sheets spreadsheet.
        Args:
            title: Spreadsheet title
            sheet_titles: Names for initial sheets
            locale: Locale (e.g., en_US)
            time_zone: Time zone (e.g., America/New_York)
        """
        props: dict = {"title": title}
        if locale is not None:
            props["locale"] = locale
        if time_zone is not None:
            props["timeZone"] = time_zone
        body: dict = {"properties": props}
        if sheet_titles:
            body["sheets"] = [
                {"properties": {"title": t}} for t in sheet_titles
            ]
        data = await _req("POST", "", json_body=body)
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_get_spreadsheet(
        spreadsheet_id: str | None = None,
        include_grid_data: bool = False,
        ranges: list[str] | None = None,
    ) -> str:
        """Get spreadsheet metadata.
        Args:
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            include_grid_data: Include cell data
            ranges: Ranges to include (A1 notation)
        """
        sid = _sid(spreadsheet_id)
        p: dict = {}
        if include_grid_data:
            p["includeGridData"] = "true"
        if ranges:
            p["ranges"] = ranges
        data = await _req("GET", f"/{sid}", params=p or None)
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_batch_update_spreadsheet(
        requests: list[dict],
        spreadsheet_id: str | None = None,
    ) -> str:
        """Apply structural/formatting updates to a spreadsheet.
        Args:
            requests: Array of request objects (Google Sheets API format)
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
        """
        sid = _sid(spreadsheet_id)
        data = await _batch_update(sid, requests)
        return _success(200, data=data)

    # === TIER 2: SHEET OPERATIONS ===

    @mcp.tool()
    async def sheets_add_sheet(
        title: str,
        spreadsheet_id: str | None = None,
        row_count: int | None = None,
        column_count: int | None = None,
        index: int | None = None,
        tab_color_red: float | None = None,
        tab_color_green: float | None = None,
        tab_color_blue: float | None = None,
    ) -> str:
        """Add a new sheet (tab) to a spreadsheet.
        Args:
            title: Sheet name
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            row_count: Number of rows (default 1000)
            column_count: Number of columns (default 26)
            index: Position (0-based)
            tab_color_red: Tab color red (0.0-1.0)
            tab_color_green: Tab color green (0.0-1.0)
            tab_color_blue: Tab color blue (0.0-1.0)
        """
        sid = _sid(spreadsheet_id)
        props: dict = {"title": title}
        gp: dict = {}
        if row_count is not None:
            gp["rowCount"] = row_count
        if column_count is not None:
            gp["columnCount"] = column_count
        if gp:
            props["gridProperties"] = gp
        if index is not None:
            props["index"] = index
        if any(
            c is not None
            for c in [tab_color_red, tab_color_green, tab_color_blue]
        ):
            props["tabColorStyle"] = {
                "rgbColor": {
                    "red": tab_color_red or 0.0,
                    "green": tab_color_green or 0.0,
                    "blue": tab_color_blue or 0.0,
                }
            }
        data = await _batch_update(
            sid, [{"addSheet": {"properties": props}}]
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_delete_sheet(
        sheet_id: int, spreadsheet_id: str | None = None,
    ) -> str:
        """Delete a sheet (tab) from a spreadsheet.
        Args:
            sheet_id: Sheet ID (0-based integer)
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
        """
        sid = _sid(spreadsheet_id)
        data = await _batch_update(
            sid, [{"deleteSheet": {"sheetId": sheet_id}}]
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_copy_sheet(
        sheet_id: int,
        destination_spreadsheet_id: str,
        source_spreadsheet_id: str | None = None,
    ) -> str:
        """Copy a sheet to another spreadsheet.
        Args:
            sheet_id: Sheet ID to copy
            destination_spreadsheet_id: Target spreadsheet ID
            source_spreadsheet_id: Source spreadsheet ID (uses default)
        """
        sid = _sid(source_spreadsheet_id)
        data = await _req(
            "POST",
            f"/{sid}/sheets/{sheet_id}:copyTo",
            json_body={
                "destinationSpreadsheetId": destination_spreadsheet_id,
            },
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_rename_sheet(
        sheet_id: int,
        title: str,
        spreadsheet_id: str | None = None,
    ) -> str:
        """Rename a sheet (tab).
        Args:
            sheet_id: Sheet ID to rename
            title: New sheet name
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
        """
        sid = _sid(spreadsheet_id)
        data = await _batch_update(sid, [{
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "title": title},
                "fields": "title",
            }
        }])
        return _success(200, data=data)

    # === TIER 3: CELL/RANGE VALUE OPERATIONS ===

    @mcp.tool()
    async def sheets_read_values(
        range: str,
        spreadsheet_id: str | None = None,
        value_render_option: str | None = None,
        date_time_render_option: str | None = None,
        major_dimension: str | None = None,
    ) -> str:
        """Read values from a range.
        Args:
            range: A1 notation range (e.g., Sheet1!A1:D10)
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            value_render_option: FORMATTED_VALUE, UNFORMATTED_VALUE, FORMULA
            date_time_render_option: SERIAL_NUMBER or FORMATTED_STRING
            major_dimension: ROWS or COLUMNS
        """
        sid = _sid(spreadsheet_id)
        p: dict = {}
        if value_render_option is not None:
            p["valueRenderOption"] = value_render_option
        if date_time_render_option is not None:
            p["dateTimeRenderOption"] = date_time_render_option
        if major_dimension is not None:
            p["majorDimension"] = major_dimension
        data = await _req(
            "GET", f"/{sid}/values/{range}", params=p or None,
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_write_values(
        range: str,
        values: list[list],
        spreadsheet_id: str | None = None,
        value_input_option: str = "USER_ENTERED",
        major_dimension: str = "ROWS",
    ) -> str:
        """Write values to a range (overwrites existing data).
        Args:
            range: A1 notation range
            values: 2D array of values
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            value_input_option: USER_ENTERED or RAW
            major_dimension: ROWS or COLUMNS
        """
        sid = _sid(spreadsheet_id)
        data = await _req(
            "PUT",
            f"/{sid}/values/{range}",
            json_body={
                "range": range,
                "majorDimension": major_dimension,
                "values": values,
            },
            params={"valueInputOption": value_input_option},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_append_values(
        range: str,
        values: list[list],
        spreadsheet_id: str | None = None,
        value_input_option: str = "USER_ENTERED",
        insert_data_option: str = "OVERWRITE",
        major_dimension: str = "ROWS",
    ) -> str:
        """Append values after the last row of data.
        Args:
            range: A1 notation range to find table (e.g., Sheet1!A:D)
            values: 2D array to append
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            value_input_option: USER_ENTERED or RAW
            insert_data_option: OVERWRITE or INSERT_ROWS
            major_dimension: ROWS or COLUMNS
        """
        sid = _sid(spreadsheet_id)
        data = await _req(
            "POST",
            f"/{sid}/values/{range}:append",
            json_body={"majorDimension": major_dimension, "values": values},
            params={
                "valueInputOption": value_input_option,
                "insertDataOption": insert_data_option,
            },
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_clear_values(
        range: str, spreadsheet_id: str | None = None,
    ) -> str:
        """Clear values from a range (formatting preserved).
        Args:
            range: A1 notation range to clear
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
        """
        sid = _sid(spreadsheet_id)
        data = await _req("POST", f"/{sid}/values/{range}:clear", json_body={})
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_batch_get_values(
        ranges: list[str],
        spreadsheet_id: str | None = None,
        value_render_option: str | None = None,
        date_time_render_option: str | None = None,
        major_dimension: str | None = None,
    ) -> str:
        """Read values from multiple ranges.
        Args:
            ranges: List of A1 notation ranges
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            value_render_option: FORMATTED_VALUE, UNFORMATTED_VALUE, FORMULA
            date_time_render_option: SERIAL_NUMBER or FORMATTED_STRING
            major_dimension: ROWS or COLUMNS
        """
        sid = _sid(spreadsheet_id)
        p: dict = {"ranges": ranges}
        if value_render_option is not None:
            p["valueRenderOption"] = value_render_option
        if date_time_render_option is not None:
            p["dateTimeRenderOption"] = date_time_render_option
        if major_dimension is not None:
            p["majorDimension"] = major_dimension
        data = await _req("GET", f"/{sid}/values:batchGet", params=p)
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_batch_update_values(
        data: list[dict],
        spreadsheet_id: str | None = None,
        value_input_option: str = "USER_ENTERED",
    ) -> str:
        """Write values to multiple ranges.
        Args:
            data: Array of {range, values} objects
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            value_input_option: USER_ENTERED or RAW
        """
        sid = _sid(spreadsheet_id)
        result = await _req(
            "POST",
            f"/{sid}/values:batchUpdate",
            json_body={
                "valueInputOption": value_input_option,
                "data": data,
            },
        )
        return _success(200, data=result)

    @mcp.tool()
    async def sheets_batch_clear_values(
        ranges: list[str], spreadsheet_id: str | None = None,
    ) -> str:
        """Clear values from multiple ranges.
        Args:
            ranges: List of A1 notation ranges to clear
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
        """
        sid = _sid(spreadsheet_id)
        result = await _req(
            "POST",
            f"/{sid}/values:batchClear",
            json_body={"ranges": ranges},
        )
        return _success(200, data=result)

    # === TIER 4: FORMATTING ===

    @mcp.tool()
    async def sheets_format_cells(
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_column: int,
        end_column: int,
        spreadsheet_id: str | None = None,
        bold: bool | None = None,
        italic: bool | None = None,
        underline: bool | None = None,
        strikethrough: bool | None = None,
        font_size: int | None = None,
        font_family: str | None = None,
        font_color_red: float | None = None,
        font_color_green: float | None = None,
        font_color_blue: float | None = None,
        bg_color_red: float | None = None,
        bg_color_green: float | None = None,
        bg_color_blue: float | None = None,
        horizontal_alignment: str | None = None,
        vertical_alignment: str | None = None,
        wrap_strategy: str | None = None,
        number_format_type: str | None = None,
        number_format_pattern: str | None = None,
    ) -> str:
        """Apply formatting to a cell range.
        Args:
            sheet_id: Sheet ID
            start_row: Start row (0-based inclusive)
            end_row: End row (0-based exclusive)
            start_column: Start column (0-based inclusive)
            end_column: End column (0-based exclusive)
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            bold: Bold text
            italic: Italic text
            underline: Underline text
            strikethrough: Strikethrough text
            font_size: Font size in points
            font_family: Font family
            font_color_red: Font color red (0.0-1.0)
            font_color_green: Font color green (0.0-1.0)
            font_color_blue: Font color blue (0.0-1.0)
            bg_color_red: Background red (0.0-1.0)
            bg_color_green: Background green (0.0-1.0)
            bg_color_blue: Background blue (0.0-1.0)
            horizontal_alignment: LEFT, CENTER, RIGHT
            vertical_alignment: TOP, MIDDLE, BOTTOM
            wrap_strategy: OVERFLOW_CELL, LEGACY_WRAP, CLIP, WRAP
            number_format_type: TEXT, NUMBER, PERCENT, CURRENCY, etc.
            number_format_pattern: Custom pattern (e.g., #,##0.00)
        """
        sid = _sid(spreadsheet_id)
        fmt: dict = {}
        fields: list[str] = []
        tf: dict = {}
        if bold is not None:
            tf["bold"] = bold
            fields.append("userEnteredFormat.textFormat.bold")
        if italic is not None:
            tf["italic"] = italic
            fields.append("userEnteredFormat.textFormat.italic")
        if underline is not None:
            tf["underline"] = underline
            fields.append("userEnteredFormat.textFormat.underline")
        if strikethrough is not None:
            tf["strikethrough"] = strikethrough
            fields.append("userEnteredFormat.textFormat.strikethrough")
        if font_size is not None:
            tf["fontSize"] = font_size
            fields.append("userEnteredFormat.textFormat.fontSize")
        if font_family is not None:
            tf["fontFamily"] = font_family
            fields.append("userEnteredFormat.textFormat.fontFamily")
        if any(
            c is not None
            for c in [font_color_red, font_color_green, font_color_blue]
        ):
            tf["foregroundColorStyle"] = {
                "rgbColor": {
                    "red": font_color_red or 0.0,
                    "green": font_color_green or 0.0,
                    "blue": font_color_blue or 0.0,
                }
            }
            fields.append(
                "userEnteredFormat.textFormat.foregroundColorStyle"
            )
        if tf:
            fmt["textFormat"] = tf
        if any(
            c is not None
            for c in [bg_color_red, bg_color_green, bg_color_blue]
        ):
            fmt["backgroundColorStyle"] = {
                "rgbColor": {
                    "red": bg_color_red or 0.0,
                    "green": bg_color_green or 0.0,
                    "blue": bg_color_blue or 0.0,
                }
            }
            fields.append("userEnteredFormat.backgroundColorStyle")
        if horizontal_alignment is not None:
            fmt["horizontalAlignment"] = horizontal_alignment
            fields.append("userEnteredFormat.horizontalAlignment")
        if vertical_alignment is not None:
            fmt["verticalAlignment"] = vertical_alignment
            fields.append("userEnteredFormat.verticalAlignment")
        if wrap_strategy is not None:
            fmt["wrapStrategy"] = wrap_strategy
            fields.append("userEnteredFormat.wrapStrategy")
        if number_format_type is not None:
            nf: dict = {"type": number_format_type}
            if number_format_pattern is not None:
                nf["pattern"] = number_format_pattern
            fmt["numberFormat"] = nf
            fields.append("userEnteredFormat.numberFormat")
        if not fields:
            raise ToolError("At least one formatting property must be provided.")
        data = await _batch_update(sid, [{
            "repeatCell": {
                "range": _grid_range(
                    sheet_id, start_row, end_row, start_column, end_column,
                ),
                "cell": {"userEnteredFormat": fmt},
                "fields": ",".join(fields),
            }
        }])
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_update_borders(
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_column: int,
        end_column: int,
        spreadsheet_id: str | None = None,
        top_style: str | None = None,
        bottom_style: str | None = None,
        left_style: str | None = None,
        right_style: str | None = None,
        inner_horizontal_style: str | None = None,
        inner_vertical_style: str | None = None,
        color_red: float | None = None,
        color_green: float | None = None,
        color_blue: float | None = None,
    ) -> str:
        """Set borders on a cell range.
        Args:
            sheet_id: Sheet ID
            start_row: Start row (0-based inclusive)
            end_row: End row (0-based exclusive)
            start_column: Start column (0-based inclusive)
            end_column: End column (0-based exclusive)
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            top_style: DOTTED, DASHED, SOLID, SOLID_MEDIUM, SOLID_THICK, DOUBLE, NONE
            bottom_style: Border style
            left_style: Border style
            right_style: Border style
            inner_horizontal_style: Inner horizontal border style
            inner_vertical_style: Inner vertical border style
            color_red: Border color red (0.0-1.0)
            color_green: Border color green (0.0-1.0)
            color_blue: Border color blue (0.0-1.0)
        """
        sid = _sid(spreadsheet_id)
        color = {}
        if any(
            c is not None
            for c in [color_red, color_green, color_blue]
        ):
            color = {
                "red": color_red or 0.0,
                "green": color_green or 0.0,
                "blue": color_blue or 0.0,
            }

        def _border(style: str | None) -> dict | None:
            if style is None:
                return None
            b: dict = {"style": style}
            if color:
                b["colorStyle"] = {"rgbColor": color}
            return b

        borders: dict = {
            "range": _grid_range(
                sheet_id, start_row, end_row, start_column, end_column,
            ),
        }
        mapping = {
            "top": top_style, "bottom": bottom_style,
            "left": left_style, "right": right_style,
            "innerHorizontal": inner_horizontal_style,
            "innerVertical": inner_vertical_style,
        }
        has_border = False
        for key, style in mapping.items():
            b = _border(style)
            if b:
                borders[key] = b
                has_border = True
        if not has_border:
            raise ToolError("At least one border style must be provided.")
        data = await _batch_update(
            sid, [{"updateBorders": borders}],
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_merge_cells(
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_column: int,
        end_column: int,
        spreadsheet_id: str | None = None,
        merge_type: str = "MERGE_ALL",
    ) -> str:
        """Merge a range of cells.
        Args:
            sheet_id: Sheet ID
            start_row: Start row (0-based inclusive)
            end_row: End row (0-based exclusive)
            start_column: Start column (0-based inclusive)
            end_column: End column (0-based exclusive)
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            merge_type: MERGE_ALL, MERGE_COLUMNS, or MERGE_ROWS
        """
        sid = _sid(spreadsheet_id)
        data = await _batch_update(sid, [{
            "mergeCells": {
                "range": _grid_range(
                    sheet_id, start_row, end_row, start_column, end_column,
                ),
                "mergeType": merge_type,
            }
        }])
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_unmerge_cells(
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_column: int,
        end_column: int,
        spreadsheet_id: str | None = None,
    ) -> str:
        """Unmerge previously merged cells.
        Args:
            sheet_id: Sheet ID
            start_row: Start row (0-based inclusive)
            end_row: End row (0-based exclusive)
            start_column: Start column (0-based inclusive)
            end_column: End column (0-based exclusive)
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
        """
        sid = _sid(spreadsheet_id)
        data = await _batch_update(sid, [{
            "unmergeCells": {
                "range": _grid_range(
                    sheet_id, start_row, end_row, start_column, end_column,
                ),
            }
        }])
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_auto_resize(
        sheet_id: int,
        dimension: str,
        start_index: int,
        end_index: int,
        spreadsheet_id: str | None = None,
    ) -> str:
        """Auto-resize columns or rows to fit content.
        Args:
            sheet_id: Sheet ID
            dimension: ROWS or COLUMNS
            start_index: Start index (0-based inclusive)
            end_index: End index (0-based exclusive)
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
        """
        sid = _sid(spreadsheet_id)
        data = await _batch_update(sid, [{
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": dimension,
                    "startIndex": start_index,
                    "endIndex": end_index,
                }
            }
        }])
        return _success(200, data=data)

    # === TIER 5: NAMED RANGES ===

    @mcp.tool()
    async def sheets_add_named_range(
        name: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_column: int,
        end_column: int,
        spreadsheet_id: str | None = None,
    ) -> str:
        """Add a named range.
        Args:
            name: Range name (unique identifier)
            sheet_id: Sheet ID containing the range
            start_row: Start row (0-based inclusive)
            end_row: End row (0-based exclusive)
            start_column: Start column (0-based inclusive)
            end_column: End column (0-based exclusive)
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
        """
        sid = _sid(spreadsheet_id)
        data = await _batch_update(sid, [{
            "addNamedRange": {
                "namedRange": {
                    "name": name,
                    "range": _grid_range(
                        sheet_id, start_row, end_row,
                        start_column, end_column,
                    ),
                }
            }
        }])
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_update_named_range(
        named_range_id: str,
        spreadsheet_id: str | None = None,
        name: str | None = None,
        sheet_id: int | None = None,
        start_row: int | None = None,
        end_row: int | None = None,
        start_column: int | None = None,
        end_column: int | None = None,
    ) -> str:
        """Update a named range.
        Args:
            named_range_id: Named range ID
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            name: New name
            sheet_id: New sheet ID
            start_row: New start row
            end_row: New end row
            start_column: New start column
            end_column: New end column
        """
        sid = _sid(spreadsheet_id)
        nr: dict = {"namedRangeId": named_range_id}
        update_fields: list[str] = []
        if name is not None:
            nr["name"] = name
            update_fields.append("name")
        if any(
            v is not None
            for v in [sheet_id, start_row, end_row, start_column, end_column]
        ):
            if sheet_id is None:
                raise ToolError("sheet_id required when updating range.")
            nr["range"] = _grid_range(
                sheet_id, start_row, end_row, start_column, end_column,
            )
            update_fields.append("range")
        if not update_fields:
            raise ToolError("At least name or range must be provided.")
        data = await _batch_update(sid, [{
            "updateNamedRange": {
                "namedRange": nr,
                "fields": ",".join(update_fields),
            }
        }])
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_delete_named_range(
        named_range_id: str, spreadsheet_id: str | None = None,
    ) -> str:
        """Delete a named range.
        Args:
            named_range_id: Named range ID
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
        """
        sid = _sid(spreadsheet_id)
        data = await _batch_update(sid, [{
            "deleteNamedRange": {"namedRangeId": named_range_id}
        }])
        return _success(200, data=data)

    # === TIER 6: FILTERS ===

    @mcp.tool()
    async def sheets_set_basic_filter(
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_column: int,
        end_column: int,
        spreadsheet_id: str | None = None,
        criteria: dict | None = None,
        sort_specs: list[dict] | None = None,
    ) -> str:
        """Set a basic filter on a sheet.
        Args:
            sheet_id: Sheet ID
            start_row: Start row (0-based inclusive)
            end_row: End row (0-based exclusive)
            start_column: Start column (0-based inclusive)
            end_column: End column (0-based exclusive)
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            criteria: Filter criteria dict
            sort_specs: Sort specifications
        """
        sid = _sid(spreadsheet_id)
        f: dict = {
            "range": _grid_range(
                sheet_id, start_row, end_row, start_column, end_column,
            ),
        }
        if criteria is not None:
            f["criteria"] = criteria
        if sort_specs is not None:
            f["sortSpecs"] = sort_specs
        data = await _batch_update(
            sid, [{"setBasicFilter": {"filter": f}}],
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_clear_basic_filter(
        sheet_id: int, spreadsheet_id: str | None = None,
    ) -> str:
        """Remove the basic filter from a sheet.
        Args:
            sheet_id: Sheet ID
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
        """
        sid = _sid(spreadsheet_id)
        data = await _batch_update(
            sid, [{"clearBasicFilter": {"sheetId": sheet_id}}],
        )
        return _success(200, data=data)

    # === TIER 7: CHARTS ===

    @mcp.tool()
    async def sheets_add_chart(
        sheet_id: int,
        chart_type: str,
        source_start_row: int,
        source_end_row: int,
        source_start_column: int,
        source_end_column: int,
        spreadsheet_id: str | None = None,
        title: str | None = None,
        anchor_sheet_id: int | None = None,
        anchor_row: int = 0,
        anchor_column: int = 0,
        legend_position: str | None = None,
    ) -> str:
        """Add an embedded chart.
        Args:
            sheet_id: Sheet ID for chart data source
            chart_type: BAR, LINE, AREA, COLUMN, SCATTER, PIE, etc.
            source_start_row: Data source start row (0-based inclusive)
            source_end_row: Data source end row (0-based exclusive)
            source_start_column: Data source start column (0-based inclusive)
            source_end_column: Data source end column (0-based exclusive)
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            title: Chart title
            anchor_sheet_id: Sheet to place chart on (defaults to sheet_id)
            anchor_row: Row offset for placement
            anchor_column: Column offset for placement
            legend_position: BOTTOM_LEGEND, LEFT_LEGEND, etc.
        """
        sid = _sid(spreadsheet_id)
        if source_end_column - source_start_column < 2:
            raise ToolError(
                "Chart requires at least 2 columns (domain + series)."
            )
        domain_range = _grid_range(
            sheet_id, source_start_row, source_end_row,
            source_start_column, source_start_column + 1,
        )
        series_range = _grid_range(
            sheet_id, source_start_row, source_end_row,
            source_start_column + 1, source_end_column,
        )
        spec: dict = {
            "basicChart": {
                "chartType": chart_type,
                "domains": [{
                    "domain": {
                        "sourceRange": {"sources": [domain_range]}
                    }
                }],
                "series": [{
                    "series": {
                        "sourceRange": {"sources": [series_range]}
                    }
                }],
            }
        }
        if title is not None:
            spec["title"] = title
        if legend_position is not None:
            spec["basicChart"]["legendPosition"] = legend_position
        a_sheet = anchor_sheet_id if anchor_sheet_id is not None else sheet_id
        chart: dict = {
            "spec": spec,
            "position": {
                "overlayPosition": {
                    "anchorCell": {
                        "sheetId": a_sheet,
                        "rowIndex": anchor_row,
                        "columnIndex": anchor_column,
                    }
                }
            },
        }
        data = await _batch_update(
            sid, [{"addChart": {"chart": chart}}],
        )
        return _success(200, data=data)

    # === TIER 8: PROTECTION ===

    @mcp.tool()
    async def sheets_protect_range(
        sheet_id: int,
        spreadsheet_id: str | None = None,
        description: str | None = None,
        warning_only: bool = False,
        start_row: int | None = None,
        end_row: int | None = None,
        start_column: int | None = None,
        end_column: int | None = None,
        editors_users: list[str] | None = None,
        editors_groups: list[str] | None = None,
    ) -> str:
        """Protect a range or entire sheet from editing.
        Args:
            sheet_id: Sheet ID
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
            description: Protection description
            warning_only: Show warning but allow editing
            start_row: Start row (omit all row/col to protect whole sheet)
            end_row: End row
            start_column: Start column
            end_column: End column
            editors_users: Emails of users who can edit
            editors_groups: Emails of groups who can edit
        """
        sid = _sid(spreadsheet_id)
        pr: dict = {
            "range": _grid_range(
                sheet_id, start_row, end_row, start_column, end_column,
            ),
            "warningOnly": warning_only,
        }
        if description is not None:
            pr["description"] = description
        editors: dict = {}
        if editors_users is not None:
            editors["users"] = editors_users
        if editors_groups is not None:
            editors["groups"] = editors_groups
        if editors:
            pr["editors"] = editors
        data = await _batch_update(
            sid, [{"addProtectedRange": {"protectedRange": pr}}],
        )
        return _success(200, data=data)

    @mcp.tool()
    async def sheets_unprotect_range(
        protected_range_id: int,
        spreadsheet_id: str | None = None,
    ) -> str:
        """Remove protection from a range.
        Args:
            protected_range_id: Protected range ID
            spreadsheet_id: Spreadsheet ID (uses default if omitted)
        """
        sid = _sid(spreadsheet_id)
        data = await _batch_update(sid, [{
            "deleteProtectedRange": {
                "protectedRangeId": protected_range_id,
            }
        }])
        return _success(200, data=data)
