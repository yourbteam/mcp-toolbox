# Task 20: Google Docs Integration - Analysis & Requirements

## Objective
Add Google Docs as a tool integration in mcp-toolbox, exposing document management capabilities (document create/get, text insertion, deletion, replacement, formatting, tables, images, named ranges, headers/footers, and raw batchUpdate) as MCP tools for LLM clients.

---

## API Technical Details

### Google Docs API v1 -- REST
- **Base URL:** `https://docs.googleapis.com/v1/documents`
- **Auth:** Google Service Account with JSON key file. Use `google-auth` library (`google.oauth2.service_account.Credentials`) to acquire OAuth 2.0 access tokens. Token passed as `Authorization: Bearer <access_token>` header.
- **Scopes:** `https://www.googleapis.com/auth/documents` (full read/write access)
- **Format:** JSON request/response
- **API Version:** v1 (stable, current)

### Authentication Flow (identical to Sheets integration)
1. Load service account credentials from JSON key file via `google.oauth2.service_account.Credentials.from_service_account_file()`
2. Scope the credentials to `https://www.googleapis.com/auth/documents`
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

The Docs API v1 has 1 REST resource with 3 methods:

| Method | HTTP | Path | Description |
|--------|------|------|-------------|
| `documents.create` | POST | `/v1/documents` | Create a new blank document |
| `documents.get` | GET | `/v1/documents/{documentId}` | Get document content and metadata |
| `documents.batchUpdate` | POST | `/v1/documents/{documentId}:batchUpdate` | Apply one or more updates to a document |

All document mutations go through `batchUpdate` with typed request objects in the `requests` array.

---

## Google Docs Object Model

```
Document
  |-- documentId
  |-- title
  |-- revisionId
  |-- body
  |     |-- content[] (array of StructuralElement)
  |           |-- paragraph
  |           |     |-- elements[] (ParagraphElement)
  |           |     |     |-- textRun (text + textStyle)
  |           |     |     |-- inlineObjectElement
  |           |     |     |-- pageBreak
  |           |     |     |-- horizontalRule
  |           |     |     |-- autoText
  |           |     |-- paragraphStyle (namedStyleType, alignment, lineSpacing, etc.)
  |           |-- sectionBreak
  |           |-- table
  |           |     |-- tableRows[]
  |           |           |-- tableCells[]
  |           |                 |-- content[] (nested StructuralElement)
  |           |-- tableOfContents
  |-- headers (map of headerId -> Header)
  |-- footers (map of footerId -> Footer)
  |-- footnotes (map of footnoteId -> Footnote)
  |-- documentStyle (pageSize, margins, defaultHeaderId, defaultFooterId)
  |-- namedStyles (heading1..6, normal, title, subtitle)
  |-- lists (map of listId -> ListProperties)
  |-- namedRanges (map of namedRangeId -> NamedRange)
  |-- inlineObjects (map of objectId -> InlineObject with imageProperties)
  |-- suggestionsViewMode
```

### Content Addressing -- Index-Based

The Docs API uses a **0-based character index** system for all content operations:

| Concept | Description |
|---------|-------------|
| Start index | 0-based position in the document body where content begins |
| End index | Exclusive end position (like Python slicing) |
| Segment | Which part of the document: body, header, footer, footnote |
| Newline characters | Each paragraph ends with `\n` which occupies one index position |
| Structural elements | Tables, section breaks, etc. each occupy index positions |
| Document start | The body content starts at index 1 (index 0 is the document start marker) |

**Critical:** Indexes shift after every insert/delete. When sending multiple requests in a single batchUpdate, requests are applied **sequentially** in array order. Use **reverse index order** (highest indexes first) when making multiple edits to avoid index shifting issues, or use the `InsertionLocation` approach.

### Range Object
```json
{
  "startIndex": 10,
  "endIndex": 25,
  "segmentId": ""  // empty string = body; otherwise headerId/footerId/footnoteId
}
```

---

## batchUpdate Request Types -- Complete Reference

The `documents.batchUpdate` endpoint accepts a `requests` array where each element is an object with exactly one key (the request type). Below is the **complete list** of all request types supported by the Google Docs API v1.

### Text Content Requests

| Request Type | Description |
|-------------|-------------|
| `insertText` | Insert text at a specified index or at the end of a segment |
| `deleteContentRange` | Delete content within a range (start/end indexes) |
| `replaceAllText` | Find-and-replace all occurrences of text in the document |

### Formatting Requests

| Request Type | Description |
|-------------|-------------|
| `updateTextStyle` | Update text formatting (bold, italic, font, size, color, link, etc.) |
| `updateParagraphStyle` | Update paragraph formatting (alignment, spacing, indentation, heading type, etc.) |

### Structural Requests

| Request Type | Description |
|-------------|-------------|
| `insertTable` | Insert a table at a specified index with given rows/columns |
| `insertTableRow` | Insert a row into an existing table |
| `insertTableColumn` | Insert a column into an existing table |
| `deleteTableRow` | Delete a row from a table |
| `deleteTableColumn` | Delete a column from a table |
| `insertPageBreak` | Insert a page break at a specified index |
| `insertSectionBreak` | Insert a section break (CONTINUOUS or NEXT_PAGE) at a specified index |
| `insertInlineImage` | Insert an image from a URL at a specified index |
| `createParagraphBullets` | Add bullet/numbered list formatting to a range of paragraphs |
| `deleteParagraphBullets` | Remove bullet/numbered list formatting from a range |

### Table Formatting Requests

| Request Type | Description |
|-------------|-------------|
| `updateTableColumnProperties` | Set column width and width type for a table column |
| `updateTableCellStyle` | Update cell formatting (background color, borders, padding, alignment) |
| `updateTableRowStyle` | Update row height and height type |
| `mergeTableCells` | Merge a rectangular range of table cells |
| `unmergeTableCells` | Unmerge previously merged table cells |
| `pinTableHeaderRows` | Pin a number of rows as repeating header rows in a table |

### Named Range Requests

| Request Type | Description |
|-------------|-------------|
| `createNamedRange` | Create a named range over a content range |
| `deleteNamedRange` | Delete a named range by ID or name |

### Document Style Requests

| Request Type | Description |
|-------------|-------------|
| `updateDocumentStyle` | Update page-level styles (page size, margins, background) |
| `updateSectionStyle` | Update section-level styles (column count, section type) |

### Header/Footer Requests

| Request Type | Description |
|-------------|-------------|
| `createHeader` | Create a header for a given section |
| `createFooter` | Create a footer for a given section |
| `deleteHeader` | Delete a header by ID |
| `deleteFooter` | Delete a footer by ID |
| `createFootnote` | Create a footnote at a specified index |

### Named Styles Requests

| Request Type | Description |
|-------------|-------------|
| `updateNamedStyles` (internal) | Reserved -- updates built-in named style definitions (NORMAL_TEXT, HEADING_1, etc.) |

### Positioned Object Requests

| Request Type | Description |
|-------------|-------------|
| `insertInlineImage` | (listed above) Inserts an image inline |
| `replaceImage` | Replace an existing inline image with a new image URL |

### Replace Requests

| Request Type | Description |
|-------------|-------------|
| `replaceAllText` | (listed above) Global find-and-replace |
| `replaceNamedRangeContent` | Replace the content of all instances of a named range |

---

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes | Path to Google service account JSON key file (reused from Sheets) |
| `GDOCS_DEFAULT_DOCUMENT_ID` | No | Default document ID (used when `document_id` param is omitted) |

### Config Integration
Add `GDOCS_DEFAULT_DOCUMENT_ID` to `config.py`:
```python
GDOCS_DEFAULT_DOCUMENT_ID: str | None = os.getenv("GDOCS_DEFAULT_DOCUMENT_ID")
```

The `GOOGLE_SERVICE_ACCOUNT_JSON` variable is already defined and shared with the Sheets integration. The service account must have the `https://www.googleapis.com/auth/documents` scope. Documents must be shared with the service account email for access, or created by the service account.

---

## Tool Specifications

### Tier 1: Document Operations (3 tools)

#### `gdocs_create_document`
Create a new blank Google Docs document.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | str | Yes | Document title |

**Returns:** Created document with `documentId`, `title`, and `revisionId`.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents`
**Body:**
```json
{
  "title": "My New Document"
}
```

#### `gdocs_get_document`
Get full document content and metadata (body, headers, footers, named ranges, styles, inline objects).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `suggestions_view_mode` | str | No | How to render suggestions: `DEFAULT_FOR_CURRENT_ACCESS`, `SUGGESTIONS_INLINE`, `PREVIEW_SUGGESTIONS_ACCEPTED`, `PREVIEW_WITHOUT_SUGGESTIONS` |

**Returns:** Full Document resource with body content, structural elements, styles, headers, footers, named ranges, and inline objects.
**Endpoint:** `GET https://docs.googleapis.com/v1/documents/{documentId}?suggestionsViewMode=...`

#### `gdocs_batch_update`
Apply one or more updates to a document. This is the low-level batch update method that accepts raw request objects for advanced use cases not covered by other tools.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `requests` | list[dict] | Yes | Array of request objects (see Google Docs API batchUpdate request types) |

**Returns:** BatchUpdate response with `documentId`, `replies` array (one per request), and `writeControl` with `requiredRevisionId`.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:** `{"requests": [...]}`

---

### Tier 2: Text Content Operations (3 tools)

#### `gdocs_insert_text`
Insert text at a specified index in the document.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `text` | str | Yes | Text to insert |
| `index` | int | Yes | 0-based index position to insert at (body starts at index 1) |
| `segment_id` | str | No | Segment to insert into: empty string for body (default), or a header/footer/footnote ID |

**Returns:** BatchUpdate response confirming insertion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "insertText": {
      "text": "Hello, world!",
      "location": {
        "index": 1,
        "segmentId": ""
      }
    }
  }]
}
```

#### `gdocs_delete_content`
Delete content within a specified range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `start_index` | int | Yes | Start index of content to delete (inclusive) |
| `end_index` | int | Yes | End index of content to delete (exclusive) |
| `segment_id` | str | No | Segment: empty string for body (default), or header/footer/footnote ID |

**Returns:** BatchUpdate response confirming deletion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "deleteContentRange": {
      "range": {
        "startIndex": 5,
        "endIndex": 15,
        "segmentId": ""
      }
    }
  }]
}
```

#### `gdocs_replace_all_text`
Find and replace all occurrences of text in the document.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `find_text` | str | Yes | Text to search for |
| `replace_text` | str | Yes | Replacement text |
| `match_case` | bool | No | Whether the search is case-sensitive (default: true) |

**Returns:** BatchUpdate response with `occurrencesChanged` count in the reply.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "replaceAllText": {
      "containsText": {
        "text": "old text",
        "matchCase": true
      },
      "replaceText": "new text"
    }
  }]
}
```

---

### Tier 3: Formatting Operations (2 tools)

#### `gdocs_update_text_style`
Update text formatting (bold, italic, underline, font, size, color, link, etc.) for a range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `start_index` | int | Yes | Start index of text to format (inclusive) |
| `end_index` | int | Yes | End index of text to format (exclusive) |
| `bold` | bool | No | Set bold |
| `italic` | bool | No | Set italic |
| `underline` | bool | No | Set underline |
| `strikethrough` | bool | No | Set strikethrough |
| `font_family` | str | No | Font family name (e.g., `Arial`, `Times New Roman`) |
| `font_size_pt` | float | No | Font size in points |
| `foreground_color_red` | float | No | Text color red component (0.0-1.0) |
| `foreground_color_green` | float | No | Text color green component (0.0-1.0) |
| `foreground_color_blue` | float | No | Text color blue component (0.0-1.0) |
| `background_color_red` | float | No | Highlight color red component (0.0-1.0) |
| `background_color_green` | float | No | Highlight color green component (0.0-1.0) |
| `background_color_blue` | float | No | Highlight color blue component (0.0-1.0) |
| `link_url` | str | No | URL to link the text to |
| `small_caps` | bool | No | Set small caps |
| `superscript` | bool | No | Set superscript (mutually exclusive with subscript) |
| `subscript` | bool | No | Set subscript (mutually exclusive with superscript) |
| `segment_id` | str | No | Segment: empty string for body (default), or header/footer/footnote ID |

**Returns:** BatchUpdate response confirming style update.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "updateTextStyle": {
      "range": {
        "startIndex": 1,
        "endIndex": 10,
        "segmentId": ""
      },
      "textStyle": {
        "bold": true,
        "italic": true,
        "fontSize": {"magnitude": 14, "unit": "PT"},
        "weightedFontFamily": {"fontFamily": "Arial"},
        "foregroundColor": {"color": {"rgbColor": {"red": 0.0, "green": 0.0, "blue": 1.0}}},
        "link": {"url": "https://example.com"}
      },
      "fields": "bold,italic,fontSize,weightedFontFamily,foregroundColor,link"
    }
  }]
}
```
**Note:** The `fields` mask is critical -- it specifies which style properties to update. Only properties listed in `fields` are modified; others are left unchanged. The tool implementation must dynamically build the `fields` mask from whichever optional params are provided.

#### `gdocs_update_paragraph_style`
Update paragraph formatting (alignment, spacing, indentation, heading type, etc.) for a range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `start_index` | int | Yes | Start index of paragraph range (inclusive) |
| `end_index` | int | Yes | End index of paragraph range (exclusive) |
| `named_style_type` | str | No | Named style: `NORMAL_TEXT`, `TITLE`, `SUBTITLE`, `HEADING_1` through `HEADING_6` |
| `alignment` | str | No | Text alignment: `START`, `CENTER`, `END`, `JUSTIFIED` |
| `line_spacing` | float | No | Line spacing as percentage (e.g., 100 = single, 200 = double) |
| `space_above_pt` | float | No | Space above paragraph in points |
| `space_below_pt` | float | No | Space below paragraph in points |
| `indent_first_line_pt` | float | No | First line indent in points |
| `indent_start_pt` | float | No | Left/start indent in points |
| `indent_end_pt` | float | No | Right/end indent in points |
| `keep_lines_together` | bool | No | Prevent page break within paragraph |
| `keep_with_next` | bool | No | Keep paragraph on same page as next paragraph |
| `direction` | str | No | Text direction: `LEFT_TO_RIGHT` or `RIGHT_TO_LEFT` |
| `segment_id` | str | No | Segment: empty string for body (default), or header/footer/footnote ID |

**Returns:** BatchUpdate response confirming style update.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "updateParagraphStyle": {
      "range": {
        "startIndex": 1,
        "endIndex": 50,
        "segmentId": ""
      },
      "paragraphStyle": {
        "namedStyleType": "HEADING_1",
        "alignment": "CENTER",
        "lineSpacing": 150,
        "spaceAbove": {"magnitude": 12, "unit": "PT"},
        "spaceBelow": {"magnitude": 6, "unit": "PT"},
        "indentFirstLine": {"magnitude": 36, "unit": "PT"}
      },
      "fields": "namedStyleType,alignment,lineSpacing,spaceAbove,spaceBelow,indentFirstLine"
    }
  }]
}
```
**Note:** Same `fields` mask pattern as `updateTextStyle` -- dynamically built from provided params.

---

### Tier 4: Structural Element Operations (7 tools)

#### `gdocs_insert_table`
Insert a table at a specified index.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `rows` | int | Yes | Number of rows |
| `columns` | int | Yes | Number of columns |
| `index` | int | Yes | Index position to insert the table |
| `segment_id` | str | No | Segment: empty string for body (default), or header/footer/footnote ID |

**Returns:** BatchUpdate response confirming table insertion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "insertTable": {
      "rows": 3,
      "columns": 4,
      "location": {"index": 1, "segmentId": ""}
    }
  }]
}
```

#### `gdocs_insert_table_row`
Insert a row into an existing table.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `table_start_index` | int | Yes | Start index of the table in the document |
| `row_index` | int | Yes | 0-based row index of the reference cell |
| `column_index` | int | Yes | 0-based column index of the reference cell |
| `insert_below` | bool | No | Insert below the reference row (default: true). If false, inserts above. |

**Returns:** BatchUpdate response confirming row insertion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "insertTableRow": {
      "tableCellLocation": {
        "tableStartLocation": {"index": 5},
        "rowIndex": 1,
        "columnIndex": 0
      },
      "insertBelow": true
    }
  }]
}
```

#### `gdocs_insert_table_column`
Insert a column into an existing table.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `table_start_index` | int | Yes | Start index of the table in the document |
| `row_index` | int | Yes | 0-based row index of the reference cell |
| `column_index` | int | Yes | 0-based column index of the reference cell |
| `insert_right` | bool | No | Insert to the right of the reference column (default: true). If false, inserts left. |

**Returns:** BatchUpdate response confirming column insertion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "insertTableColumn": {
      "tableCellLocation": {
        "tableStartLocation": {"index": 5},
        "rowIndex": 0,
        "columnIndex": 1
      },
      "insertRight": true
    }
  }]
}
```

#### `gdocs_delete_table_row`
Delete a row from a table.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `table_start_index` | int | Yes | Start index of the table in the document |
| `row_index` | int | Yes | 0-based row index of the reference cell |
| `column_index` | int | Yes | 0-based column index of the reference cell |

**Returns:** BatchUpdate response confirming row deletion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "deleteTableRow": {
      "tableCellLocation": {
        "tableStartLocation": {"index": 5},
        "rowIndex": 2,
        "columnIndex": 0
      }
    }
  }]
}
```

#### `gdocs_delete_table_column`
Delete a column from a table.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `table_start_index` | int | Yes | Start index of the table in the document |
| `row_index` | int | Yes | 0-based row index of the reference cell |
| `column_index` | int | Yes | 0-based column index of the reference cell |

**Returns:** BatchUpdate response confirming column deletion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "deleteTableColumn": {
      "tableCellLocation": {
        "tableStartLocation": {"index": 5},
        "rowIndex": 0,
        "columnIndex": 3
      }
    }
  }]
}
```

#### `gdocs_insert_inline_image`
Insert an image from a URL at a specified index.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `uri` | str | Yes | Public URL of the image to insert |
| `index` | int | Yes | Index position to insert the image |
| `width_pt` | float | No | Image width in points (72 points = 1 inch) |
| `height_pt` | float | No | Image height in points |
| `segment_id` | str | No | Segment: empty string for body (default), or header/footer/footnote ID |

**Returns:** BatchUpdate response with `inlineObjectId` of the inserted image.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "insertInlineImage": {
      "uri": "https://example.com/image.png",
      "location": {"index": 1, "segmentId": ""},
      "objectSize": {
        "width": {"magnitude": 200, "unit": "PT"},
        "height": {"magnitude": 100, "unit": "PT"}
      }
    }
  }]
}
```
**Note:** If `objectSize` is omitted, the image is inserted at its natural size. The image URL must be publicly accessible or accessible to the service account.

#### `gdocs_insert_page_break`
Insert a page break at a specified index.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `index` | int | Yes | Index position to insert the page break |
| `segment_id` | str | No | Segment: empty string for body (default), or header/footer/footnote ID |

**Returns:** BatchUpdate response confirming page break insertion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "insertPageBreak": {
      "location": {"index": 50, "segmentId": ""}
    }
  }]
}
```

---

### Tier 5: Table Formatting Operations (6 tools)

#### `gdocs_update_table_column_properties`
Set column width for a table column.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `table_start_index` | int | Yes | Start index of the table in the document |
| `column_indices` | list[int] | Yes | 0-based column indices to update |
| `width_pt` | float | Yes | Column width in points |
| `width_type` | str | No | Width type: `EVENLY_DISTRIBUTED` (default) or `FIXED_WIDTH` |

**Returns:** BatchUpdate response confirming column width update.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "updateTableColumnProperties": {
      "tableStartLocation": {"index": 5},
      "columnIndices": [0, 1],
      "tableColumnProperties": {
        "widthType": "FIXED_WIDTH",
        "width": {"magnitude": 100, "unit": "PT"}
      },
      "fields": "widthType,width"
    }
  }]
}
```

#### `gdocs_update_table_cell_style`
Update cell formatting for a range of table cells.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `table_start_index` | int | Yes | Start index of the table in the document |
| `row_start` | int | Yes | Start row index (inclusive, 0-based) |
| `row_end` | int | Yes | End row index (exclusive) |
| `column_start` | int | Yes | Start column index (inclusive, 0-based) |
| `column_end` | int | Yes | End column index (exclusive) |
| `background_color_red` | float | No | Background color red (0.0-1.0) |
| `background_color_green` | float | No | Background color green (0.0-1.0) |
| `background_color_blue` | float | No | Background color blue (0.0-1.0) |
| `padding_top_pt` | float | No | Top padding in points |
| `padding_bottom_pt` | float | No | Bottom padding in points |
| `padding_left_pt` | float | No | Left padding in points |
| `padding_right_pt` | float | No | Right padding in points |
| `content_alignment` | str | No | Vertical alignment: `TOP`, `MIDDLE`, `BOTTOM` |

**Returns:** BatchUpdate response confirming cell style update.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "updateTableCellStyle": {
      "tableRange": {
        "tableCellLocation": {
          "tableStartLocation": {"index": 5},
          "rowIndex": 0,
          "columnIndex": 0
        },
        "rowSpan": 2,
        "columnSpan": 3
      },
      "tableCellStyle": {
        "backgroundColor": {"color": {"rgbColor": {"red": 0.9, "green": 0.9, "blue": 0.9}}},
        "paddingTop": {"magnitude": 5, "unit": "PT"},
        "contentAlignment": "MIDDLE"
      },
      "fields": "backgroundColor,paddingTop,contentAlignment"
    }
  }]
}
```

#### `gdocs_update_table_row_style`
Update row height for table rows.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `table_start_index` | int | Yes | Start index of the table in the document |
| `row_index` | int | Yes | 0-based row index to update |
| `min_row_height_pt` | float | Yes | Minimum row height in points |

**Returns:** BatchUpdate response confirming row style update.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "updateTableRowStyle": {
      "tableStartLocation": {"index": 5},
      "rowIndex": 0,
      "tableRowStyle": {
        "minRowHeight": {"magnitude": 30, "unit": "PT"}
      },
      "fields": "minRowHeight"
    }
  }]
}
```

#### `gdocs_merge_table_cells`
Merge a rectangular range of table cells.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `table_start_index` | int | Yes | Start index of the table in the document |
| `row_index` | int | Yes | 0-based row index of the top-left cell |
| `column_index` | int | Yes | 0-based column index of the top-left cell |
| `row_span` | int | Yes | Number of rows to merge |
| `column_span` | int | Yes | Number of columns to merge |

**Returns:** BatchUpdate response confirming cell merge.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "mergeTableCells": {
      "tableRange": {
        "tableCellLocation": {
          "tableStartLocation": {"index": 5},
          "rowIndex": 0,
          "columnIndex": 0
        },
        "rowSpan": 2,
        "columnSpan": 2
      }
    }
  }]
}
```

#### `gdocs_unmerge_table_cells`
Unmerge previously merged table cells.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `table_start_index` | int | Yes | Start index of the table in the document |
| `row_index` | int | Yes | 0-based row index of the top-left cell of the merged region |
| `column_index` | int | Yes | 0-based column index of the top-left cell of the merged region |
| `row_span` | int | Yes | Number of rows in the merged region |
| `column_span` | int | Yes | Number of columns in the merged region |

**Returns:** BatchUpdate response confirming cell unmerge.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "unmergeTableCells": {
      "tableRange": {
        "tableCellLocation": {
          "tableStartLocation": {"index": 5},
          "rowIndex": 0,
          "columnIndex": 0
        },
        "rowSpan": 2,
        "columnSpan": 2
      }
    }
  }]
}
```

#### `gdocs_pin_table_header_rows`
Pin rows as repeating header rows in a table (they repeat on each page if table spans pages).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `table_start_index` | int | Yes | Start index of the table in the document |
| `pinned_header_row_count` | int | Yes | Number of rows to pin as headers (0 to unpin) |

**Returns:** BatchUpdate response confirming header pinning.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "pinTableHeaderRows": {
      "tableStartLocation": {"index": 5},
      "pinnedHeaderRowsCount": 1
    }
  }]
}
```

---

### Tier 6: Named Range Operations (2 tools)

#### `gdocs_create_named_range`
Create a named range over a content range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `name` | str | Yes | Name for the range |
| `start_index` | int | Yes | Start index of the range (inclusive) |
| `end_index` | int | Yes | End index of the range (exclusive) |
| `segment_id` | str | No | Segment: empty string for body (default), or header/footer/footnote ID |

**Returns:** BatchUpdate response with `namedRangeId` in the reply.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "createNamedRange": {
      "name": "my_range",
      "range": {
        "startIndex": 10,
        "endIndex": 25,
        "segmentId": ""
      }
    }
  }]
}
```

#### `gdocs_delete_named_range`
Delete a named range by ID or by name.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `named_range_id` | str | No | Named range ID to delete (mutually exclusive with `name`) |
| `name` | str | No | Named range name to delete (mutually exclusive with `named_range_id`) |

**Returns:** BatchUpdate response confirming deletion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body (by ID):**
```json
{
  "requests": [{
    "deleteNamedRange": {
      "namedRangeId": "kix.abc123"
    }
  }]
}
```
**Body (by name):**
```json
{
  "requests": [{
    "deleteNamedRange": {
      "name": "my_range"
    }
  }]
}
```

---

### Tier 7: List (Bullet) Operations (2 tools)

#### `gdocs_create_paragraph_bullets`
Add bullet or numbered list formatting to a range of paragraphs.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `start_index` | int | Yes | Start index of paragraph range (inclusive) |
| `end_index` | int | Yes | End index of paragraph range (exclusive) |
| `bullet_preset` | str | Yes | Bullet preset: `BULLET_DISC_CIRCLE_SQUARE`, `BULLET_DIAMONDX_ARROW3D_SQUARE`, `BULLET_CHECKBOX`, `BULLET_ARROW_DIAMOND_DISC`, `BULLET_STAR_CIRCLE_SQUARE`, `BULLET_ARROW3D_CIRCLE_SQUARE`, `BULLET_LEFTTRIANGLE_DIAMOND_DISC`, `BULLET_DIAMONDX_HOLLOWDIAMOND_SQUARE`, `BULLET_DIAMOND_CIRCLE_SQUARE`, `NUMBERED_DECIMAL_ALPHA_ROMAN`, `NUMBERED_DECIMAL_ALPHA_ROMAN_PARENS`, `NUMBERED_DECIMAL_NESTED`, `NUMBERED_UPPERALPHA_ALPHA_ROMAN`, `NUMBERED_UPPERROMAN_UPPERALPHA_DECIMAL`, `NUMBERED_ZERODECIMAL_ALPHA_ROMAN` |
| `segment_id` | str | No | Segment: empty string for body (default) |

**Returns:** BatchUpdate response confirming bullet creation.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "createParagraphBullets": {
      "range": {
        "startIndex": 1,
        "endIndex": 50,
        "segmentId": ""
      },
      "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"
    }
  }]
}
```

#### `gdocs_delete_paragraph_bullets`
Remove bullet/numbered list formatting from a range of paragraphs.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `start_index` | int | Yes | Start index of paragraph range (inclusive) |
| `end_index` | int | Yes | End index of paragraph range (exclusive) |
| `segment_id` | str | No | Segment: empty string for body (default) |

**Returns:** BatchUpdate response confirming bullet removal.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "deleteParagraphBullets": {
      "range": {
        "startIndex": 1,
        "endIndex": 50,
        "segmentId": ""
      }
    }
  }]
}
```

---

### Tier 8: Section & Document Style Operations (3 tools)

#### `gdocs_insert_section_break`
Insert a section break at a specified index.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `index` | int | Yes | Index position to insert the section break |
| `section_type` | str | No | Section type: `CONTINUOUS` (default) or `NEXT_PAGE` |
| `segment_id` | str | No | Segment: empty string for body (default) |

**Returns:** BatchUpdate response confirming section break insertion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "insertSectionBreak": {
      "location": {"index": 50, "segmentId": ""},
      "sectionType": "NEXT_PAGE"
    }
  }]
}
```

#### `gdocs_update_document_style`
Update page-level document styles (page size, margins, background color).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `page_width_pt` | float | No | Page width in points (default US Letter: 612) |
| `page_height_pt` | float | No | Page height in points (default US Letter: 792) |
| `margin_top_pt` | float | No | Top margin in points |
| `margin_bottom_pt` | float | No | Bottom margin in points |
| `margin_left_pt` | float | No | Left margin in points |
| `margin_right_pt` | float | No | Right margin in points |
| `background_color_red` | float | No | Page background red (0.0-1.0) |
| `background_color_green` | float | No | Page background green (0.0-1.0) |
| `background_color_blue` | float | No | Page background blue (0.0-1.0) |
| `use_first_page_header_footer` | bool | No | Whether the first page has a different header/footer |
| `default_header_id` | str | No | ID of the default header |
| `default_footer_id` | str | No | ID of the default footer |

**Returns:** BatchUpdate response confirming document style update.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "updateDocumentStyle": {
      "documentStyle": {
        "pageSize": {
          "width": {"magnitude": 612, "unit": "PT"},
          "height": {"magnitude": 792, "unit": "PT"}
        },
        "marginTop": {"magnitude": 72, "unit": "PT"},
        "marginBottom": {"magnitude": 72, "unit": "PT"},
        "marginLeft": {"magnitude": 72, "unit": "PT"},
        "marginRight": {"magnitude": 72, "unit": "PT"},
        "background": {"color": {"rgbColor": {"red": 1.0, "green": 1.0, "blue": 1.0}}}
      },
      "fields": "pageSize,marginTop,marginBottom,marginLeft,marginRight,background"
    }
  }]
}
```

#### `gdocs_update_section_style`
Update section-level styles (column configuration).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `start_index` | int | Yes | Start index of the section range (inclusive) |
| `end_index` | int | Yes | End index of the section range (exclusive) |
| `column_count` | int | No | Number of text columns (1, 2, or 3) |
| `column_separator_style` | str | No | Separator between columns: `NONE`, `BETWEEN_EACH_COLUMN` |
| `content_direction` | str | No | Content direction: `LEFT_TO_RIGHT` or `RIGHT_TO_LEFT` |
| `section_type` | str | No | Section type: `CONTINUOUS` or `NEXT_PAGE` |
| `segment_id` | str | No | Segment: empty string for body (default) |

**Returns:** BatchUpdate response confirming section style update.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "updateSectionStyle": {
      "range": {
        "startIndex": 0,
        "endIndex": 100,
        "segmentId": ""
      },
      "sectionStyle": {
        "columnProperties": [
          {"width": {"magnitude": 200, "unit": "PT"}, "paddingEnd": {"magnitude": 12, "unit": "PT"}},
          {"width": {"magnitude": 200, "unit": "PT"}}
        ],
        "columnSeparatorStyle": "BETWEEN_EACH_COLUMN",
        "sectionType": "CONTINUOUS"
      },
      "fields": "columnProperties,columnSeparatorStyle,sectionType"
    }
  }]
}
```

---

### Tier 9: Header, Footer & Footnote Operations (5 tools)

#### `gdocs_create_header`
Create a header for a section.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `section_break_index` | int | Yes | Index of the section break whose section gets the header. Use 0 for the first section (document start). |
| `type` | str | No | Header type: `DEFAULT` (default) or `FIRST_PAGE` |

**Returns:** BatchUpdate response with `headerId` in the reply.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "createHeader": {
      "sectionBreakLocation": {"index": 0, "segmentId": ""},
      "type": "DEFAULT"
    }
  }]
}
```

#### `gdocs_create_footer`
Create a footer for a section.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `section_break_index` | int | Yes | Index of the section break whose section gets the footer. Use 0 for the first section. |
| `type` | str | No | Footer type: `DEFAULT` (default) or `FIRST_PAGE` |

**Returns:** BatchUpdate response with `footerId` in the reply.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "createFooter": {
      "sectionBreakLocation": {"index": 0, "segmentId": ""},
      "type": "DEFAULT"
    }
  }]
}
```

#### `gdocs_delete_header`
Delete a header by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `header_id` | str | Yes | Header ID to delete (obtained from `gdocs_get_document` or `gdocs_create_header`) |

**Returns:** BatchUpdate response confirming deletion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "deleteHeader": {
      "headerId": "kix.abc123"
    }
  }]
}
```

#### `gdocs_delete_footer`
Delete a footer by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `footer_id` | str | Yes | Footer ID to delete (obtained from `gdocs_get_document` or `gdocs_create_footer`) |

**Returns:** BatchUpdate response confirming deletion.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "deleteFooter": {
      "footerId": "kix.def456"
    }
  }]
}
```

#### `gdocs_create_footnote`
Create a footnote at a specified index. The footnote content can then be edited using `gdocs_insert_text` with the footnote's segment ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `index` | int | Yes | Index position to insert the footnote reference |
| `segment_id` | str | No | Segment: empty string for body (default) |

**Returns:** BatchUpdate response with `footnoteId` in the reply.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "createFootnote": {
      "location": {"index": 25, "segmentId": ""}
    }
  }]
}
```

---

### Tier 10: Replace & Image Operations (2 tools)

#### `gdocs_replace_named_range_content`
Replace the content of all instances of a named range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `named_range_id` | str | No | Named range ID (mutually exclusive with `name`) |
| `name` | str | No | Named range name (mutually exclusive with `named_range_id`) |
| `text` | str | Yes | Replacement text |

**Returns:** BatchUpdate response confirming replacement.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body (by ID):**
```json
{
  "requests": [{
    "replaceNamedRangeContent": {
      "namedRangeId": "kix.abc123",
      "text": "new content"
    }
  }]
}
```

#### `gdocs_replace_image`
Replace an existing inline image with a new image from a URL.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | str | No | Document ID (uses default if not provided) |
| `image_object_id` | str | Yes | Object ID of the inline image to replace (found in `inlineObjects` from `gdocs_get_document`) |
| `uri` | str | Yes | Public URL of the replacement image |
| `image_replace_method` | str | No | Replace method: `CENTER_CROP` (default) or `SIZE_TO_FIT` |

**Returns:** BatchUpdate response confirming image replacement.
**Endpoint:** `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
**Body:**
```json
{
  "requests": [{
    "replaceImage": {
      "imageObjectId": "kix.img123",
      "uri": "https://example.com/new-image.png",
      "imageReplaceMethod": "CENTER_CROP"
    }
  }]
}
```

---

## Tool Summary

| Tier | Category | Tools | Count |
|------|----------|-------|-------|
| 1 | Document Operations | `gdocs_create_document`, `gdocs_get_document`, `gdocs_batch_update` | 3 |
| 2 | Text Content | `gdocs_insert_text`, `gdocs_delete_content`, `gdocs_replace_all_text` | 3 |
| 3 | Formatting | `gdocs_update_text_style`, `gdocs_update_paragraph_style` | 2 |
| 4 | Structural Elements | `gdocs_insert_table`, `gdocs_insert_table_row`, `gdocs_insert_table_column`, `gdocs_delete_table_row`, `gdocs_delete_table_column`, `gdocs_insert_inline_image`, `gdocs_insert_page_break` | 7 |
| 5 | Table Formatting | `gdocs_update_table_column_properties`, `gdocs_update_table_cell_style`, `gdocs_update_table_row_style`, `gdocs_merge_table_cells`, `gdocs_unmerge_table_cells`, `gdocs_pin_table_header_rows` | 6 |
| 6 | Named Ranges | `gdocs_create_named_range`, `gdocs_delete_named_range` | 2 |
| 7 | Lists (Bullets) | `gdocs_create_paragraph_bullets`, `gdocs_delete_paragraph_bullets` | 2 |
| 8 | Section & Document Style | `gdocs_insert_section_break`, `gdocs_update_document_style`, `gdocs_update_section_style` | 3 |
| 9 | Headers, Footers & Footnotes | `gdocs_create_header`, `gdocs_create_footer`, `gdocs_delete_header`, `gdocs_delete_footer`, `gdocs_create_footnote` | 5 |
| 10 | Replace & Image | `gdocs_replace_named_range_content`, `gdocs_replace_image` | 2 |
| | **Total** | | **35** |

---

## Architecture Decisions

### 1. Shared Auth with Sheets Integration
Reuse the same `GOOGLE_SERVICE_ACCOUNT_JSON` config variable. However, the Docs tool needs its **own** `_credentials` and `_client` instances because:
- The OAuth scope is different (`documents` vs `spreadsheets`)
- The base URL is different (`docs.googleapis.com` vs `sheets.googleapis.com`)
- Token refresh is independent

The pattern is identical to `sheets_tool.py`:
```python
_credentials = None
_client: httpx.AsyncClient | None = None
BASE = "https://docs.googleapis.com/v1/documents"

def _get_token() -> str:
    # Same pattern as sheets, but scope = "https://www.googleapis.com/auth/documents"
    ...

async def _get_client() -> httpx.AsyncClient:
    # Same singleton httpx.AsyncClient pattern
    ...
```

### 2. Shared batchUpdate Helper
Since nearly all write operations go through `documents.batchUpdate`, provide a shared `_batch_update()` helper:
```python
async def _batch_update(document_id: str, requests: list[dict]) -> dict:
    data = await _req(
        "POST", f"/{document_id}:batchUpdate",
        json_body={"requests": requests},
    )
    return data if isinstance(data, dict) else {"raw": data}
```

Each convenience tool (insert_text, delete_content, etc.) constructs its specific request object and delegates to `_batch_update()`. The raw `gdocs_batch_update` tool exposes `_batch_update()` directly for advanced use cases.

### 3. Default Document ID Pattern
Follow the same pattern as Sheets' `_sid()` helper:
```python
def _did(override: str | None) -> str:
    did = override or GDOCS_DEFAULT_DOCUMENT_ID
    if not did:
        raise ToolError(
            "No document_id provided. Pass document_id or set "
            "GDOCS_DEFAULT_DOCUMENT_ID."
        )
    return did
```

### 4. Fields Mask Builder for Style Updates
The `updateTextStyle` and `updateParagraphStyle` requests require a `fields` parameter that lists which properties are being set. Build this dynamically:
```python
def _build_fields_mask(style_dict: dict) -> str:
    """Build comma-separated fields mask from non-None style properties."""
    return ",".join(style_dict.keys())
```
Only include properties in the style dict when the corresponding parameter is not None. This ensures only explicitly set properties are modified.

### 5. Location and Range Helpers
Provide helper functions to reduce boilerplate:
```python
def _location(index: int, segment_id: str = "") -> dict:
    loc: dict = {"index": index}
    if segment_id:
        loc["segmentId"] = segment_id
    return loc

def _range(start_index: int, end_index: int, segment_id: str = "") -> dict:
    r: dict = {"startIndex": start_index, "endIndex": end_index}
    if segment_id:
        r["segmentId"] = segment_id
    return r

def _table_cell_location(
    table_start_index: int, row_index: int, column_index: int,
) -> dict:
    return {
        "tableStartLocation": {"index": table_start_index},
        "rowIndex": row_index,
        "columnIndex": column_index,
    }
```

### 6. Index-Based Content Addressing Strategy
Document to users (in tool docstrings) that:
- Body content starts at index 1
- Use `gdocs_get_document` first to discover current indexes before editing
- When making multiple edits, work from **highest index to lowest** to avoid index shift issues
- Alternatively, use `gdocs_batch_update` to send multiple requests that are applied in order

### 7. File Structure
Single file: `src/mcp_toolbox/tools/gdocs_tool.py` following the existing convention (one file per integration).

---

## Key Quirks & Gotchas

1. **Index shifting** -- Every insert or delete changes all subsequent indexes. When making multiple edits in a single `batchUpdate`, requests are processed in array order. Work from end of document backward, or recalculate indexes between operations.

2. **Body starts at index 1** -- Index 0 is the document start sentinel. Inserting at index 0 will fail. The first valid insertion point is index 1.

3. **Trailing newline** -- Every document has at least one paragraph, and every paragraph ends with `\n`. You cannot delete the final newline of the document body.

4. **Table cell content** -- Each table cell contains its own nested body content with its own index space. However, the indexes in the Docs API are **global** (document-wide), not relative to the cell. Use `gdocs_get_document` to discover the actual indexes of table cell content.

5. **Segment IDs** -- Headers, footers, and footnotes are separate "segments" with their own content. To edit them, pass the appropriate `segmentId` (headerId, footerId, or footnoteId) to text/style operations. An empty string or omitted segmentId targets the document body.

6. **Fields mask is mandatory for style updates** -- `updateTextStyle`, `updateParagraphStyle`, `updateDocumentStyle`, `updateSectionStyle`, `updateTableColumnProperties`, `updateTableCellStyle`, and `updateTableRowStyle` all require a `fields` parameter. Omitting it results in an error. Only properties listed in `fields` are modified.

7. **Service account sharing** -- The service account email must be added as an editor on existing documents (via Google Drive sharing), or the document must be created by the service account. Documents created by the service account are owned by it and are not visible in any user's Drive unless explicitly shared.

8. **Image URLs must be publicly accessible** -- `insertInlineImage` and `replaceImage` require a publicly accessible URL. Google Drive URLs can work if the file is shared publicly, but the direct download URL format must be used.

9. **No pagination on get** -- `documents.get` returns the entire document in one response. Very large documents may produce large JSON responses. There is no built-in pagination for document content.

10. **Revision tracking** -- `documents.get` returns a `revisionId`. You can pass `requiredRevisionId` in `batchUpdate` to ensure you're editing the expected version (optimistic concurrency).

11. **batchUpdate is atomic per request array** -- If any request in the array fails, the entire batch fails and no changes are applied. This is useful for transactional updates but means one bad request rolls back all preceding requests in the same batch.

12. **Units** -- All dimension values (font size, margins, page size, padding, etc.) use a `Dimension` object with `magnitude` (float) and `unit` (always `"PT"` for points). 72 points = 1 inch.

---

## Dependencies

### Existing (no new packages needed)
- `httpx` -- async HTTP client (already in project)
- `google-auth[requests]` -- service account auth (already installed for Sheets)

### Config Changes
- Add `GDOCS_DEFAULT_DOCUMENT_ID` to `config.py`

### Registration
- Add `gdocs_tool` to `tools/__init__.py` `register_all_tools()` function

---

## Test Strategy

### Unit Tests
- Test `_did()` helper with/without default document ID
- Test `_location()`, `_range()`, `_table_cell_location()` helpers produce correct dicts
- Test fields mask builder generates correct comma-separated strings
- Test each tool function constructs the correct request body structure

### Integration Tests (with mocked httpx)
- Mock `_req()` to verify correct HTTP method, URL, and body for each tool
- Test `gdocs_create_document` sends POST to `/`
- Test `gdocs_get_document` sends GET to `/{documentId}`
- Test `gdocs_batch_update` sends POST to `/{documentId}:batchUpdate`
- Test convenience tools (insert_text, delete_content, etc.) delegate to `_batch_update` with correct request structure
- Test error handling for 429 (rate limit) and 400+ status codes
- Test auth flow (credential loading, token refresh)

### Test File
`tests/test_gdocs_tool.py` -- following existing test patterns in the project.
