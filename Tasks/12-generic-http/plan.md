# Task 12: Generic HTTP Tools - Implementation Plan

## Overview
4 tools, no new deps, no config. Code patterns are fully specified in the analysis.

**Steps:** Create http_tool.py from analysis code → register → tests → update test_server.py → CLAUDE.md → validate.

## Implementation
The analysis contains complete implementation code for all 4 tools. Assemble into `src/mcp_toolbox/tools/http_tool.py` with shared response parser helper. Add `http_tool` to `__init__.py`. Write tests using respx. Update test_server.py to 228 tools.
