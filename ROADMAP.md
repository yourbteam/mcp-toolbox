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

*Last updated: 2026-04-04*
