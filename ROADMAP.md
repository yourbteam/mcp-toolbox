# MCP Toolbox — Integration Roadmap

## Current State (898 tools across 24 integrations)

| # | Integration | Tools | Category | Status |
|---|-------------|-------|----------|--------|
| 1 | SendGrid | 14 | Email (transactional) | Done |
| 2 | ClickUp | 81 | Project Management | Done |
| 3 | O365 Email | 19 | Email (corporate) | Done |
| 4 | Microsoft Teams | 28 | Messaging / Meetings | Done |
| 5 | Azure Key Vault | 39 | Secrets / Keys / Certificates | Done |
| 6 | AWS Parameter Store | 13 | Configuration / Secrets | Done |
| 7 | Slack | 28 | Messaging / Collaboration | Done |
| 8 | Generic HTTP | 4 | Flexibility / Any API | Done |
| 9 | MS Graph Calendar | 23 | Calendar & Scheduling | Done |
| 10 | HubSpot CRM | 43 | CRM | Done |
| 11 | Jira | 44 | Dev/IT Workflows | Done |
| 12 | Stripe | 77 | Finance & Payments | Done |
| 13 | Google Sheets | 27 | Data & Spreadsheets | Done |
| 14 | QuickBooks Online | 46 | Finance & Accounting | Done |
| 15 | GitHub | 75 | Dev/IT Workflows | Done |
| 16 | Google Tasks | 14 | Task Management | Done |
| 17 | Google Calendar | 34 | Calendar & Scheduling | Done |
| 18 | Google Docs | 35 | Document Management | Done |
| 19 | Gmail | 62 | Email (Google) | Done |
| 20 | Notion | 21 | Knowledge Management | Done |
| 21 | Google Drive | 37 | File Management | Done |
| 22 | Zendesk | 66 | Customer Support | Done |
| 23 | Salesforce | 66 | CRM (Enterprise) | Done |
| **Total** | | **898** (+ 2 example) | | |

---

## Planned Integrations

### Phase 1 — Data & Low-Code
| Integration | Description | Auth | New Deps? |
|-------------|-------------|------|-----------|
| **Airtable** | Structured data with rich field types. | API key | No (httpx) |

### Phase 2 — Dev/IT (Extended)
| Integration | Description | Auth | New Deps? |
|-------------|-------------|------|-----------|
| **PagerDuty** | Incidents, escalations, on-call schedules. | API key | No (httpx) |

### Phase 3 — Finance (Extended)
| Integration | Description | Auth | New Deps? |
|-------------|-------------|------|-----------|
| **Xero** | Invoices, contacts, bank transactions. | OAuth2 | No (httpx) |

### Phase 4 — Customer Support (Extended)
| Integration | Description | Auth | New Deps? |
|-------------|-------------|------|-----------|
| **Freshdesk** | Tickets, contacts, agents. | API key | No (httpx) |
| **Intercom** | Conversations, contacts, messages. | API token | No (httpx) |

### Phase 5 — HR & People
| Integration | Description | Auth | New Deps? |
|-------------|-------------|------|-----------|
| **BambooHR** | Employees, time off, directory, reports. | API key | No (httpx) |
| **Gusto** | Payroll, benefits, onboarding. | OAuth2 | No (httpx) |

### Phase 6 — Document & Knowledge (Extended)
| Integration | Description | Auth | New Deps? |
|-------------|-------------|------|-----------|
| **SharePoint/OneDrive** | Files via Microsoft Graph. | O365 credentials | No |
| **Confluence** | Pages, spaces, search. | API token | No (httpx) |

### Phase 7 — Communication (Extended)
| Integration | Description | Auth | New Deps? |
|-------------|-------------|------|-----------|
| **Twilio** | SMS, WhatsApp, voice calls. | Account SID + Auth Token | `twilio` |
| **Discord** | Messages, channels, guilds. | Bot token | No (httpx) |

---

## Estimated Tool Counts

| Phase | Integrations | Est. Tools | Running Total |
|-------|-------------|------------|---------------|
| Current | 24 | 898 | 898 |
| Phase 1 | Airtable | ~15 | ~913 |
| Phase 2 | PagerDuty | ~15 | ~928 |
| Phase 3 | Xero | ~20 | ~948 |
| Phase 4 | 2 (Support) | ~25 | ~973 |
| Phase 5 | 2 (HR) | ~15 | ~988 |
| Phase 6 | 2 (Docs) | ~30 | ~1018 |
| Phase 7 | 2 (Comms) | ~20 | ~1038 |

**Target: ~1,000 tools** covering major SaaS integrations for cross-industry workflow automation.

---

## Pending Hardening Tasks

### HTTP Tool Security Hardening
The Generic HTTP tool (`http_tool.py`) has 9 security/robustness findings from the L1 audit that need addressing:

1. **Path traversal** — `http_download` can write to any writable path; restrict to allowed directory
2. **Arbitrary file read** — `http_upload` can read any file; restrict to allowed directory
3. **Unbounded memory** — `http_request` has no upper cap on `max_response_size`; clamp to 500KB
4. **Full response in memory** — `response.text` loads entire body before truncating; use streaming
5. **Partial file cleanup** — `http_download` only cleans up on `ToolError`, not other exceptions; use `try/finally`
6. **Sync file I/O** — `http_upload` reads files synchronously in async context
7. **Header injection** — `headers` dict passed without validation (httpx mitigates, but defense-in-depth)
8. **JSON truncation** — Truncated JSON returns broken string instead of structured indicator
9. **Form data types** — `http_request_form` doesn't coerce dict values to strings

**Priority:** Medium — these are design decisions about how permissive the "escape hatch" tool should be. Not API correctness bugs, but important for production deployments.

### L2 Contract Tests
Add request-body assertions to existing unit tests to verify the exact JSON/form bodies sent to APIs (not just response parsing). Estimated ~900 additional assertions across the test suite. This catches wrong field names, missing wrapper keys, and incorrect nesting that mocked tests currently miss.

---

*Last updated: 2026-04-04*
