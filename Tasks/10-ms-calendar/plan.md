# Task 10: MS Graph Calendar - Implementation Plan

## Overview
23 calendar tools using Microsoft Graph API. Same msal/httpx pattern as o365_tool.py — independent module with own helpers, reusing O365 credentials. No new dependencies.

## Implementation
Self-contained `calendar_tool.py` with own `_get_token()`, `_get_http_client()`, `_request()`, `_get_user_id()` (all identical to o365_tool.py pattern). All tools prefixed `calendar_`. 23 tools across 8 categories. Update __init__.py, test_server.py, CLAUDE.md. Write tests with respx + msal mocking. Target: 228 + 23 = 251 tools.
