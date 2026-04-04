# Task 14: Google Sheets - Implementation Plan

## Overview
27 tools across 8 tiers. Google Service Account auth via `google-auth[requests]`. httpx for REST calls. Bearer token with auto-refresh. New dependency required. Target: 415 + 27 = 442 tools.

## New Dependency
- `google-auth[requests]>=2.0.0` in pyproject.toml

## Config
- `GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE` — path to JSON key file
- `GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID` — optional default spreadsheet ID

## Implementation
- `src/mcp_toolbox/tools/sheets_tool.py` — 27 tools
- Auth: `google.oauth2.service_account.Credentials` with sheets scope, auto-refresh
- Helper: `_get_headers()` refreshes token if expired, returns auth headers
- Helper: `_req()` for httpx calls with Bearer token
- Helper: `_batch_update()` for batchUpdate requests (used by ~15 tools)
- All batchUpdate tools route through spreadsheets.batchUpdate endpoint
