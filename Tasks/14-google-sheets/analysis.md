# Task 14: Google Sheets Integration - Analysis & Requirements

## Objective
Add Google Sheets as a tool integration in mcp-toolbox, exposing spreadsheet management capabilities (spreadsheet CRUD, sheet operations, cell/range read/write, formatting, named ranges, filters, charts, protection) as MCP tools for LLM clients.

---

## API Technical Details

### Google Sheets API v4 -- REST
- **Base URL:** `https://sheets.googleapis.com/v4/spreadsheets`
- **Auth:** Google Service Account with JSON key file. Use `google-auth` library (`google.oauth2.service_account.Credentials`) to acquire OAuth 2.0 access tokens. Token passed as `Authorization: Bearer <access_token>` header.
- **Scopes:** `https://www.googleapis.com/auth/spreadsheets` (full read/write access)
- **Format:** JSON request/response
- **API Version:** v4 (stable, current)

### Authentication Flow
1. Load service account credentials from JSON key file via `google.oauth2.service_account.Credentials.from_service_account_file()`
2. Scope the credentials to `https://www.googleapis.com/auth/spreadsheets`
3. Call `credentials.refresh(google.auth.transport.requests.Request())` to obtain/refresh the access token
4. Use `credentials.token` as the Bearer token in httpx request headers
5. Token auto-expires (typically 1 hour); refresh before each request if expired via `credentials.valid` check

### Rate Limits

| Metric | Limit |
|--------|-------|
| Read requests | 300 per minute per project |
| Write requests | 300 per minute per project |
| Per-user limit | 60 requests per minute per user per project |
| Daily limit | No daily limit (as long as per-minute quotas are respected) |

- HTTP 429 on exceed -- use exponential backoff; quota refills every minute
- No `Retry-After` header; implement client-side backoff

### REST Resources

The Sheets API v4 has 4 REST resources:

| Resource | Description |
|----------|-------------|
| `v4.spreadsheets` | Spreadsheet-level operations (create, get, batchUpdate) |
| `v4.spreadsheets.sheets` | Sheet-level operations (copyTo) |
| `v4.spreadsheets.values` | Cell/range value operations (get, update, append, clear, batchGet, batchUpdate, batchClear) |
| `v4.spreadsheets.developerMetadata` | Developer metadata operations (out of scope) |

### Key Quirks
- **A1 notation** -- ranges use A1 notation (e.g., `Sheet1!A1:D10`). Sheet name is optional for the first sheet but required for others. Sheet names with spaces must be quoted in the range (e.g., `'My Sheet'!A1:B5`).
- **ValueInputOption required for writes** -- `RAW` (no parsing) or `USER_ENTERED` (parses as if typed into the UI, including formulas and dates). Must be specified on every write/update/append call.
- **ValueRenderOption for reads** -- `FORMATTED_VALUE` (display value), `UNFORMATTED_VALUE` (raw number), or `FORMULA` (shows formulas). Default is `FORMATTED_VALUE`.
- **batchUpdate is the Swiss army knife** -- sheet operations (add, delete, rename), formatting, named ranges, filters, charts, and protection are ALL done via `spreadsheets.batchUpdate` with different request types in the `requests` array. This is NOT the same as `spreadsheets.values.batchUpdate` (which writes cell values).
- **0-indexed sheet IDs** -- the first sheet in a spreadsheet has `sheetId: 0`. New sheets get auto-assigned IDs.
- **GridRange uses 0-indexed row/column indices** -- `startRowIndex`, `endRowIndex`, `startColumnIndex`, `endColumnIndex` are all 0-based and end-exclusive.
- **Spreadsheet ID from URL** -- the spreadsheet ID is the long string in the URL: `https://docs.google.com/spreadsheets/d/{spreadsheetId}/edit`
- **Service account sharing** -- the service account email must be shared on the spreadsheet (or the spreadsheet must be created by the service account) for access.
- **No pagination on values** -- `values.get` and `values.batchGet` return all requested data at once (no cursor-based pagination).
- **Create returns full spreadsheet** -- `spreadsheets.create` returns the complete Spreadsheet resource including the auto-generated spreadsheetId.

---

## Google Sheets Object Model

```
Spreadsheet
  |-- properties (title, locale, timeZone, etc.)
  |-- sheets[] (array of Sheet objects)
  |     |-- properties (sheetId, title, index, sheetType, gridProperties)
  |     |-- data[] (GridData with row/cell values and formatting)
  |     |-- charts[]
  |     |-- filterViews[]
  |     |-- protectedRanges[]
  |     |-- basicFilter
  |     |-- conditionalFormats[]
  |-- namedRanges[]
  |-- spreadsheetId
  |-- spreadsheetUrl
```

### Range Addressing
| Format | Example | Description |
|--------|---------|-------------|
| A1 notation | `Sheet1!A1:D10` | Standard cell range |
| Named range | `MyRange` | User-defined named range |
| Full column | `Sheet1!A:A` | Entire column A |
| Full row | `Sheet1!1:1` | Entire row 1 |
| Entire sheet | `Sheet1` | All data in sheet |

---

## Tool Specifications

### Tier 1: Spreadsheet Operations (3 tools)

#### `sheets_create_spreadsheet`
Create a new Google Sheets spreadsheet.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | str | Yes | Spreadsheet title |
| `sheet_titles` | list[str] | No | Names for initial sheets (default: one sheet named "Sheet1") |
| `locale` | str | No | Locale of the spreadsheet (e.g., `en_US`) |
| `time_zone` | str | No | Time zone (e.g., `America/New_York`) |

**Returns:** Created spreadsheet with `spreadsheetId`, `spreadsheetUrl`, and sheet metadata.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets`
**Body:**
```json
{
  "properties": {
    "title": "...",
    "locale": "...",
    "timeZone": "..."
  },
  "sheets": [
    {"properties": {"title": "Sheet1"}},
    {"properties": {"title": "Sheet2"}}
  ]
}
```

#### `sheets_get_spreadsheet`
Get spreadsheet metadata (properties, sheet list, named ranges).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `include_grid_data` | bool | No | Whether to include cell data (default: false) |
| `ranges` | list[str] | No | Ranges to include if `include_grid_data` is true (A1 notation) |

**Returns:** Spreadsheet resource with properties, sheets metadata, and named ranges.
**Endpoint:** `GET https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}?includeGridData={bool}&ranges={range1}&ranges={range2}`

#### `sheets_batch_update_spreadsheet`
Apply one or more structural/formatting updates to a spreadsheet. This is the low-level batch update method that accepts raw request objects for advanced use cases not covered by other tools.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `requests` | list[dict] | Yes | Array of request objects (see Google Sheets API Request types reference) |

**Returns:** Batch update response with replies for each request.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:** `{"requests": [...]}`

---

### Tier 2: Sheet Operations (4 tools)

#### `sheets_add_sheet`
Add a new sheet (tab) to a spreadsheet.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `title` | str | Yes | Name for the new sheet |
| `row_count` | int | No | Number of rows (default: 1000) |
| `column_count` | int | No | Number of columns (default: 26) |
| `index` | int | No | Position to insert the sheet (0-based; default: appended at end) |
| `tab_color_red` | float | No | Tab color red component (0.0-1.0) |
| `tab_color_green` | float | No | Tab color green component (0.0-1.0) |
| `tab_color_blue` | float | No | Tab color blue component (0.0-1.0) |

**Returns:** The added sheet's properties including auto-assigned `sheetId`.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "addSheet": {
      "properties": {
        "title": "...",
        "gridProperties": {"rowCount": 1000, "columnCount": 26},
        "index": 0,
        "tabColorStyle": {"rgbColor": {"red": 0.0, "green": 0.0, "blue": 1.0}}
      }
    }
  }]
}
```

#### `sheets_delete_sheet`
Delete a sheet (tab) from a spreadsheet.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID to delete (0-based integer, NOT the sheet name) |

**Returns:** Confirmation of deletion.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:** `{"requests": [{"deleteSheet": {"sheetId": 0}}]}`

#### `sheets_copy_sheet`
Copy a sheet to the same or another spreadsheet.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `source_spreadsheet_id` | str | No | Source spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID to copy |
| `destination_spreadsheet_id` | str | Yes | Target spreadsheet ID (can be the same spreadsheet) |

**Returns:** The properties of the newly created sheet copy.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{sourceSpreadsheetId}/sheets/{sheetId}:copyTo`
**Body:** `{"destinationSpreadsheetId": "..."}`

#### `sheets_rename_sheet`
Rename an existing sheet (tab).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID to rename |
| `title` | str | Yes | New sheet name |

**Returns:** Confirmation of rename.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "updateSheetProperties": {
      "properties": {"sheetId": 0, "title": "New Name"},
      "fields": "title"
    }
  }]
}
```

---

### Tier 3: Cell/Range Value Operations (7 tools)

#### `sheets_read_values`
Read values from a single range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `range` | str | Yes | A1 notation range (e.g., `Sheet1!A1:D10`) |
| `value_render_option` | str | No | How values are rendered: `FORMATTED_VALUE` (default), `UNFORMATTED_VALUE`, `FORMULA` |
| `date_time_render_option` | str | No | How dates are rendered: `SERIAL_NUMBER` or `FORMATTED_STRING` (default) |
| `major_dimension` | str | No | `ROWS` (default) or `COLUMNS` -- determines the orientation of the returned array |

**Returns:** ValueRange with `range`, `majorDimension`, and `values` (2D array).
**Endpoint:** `GET https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}/values/{range}?valueRenderOption=...&dateTimeRenderOption=...&majorDimension=...`

#### `sheets_write_values`
Write values to a single range (overwrites existing data).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `range` | str | Yes | A1 notation range (e.g., `Sheet1!A1:D3`) |
| `values` | list[list] | Yes | 2D array of values (rows of columns), e.g., `[["Name", "Age"], ["Alice", 30]]` |
| `value_input_option` | str | No | `USER_ENTERED` (default, parses formulas/dates) or `RAW` (stores as-is) |
| `major_dimension` | str | No | `ROWS` (default) or `COLUMNS` |

**Returns:** UpdateValuesResponse with `updatedRange`, `updatedRows`, `updatedColumns`, `updatedCells`.
**Endpoint:** `PUT https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}/values/{range}?valueInputOption=...`
**Body:**
```json
{
  "range": "Sheet1!A1:B2",
  "majorDimension": "ROWS",
  "values": [["Name", "Age"], ["Alice", 30]]
}
```

#### `sheets_append_values`
Append values after the last row of data in a range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `range` | str | Yes | A1 notation range to search for a table (e.g., `Sheet1!A:D`) |
| `values` | list[list] | Yes | 2D array of values to append |
| `value_input_option` | str | No | `USER_ENTERED` (default) or `RAW` |
| `insert_data_option` | str | No | `OVERWRITE` (default) or `INSERT_ROWS` (inserts new rows for the appended data) |
| `major_dimension` | str | No | `ROWS` (default) or `COLUMNS` |

**Returns:** AppendValuesResponse with `tableRange` (original data range) and `updates` (range of appended data).
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}/values/{range}:append?valueInputOption=...&insertDataOption=...`
**Body:**
```json
{
  "majorDimension": "ROWS",
  "values": [["Bob", 25], ["Carol", 35]]
}
```

#### `sheets_clear_values`
Clear values from a single range (formatting is preserved).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `range` | str | Yes | A1 notation range to clear (e.g., `Sheet1!A1:D10`) |

**Returns:** ClearValuesResponse with the `clearedRange`.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}/values/{range}:clear`
**Body:** `{}`

#### `sheets_batch_get_values`
Read values from multiple ranges in a single request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `ranges` | list[str] | Yes | List of A1 notation ranges (e.g., `["Sheet1!A1:B5", "Sheet2!C1:D3"]`) |
| `value_render_option` | str | No | `FORMATTED_VALUE` (default), `UNFORMATTED_VALUE`, or `FORMULA` |
| `date_time_render_option` | str | No | `SERIAL_NUMBER` or `FORMATTED_STRING` (default) |
| `major_dimension` | str | No | `ROWS` (default) or `COLUMNS` |

**Returns:** BatchGetValuesResponse with `spreadsheetId` and `valueRanges` (array of ValueRange objects).
**Endpoint:** `GET https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}/values:batchGet?ranges={range1}&ranges={range2}&valueRenderOption=...&dateTimeRenderOption=...&majorDimension=...`

#### `sheets_batch_update_values`
Write values to multiple ranges in a single request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `data` | list[dict] | Yes | Array of ValueRange objects, each with `range` and `values` keys, e.g., `[{"range": "Sheet1!A1", "values": [["Hello"]]}, {"range": "Sheet2!B2", "values": [[42]]}]` |
| `value_input_option` | str | No | `USER_ENTERED` (default) or `RAW` |

**Returns:** BatchUpdateValuesResponse with `totalUpdatedRows`, `totalUpdatedColumns`, `totalUpdatedCells`, `totalUpdatedSheets`, and per-range `responses`.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}/values:batchUpdate`
**Body:**
```json
{
  "valueInputOption": "USER_ENTERED",
  "data": [
    {"range": "Sheet1!A1:B2", "majorDimension": "ROWS", "values": [["a", "b"], ["c", "d"]]},
    {"range": "Sheet2!A1", "values": [["Hello"]]}
  ]
}
```

#### `sheets_batch_clear_values`
Clear values from multiple ranges in a single request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `ranges` | list[str] | Yes | List of A1 notation ranges to clear |

**Returns:** BatchClearValuesResponse with `spreadsheetId` and `clearedRanges`.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}/values:batchClear`
**Body:** `{"ranges": ["Sheet1!A1:B5", "Sheet2!C1:D3"]}`

---

### Tier 4: Formatting (5 tools)

All formatting tools use `spreadsheets.batchUpdate` under the hood.

#### `sheets_format_cells`
Apply formatting to a range of cells (bold, italic, font size, font color, background color, number format, text alignment).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID (0-based integer) |
| `start_row` | int | Yes | Start row index (0-based, inclusive) |
| `end_row` | int | Yes | End row index (0-based, exclusive) |
| `start_column` | int | Yes | Start column index (0-based, inclusive) |
| `end_column` | int | Yes | End column index (0-based, exclusive) |
| `bold` | bool | No | Bold text |
| `italic` | bool | No | Italic text |
| `underline` | bool | No | Underline text |
| `strikethrough` | bool | No | Strikethrough text |
| `font_size` | int | No | Font size in points |
| `font_family` | str | No | Font family (e.g., `Arial`, `Roboto`) |
| `font_color_red` | float | No | Font color red (0.0-1.0) |
| `font_color_green` | float | No | Font color green (0.0-1.0) |
| `font_color_blue` | float | No | Font color blue (0.0-1.0) |
| `bg_color_red` | float | No | Background color red (0.0-1.0) |
| `bg_color_green` | float | No | Background color green (0.0-1.0) |
| `bg_color_blue` | float | No | Background color blue (0.0-1.0) |
| `horizontal_alignment` | str | No | `LEFT`, `CENTER`, `RIGHT` |
| `vertical_alignment` | str | No | `TOP`, `MIDDLE`, `BOTTOM` |
| `wrap_strategy` | str | No | `OVERFLOW_CELL`, `LEGACY_WRAP`, `CLIP`, `WRAP` |
| `number_format_type` | str | No | `TEXT`, `NUMBER`, `PERCENT`, `CURRENCY`, `DATE`, `TIME`, `DATE_TIME`, `SCIENTIFIC` |
| `number_format_pattern` | str | No | Custom number format pattern (e.g., `#,##0.00`, `yyyy-mm-dd`) |

At least one formatting property must be provided.
**Returns:** Confirmation of formatting applied.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:** Uses `repeatCellRequest` with `range` (GridRange), `cell` (CellData with `userEnteredFormat`), and `fields` mask.

#### `sheets_update_borders`
Set borders on a range of cells.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID |
| `start_row` | int | Yes | Start row index (0-based, inclusive) |
| `end_row` | int | Yes | End row index (0-based, exclusive) |
| `start_column` | int | Yes | Start column index (0-based, inclusive) |
| `end_column` | int | Yes | End column index (0-based, exclusive) |
| `top_style` | str | No | Top border style: `DOTTED`, `DASHED`, `SOLID`, `SOLID_MEDIUM`, `SOLID_THICK`, `DOUBLE`, `NONE` |
| `bottom_style` | str | No | Bottom border style |
| `left_style` | str | No | Left border style |
| `right_style` | str | No | Right border style |
| `inner_horizontal_style` | str | No | Inner horizontal border style |
| `inner_vertical_style` | str | No | Inner vertical border style |
| `color_red` | float | No | Border color red (0.0-1.0), applies to all specified borders |
| `color_green` | float | No | Border color green (0.0-1.0) |
| `color_blue` | float | No | Border color blue (0.0-1.0) |

At least one border style must be provided.
**Returns:** Confirmation of borders applied.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:** Uses `updateBordersRequest` with `range` (GridRange) and border specifications.

#### `sheets_merge_cells`
Merge a range of cells.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID |
| `start_row` | int | Yes | Start row index (0-based, inclusive) |
| `end_row` | int | Yes | End row index (0-based, exclusive) |
| `start_column` | int | Yes | Start column index (0-based, inclusive) |
| `end_column` | int | Yes | End column index (0-based, exclusive) |
| `merge_type` | str | No | `MERGE_ALL` (default), `MERGE_COLUMNS`, or `MERGE_ROWS` |

**Returns:** Confirmation of merge.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:** `{"requests": [{"mergeCells": {"range": {...}, "mergeType": "MERGE_ALL"}}]}`

#### `sheets_unmerge_cells`
Unmerge previously merged cells in a range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID |
| `start_row` | int | Yes | Start row index (0-based, inclusive) |
| `end_row` | int | Yes | End row index (0-based, exclusive) |
| `start_column` | int | Yes | Start column index (0-based, inclusive) |
| `end_column` | int | Yes | End column index (0-based, exclusive) |

**Returns:** Confirmation of unmerge.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:** `{"requests": [{"unmergeCells": {"range": {...}}}]}`

#### `sheets_auto_resize`
Auto-resize columns or rows to fit their content.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID |
| `dimension` | str | Yes | `ROWS` or `COLUMNS` |
| `start_index` | int | Yes | Start index (0-based, inclusive) |
| `end_index` | int | Yes | End index (0-based, exclusive) |

**Returns:** Confirmation of resize.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "autoResizeDimensions": {
      "dimensions": {
        "sheetId": 0,
        "dimension": "COLUMNS",
        "startIndex": 0,
        "endIndex": 5
      }
    }
  }]
}
```

---

### Tier 5: Named Ranges (3 tools)

#### `sheets_add_named_range`
Add a named range to the spreadsheet.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `name` | str | Yes | Name for the range (must be unique, valid identifier) |
| `sheet_id` | int | Yes | Sheet ID containing the range |
| `start_row` | int | Yes | Start row index (0-based, inclusive) |
| `end_row` | int | Yes | End row index (0-based, exclusive) |
| `start_column` | int | Yes | Start column index (0-based, inclusive) |
| `end_column` | int | Yes | End column index (0-based, exclusive) |

**Returns:** The created named range with its auto-assigned `namedRangeId`.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "addNamedRange": {
      "namedRange": {
        "name": "MyRange",
        "range": {
          "sheetId": 0,
          "startRowIndex": 0,
          "endRowIndex": 10,
          "startColumnIndex": 0,
          "endColumnIndex": 4
        }
      }
    }
  }]
}
```

#### `sheets_update_named_range`
Update an existing named range (change its name or cell range).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `named_range_id` | str | Yes | Named range ID (from `sheets_get_spreadsheet` or `sheets_add_named_range` response) |
| `name` | str | No | New name for the range |
| `sheet_id` | int | No | New sheet ID for the range |
| `start_row` | int | No | New start row index |
| `end_row` | int | No | New end row index |
| `start_column` | int | No | New start column index |
| `end_column` | int | No | New end column index |

At least one property (name or range coordinates) must be provided.
**Returns:** Confirmation of update.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "updateNamedRange": {
      "namedRange": {
        "namedRangeId": "...",
        "name": "NewName",
        "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 20, "startColumnIndex": 0, "endColumnIndex": 5}
      },
      "fields": "name,range"
    }
  }]
}
```

#### `sheets_delete_named_range`
Delete a named range from the spreadsheet.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `named_range_id` | str | Yes | Named range ID to delete |

**Returns:** Confirmation of deletion.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:** `{"requests": [{"deleteNamedRange": {"namedRangeId": "..."}}]}`

---

### Tier 6: Filters (2 tools)

#### `sheets_set_basic_filter`
Set a basic filter on a sheet (the auto-filter row that appears at the top of a data range).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID |
| `start_row` | int | Yes | Start row index (0-based, inclusive) |
| `end_row` | int | Yes | End row index (0-based, exclusive) |
| `start_column` | int | Yes | Start column index (0-based, inclusive) |
| `end_column` | int | Yes | End column index (0-based, exclusive) |
| `criteria` | dict | No | Column filter criteria as `{columnIndex: {"hiddenValues": [...], "condition": {"type": "...", "values": [...]}}}`. Column indices are 0-based. Condition types: `NUMBER_GREATER`, `NUMBER_LESS`, `TEXT_CONTAINS`, `TEXT_NOT_CONTAINS`, `CUSTOM_FORMULA`, etc. |
| `sort_specs` | list[dict] | No | Sort specifications, e.g., `[{"dimensionIndex": 0, "sortOrder": "ASCENDING"}]` |

**Returns:** Confirmation of filter set.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "setBasicFilter": {
      "filter": {
        "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 100, "startColumnIndex": 0, "endColumnIndex": 5},
        "criteria": {
          "0": {"hiddenValues": ["exclude_this"]}
        },
        "sortSpecs": [{"dimensionIndex": 0, "sortOrder": "ASCENDING"}]
      }
    }
  }]
}
```

#### `sheets_clear_basic_filter`
Remove the basic filter from a sheet.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID |

**Returns:** Confirmation of filter removal.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:** `{"requests": [{"clearBasicFilter": {"sheetId": 0}}]}`

---

### Tier 7: Charts (1 tool)

#### `sheets_add_chart`
Add an embedded chart to a sheet.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID where the chart's data source resides |
| `chart_type` | str | Yes | Chart type: `BAR`, `LINE`, `AREA`, `COLUMN`, `SCATTER`, `COMBO`, `STEPPED_AREA`, `PIE`, `BUBBLE`, `HISTOGRAM`, `ORG`, `TREEMAP`, `WATERFALL`, `RADAR` |
| `title` | str | No | Chart title |
| `source_start_row` | int | Yes | Data source start row (0-based, inclusive) |
| `source_end_row` | int | Yes | Data source end row (0-based, exclusive) |
| `source_start_column` | int | Yes | Data source start column (0-based, inclusive) |
| `source_end_column` | int | Yes | Data source end column (0-based, exclusive) |
| `anchor_sheet_id` | int | No | Sheet ID to place the chart on (defaults to `sheet_id`) |
| `anchor_row` | int | No | Row offset for chart placement (0-based, default: 0) |
| `anchor_column` | int | No | Column offset for chart placement (0-based, default: 0) |
| `legend_position` | str | No | `BOTTOM_LEGEND`, `LEFT_LEGEND`, `RIGHT_LEGEND`, `TOP_LEGEND`, `NO_LEGEND` |

**Returns:** The created chart with its auto-assigned `chartId`.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "addChart": {
      "chart": {
        "spec": {
          "title": "Sales Chart",
          "basicChart": {
            "chartType": "LINE",
            "legendPosition": "BOTTOM_LEGEND",
            "domains": [{
              "domain": {
                "sourceRange": {
                  "sources": [{"sheetId": 0, "startRowIndex": 0, "endRowIndex": 10, "startColumnIndex": 0, "endColumnIndex": 1}]
                }
              }
            }],
            "series": [{
              "series": {
                "sourceRange": {
                  "sources": [{"sheetId": 0, "startRowIndex": 0, "endRowIndex": 10, "startColumnIndex": 1, "endColumnIndex": 2}]
                }
              }
            }]
          }
        },
        "position": {
          "overlayPosition": {
            "anchorCell": {"sheetId": 0, "rowIndex": 0, "columnIndex": 5}
          }
        }
      }
    }
  }]
}
```

---

### Tier 8: Protection (2 tools)

#### `sheets_protect_range`
Protect a range or entire sheet from editing.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `sheet_id` | int | Yes | Sheet ID |
| `description` | str | No | Description of the protection |
| `warning_only` | bool | No | If true, shows a warning but allows editing (default: false) |
| `start_row` | int | No | Start row index (omit all row/col params to protect entire sheet) |
| `end_row` | int | No | End row index |
| `start_column` | int | No | Start column index |
| `end_column` | int | No | End column index |
| `editors_users` | list[str] | No | Email addresses of users who can edit the protected range |
| `editors_groups` | list[str] | No | Email addresses of groups who can edit |

If row/column indices are omitted, the entire sheet is protected.
**Returns:** The created protected range with its auto-assigned `protectedRangeId`.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "addProtectedRange": {
      "protectedRange": {
        "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 10},
        "description": "Header row - do not edit",
        "warningOnly": false,
        "editors": {
          "users": ["admin@example.com"],
          "groups": []
        }
      }
    }
  }]
}
```

#### `sheets_unprotect_range`
Remove protection from a previously protected range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | str | No | Spreadsheet ID (uses default if not provided) |
| `protected_range_id` | int | Yes | Protected range ID (from `sheets_get_spreadsheet` or `sheets_protect_range` response) |

**Returns:** Confirmation of protection removal.
**Endpoint:** `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}:batchUpdate`
**Body:** `{"requests": [{"deleteProtectedRange": {"protectedRangeId": 123}}]}`

---

## Architecture Decisions

### A1: httpx with google-auth Token Management (no Google SDK)
Use `httpx` (already in project dependencies) for async HTTP calls, consistent with ClickUp/HubSpot patterns. Use `google-auth` library solely for service account credential loading and token acquisition. Do NOT use `google-api-python-client` or `gspread` -- they add unnecessary complexity and are synchronous.

### A2: Token-Refreshing httpx Client

```python
import google.auth.transport.requests
from google.oauth2 import service_account

_credentials: service_account.Credentials | None = None
_client: httpx.AsyncClient | None = None

def _get_token() -> str:
    """Get a valid access token, refreshing if needed."""
    global _credentials
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ToolError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not configured. "
            "Set it to the path of your service account JSON key file."
        )
    if _credentials is None:
        _credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
    if not _credentials.valid:
        _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token

def _get_client() -> httpx.AsyncClient:
    """Get or create the httpx client with fresh auth token."""
    global _client
    token = _get_token()
    if _client is None:
        _client = httpx.AsyncClient(
            base_url="https://sheets.googleapis.com/v4/spreadsheets",
            timeout=30.0,
        )
    # Always update the auth header in case the token was refreshed
    _client.headers["Authorization"] = f"Bearer {token}"
    return _client
```

**Note:** `_credentials.refresh()` uses synchronous `google.auth.transport.requests.Request()`. This is a brief network call (~100ms) that happens at most once per hour. Running it synchronously in an async context is acceptable for this use case -- same pattern used by Google's own async libraries internally.

### A3: Default Spreadsheet ID Helper

```python
def _resolve_spreadsheet_id(override: str | None = None) -> str:
    """Resolve spreadsheet ID: override > config > error."""
    sid = override or GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID
    if not sid:
        raise ToolError(
            "No spreadsheet_id provided. Either pass spreadsheet_id or set "
            "GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID in your environment."
        )
    return sid
```

### A4: Tool Naming Convention
All Google Sheets tools prefixed with `sheets_` to distinguish from other integrations.

### A5: Error Handling
Same pattern as ClickUp/HubSpot: catch `httpx` exceptions, convert to `ToolError` with human-readable messages. 429 responses include rate limit info. No automatic retry.

### A6: Response Format
Consistent JSON convention: `{"status": "success", ...}` or raised `ToolError` on failure.

### A7: GridRange Builder Helper
Many tools need GridRange objects. A shared helper reduces boilerplate:

```python
def _grid_range(
    sheet_id: int,
    start_row: int | None = None,
    end_row: int | None = None,
    start_column: int | None = None,
    end_column: int | None = None,
) -> dict:
    """Build a GridRange dict, omitting None fields."""
    gr = {"sheetId": sheet_id}
    if start_row is not None:
        gr["startRowIndex"] = start_row
    if end_row is not None:
        gr["endRowIndex"] = end_row
    if start_column is not None:
        gr["startColumnIndex"] = start_column
    if end_column is not None:
        gr["endColumnIndex"] = end_column
    return gr
```

### A8: batchUpdate Wrapper Helper
Since formatting, named ranges, filters, charts, and protection all use `spreadsheets.batchUpdate`, a shared helper simplifies these tools:

```python
async def _batch_update(spreadsheet_id: str, requests: list[dict]) -> dict:
    """Execute a spreadsheets.batchUpdate call."""
    client = _get_client()
    return await _request("POST", f"/{spreadsheet_id}:batchUpdate", json={"requests": requests})
```

### A9: Missing Credential Strategy
Same as ClickUp: register tools regardless, fail at invocation with clear `ToolError` if service account JSON path is not configured.

### A10: Formatting Field Mask Builder
The `repeatCellRequest` used by `sheets_format_cells` requires a `fields` mask specifying which format fields are being set. Build this dynamically from the provided parameters to avoid accidentally clearing unset formatting properties.

---

## Configuration Requirements

### Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Path to Google service account JSON key file | Yes (at invocation) | `None` |
| `GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID` | Default spreadsheet ID (used when `spreadsheet_id` param is omitted) | No | `None` |

### Config Pattern
```python
# Google Sheets
GOOGLE_SERVICE_ACCOUNT_JSON: str | None = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID: str | None = os.getenv("GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID")
```

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/config.py` | Modify | Add `GOOGLE_SERVICE_ACCOUNT_JSON` and `GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID` |
| `.env.example` | Modify | Add Google Sheets variables |
| `src/mcp_toolbox/tools/sheets_tool.py` | **New** | All Google Sheets tools (27 tools) |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register sheets_tool |
| `tests/test_sheets_tool.py` | **New** | Tests for all Google Sheets tools |
| `CLAUDE.md` | Modify | Document Google Sheets integration |
| `pyproject.toml` | Modify | Add `google-auth[requests]>=2.0.0` dependency |

---

## Dependencies

| Package | Purpose | Already in project? |
|---------|---------|-------------------|
| `httpx` | Async HTTP client | Yes |
| `google-auth[requests]>=2.0.0` | Service account credential loading, OAuth 2.0 token acquisition, and `google.auth.transport.requests.Request` for token refresh | **No -- new dependency** |
| `respx` | httpx mock library (dev) | Yes |

### Why `google-auth` and not `google-api-python-client`?
- `google-auth` is a lightweight library (~500KB) focused solely on authentication
- `google-api-python-client` pulls in `google-auth`, `google-auth-httplib2`, `httplib2`, `uritemplate`, and auto-discovery machinery -- unnecessary bloat
- We only need token acquisition; all HTTP calls go through httpx
- `google-auth` core has no transitive dependencies beyond `cachetools`, `pyasn1-modules`, and `rsa`
- The `[requests]` extra is needed because `google.auth.transport.requests.Request()` (used for token refresh) requires the `requests` library, which is an optional dependency of `google-auth`

---

## Testing Strategy

### Approach
Use `pytest` with `respx` for mocking HTTP calls. Mock the `google-auth` credential loading and token refresh to avoid needing a real service account in tests.

```python
import respx
import httpx
from unittest.mock import patch, MagicMock

@respx.mock
@patch("mcp_toolbox.tools.sheets_tool._get_token", return_value="fake-token")
async def test_read_values(mock_token):
    respx.get(
        "https://sheets.googleapis.com/v4/spreadsheets/abc123/values/Sheet1!A1:B5"
    ).mock(
        return_value=httpx.Response(200, json={
            "range": "Sheet1!A1:B5",
            "majorDimension": "ROWS",
            "values": [["Name", "Age"], ["Alice", "30"]]
        })
    )
    result = await server.call_tool("sheets_read_values", {
        "spreadsheet_id": "abc123",
        "range": "Sheet1!A1:B5"
    })
    assert "success" in result
```

### Test Coverage
1. Happy path for every tool (27 tests minimum)
2. Missing service account JSON path -> ToolError
3. Invalid/expired token refresh failure -> ToolError
4. API errors (401 Unauthorized, 403 Forbidden, 404 Not Found, 429 Rate Limit)
5. Default spreadsheet ID resolution (override vs. config vs. error)
6. GridRange builder with various None combinations
7. Formatting field mask builder (only specified fields included)
8. Value input/render options passed correctly
9. batchUpdate request construction for sheet/formatting/chart/protection tools

---

## Success Criteria

1. `uv sync` installs without errors (new `google-auth[requests]>=2.0.0` dependency resolves)
2. All 27 Google Sheets tools register and are discoverable via MCP Inspector
3. Tools return meaningful errors when service account JSON is missing
4. Tools return meaningful errors when spreadsheet_id is missing and no default is set
5. All tools return consistent JSON responses (`{"status": "success", ...}`)
6. New tests pass and full regression suite remains green
7. Config handles missing credentials gracefully (tools register, fail at invocation)
8. Total tool count reaches **365** (current 338 + 27 new Google Sheets tools)

---

## Scope Decision

**All 8 tiers (27 tools)** -- full Google Sheets integration covering spreadsheet CRUD, sheet operations, cell/range value read/write/append/clear with batch variants, formatting, named ranges, filters, charts, and protection.

---

## Tool Summary (27 tools total)

### Tier 1 -- Spreadsheet Operations (3 tools)
1. `sheets_create_spreadsheet` -- Create a new spreadsheet with title and optional sheet names
2. `sheets_get_spreadsheet` -- Get spreadsheet metadata, sheets, and named ranges
3. `sheets_batch_update_spreadsheet` -- Raw batchUpdate for advanced use cases

### Tier 2 -- Sheet Operations (4 tools)
4. `sheets_add_sheet` -- Add a new sheet (tab) with optional size and color
5. `sheets_delete_sheet` -- Delete a sheet by ID
6. `sheets_copy_sheet` -- Copy a sheet to same or different spreadsheet
7. `sheets_rename_sheet` -- Rename a sheet

### Tier 3 -- Cell/Range Value Operations (7 tools)
8. `sheets_read_values` -- Read values from a single range
9. `sheets_write_values` -- Write values to a single range
10. `sheets_append_values` -- Append rows after existing data
11. `sheets_clear_values` -- Clear values from a range (preserves formatting)
12. `sheets_batch_get_values` -- Read values from multiple ranges
13. `sheets_batch_update_values` -- Write values to multiple ranges
14. `sheets_batch_clear_values` -- Clear values from multiple ranges

### Tier 4 -- Formatting (5 tools)
15. `sheets_format_cells` -- Apply text/number/color formatting to a range
16. `sheets_update_borders` -- Set borders on a range
17. `sheets_merge_cells` -- Merge a range of cells
18. `sheets_unmerge_cells` -- Unmerge previously merged cells
19. `sheets_auto_resize` -- Auto-resize columns or rows to fit content

### Tier 5 -- Named Ranges (3 tools)
20. `sheets_add_named_range` -- Create a named range
21. `sheets_update_named_range` -- Update a named range's name or coordinates
22. `sheets_delete_named_range` -- Delete a named range

### Tier 6 -- Filters (2 tools)
23. `sheets_set_basic_filter` -- Set auto-filter on a data range with criteria
24. `sheets_clear_basic_filter` -- Remove the basic filter from a sheet

### Tier 7 -- Charts (1 tool)
25. `sheets_add_chart` -- Add an embedded chart with configurable type and data source

### Tier 8 -- Protection (2 tools)
26. `sheets_protect_range` -- Protect a range or sheet from editing
27. `sheets_unprotect_range` -- Remove protection from a range
