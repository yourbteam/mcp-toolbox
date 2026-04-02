# Task 11: HubSpot CRM Integration - Analysis & Requirements

## Objective
Add HubSpot CRM as a tool integration in mcp-toolbox, exposing CRM capabilities (contacts, companies, deals, tickets, notes, associations, pipelines) as MCP tools for LLM clients.

---

## API Technical Details

### API v3/v4 -- REST
- **Base URL:** `https://api.hubapi.com`
- **Auth:** Private App Token via `Authorization: Bearer pat-xx-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` header
- **Format:** JSON request/response
- **API Versions:** CRM objects use v3 (`/crm/v3/objects/...`), associations use v4 (`/crm/v4/...`), pipelines use v3 (`/crm/v3/pipelines/...`)

### Rate Limits

| Metric | Limit |
|--------|-------|
| Burst (all plans) | 190 requests / 10 seconds per private app |
| Daily (Professional) | 650,000 requests / day per account |
| Daily (Enterprise) | 1,000,000 requests / day per account |
| Search endpoints | 5 requests / second per app |

- HTTP 429 on exceed with `Retry-After` header
- Rate limit headers: `X-HubSpot-RateLimit-Daily`, `X-HubSpot-RateLimit-Daily-Remaining`

### No Official Python SDK Needed
HubSpot offers `hubspot-api-client` but it adds unnecessary complexity. **Recommendation:** Use `httpx` (already in our dependencies) for direct async HTTP calls -- consistent with ClickUp pattern, simpler, full async control.

### Key Quirks
- **Properties object pattern** -- all CRM object create/update requests wrap data in `{"properties": {...}}`
- **Search uses POST** -- search endpoints are `POST /crm/v3/objects/{objectType}/search` with filter body
- **filterGroups limit** -- max 5 filterGroups, 10 filters per group, 25 filters total (expanded August 2024)
- **Pagination via `after` cursor** -- not page numbers; responses include `paging.next.after` for next page
- **Default properties only** -- GET requests return only default properties; use `?properties=prop1,prop2` to request additional ones
- **Associations are directional** -- contact-to-company has a different association type ID than company-to-contact
- **Associations v4** -- newer association endpoints use `/crm/v4/` while object CRUD uses `/crm/v3/`
- **Timestamps in ISO 8601** -- unlike ClickUp, HubSpot uses standard ISO datetime strings
- **Archived records excluded by default** -- pass `?archived=true` to include them

---

## HubSpot CRM Object Model

```
Contacts <-----> Companies
   |                |
   v                v
  Deals <--------> Tickets
   |
   v
Pipeline --> Stages
   |
   v
Notes/Engagements (attached to any object)
```

### Core CRM Objects
| Object | API Path | Key Properties |
|--------|----------|----------------|
| Contacts | `/crm/v3/objects/contacts` | email, firstname, lastname, phone, company, lifecyclestage |
| Companies | `/crm/v3/objects/companies` | name, domain, industry, phone, city, state |
| Deals | `/crm/v3/objects/deals` | dealname, amount, dealstage, pipeline, closedate, hubspot_owner_id |
| Tickets | `/crm/v3/objects/tickets` | subject, content, hs_pipeline, hs_pipeline_stage, hs_ticket_priority |
| Notes | `/crm/v3/objects/notes` | hs_note_body, hs_timestamp, hubspot_owner_id |

---

## Tool Specifications

### Tier 1: Contacts (6 tools)

#### `hubspot_create_contact`
Create a new contact in HubSpot CRM.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | str | Yes | Contact email address (primary identifier) |
| `firstname` | str | No | First name |
| `lastname` | str | No | Last name |
| `phone` | str | No | Phone number |
| `company` | str | No | Company name (text, not association) |
| `jobtitle` | str | No | Job title |
| `lifecyclestage` | str | No | Lifecycle stage (e.g., `lead`, `customer`, `subscriber`) |
| `hubspot_owner_id` | str | No | HubSpot owner ID to assign contact |
| `extra_properties` | dict | No | Additional HubSpot properties as key-value pairs |

**Returns:** Created contact with ID and properties.
**Endpoint:** `POST /crm/v3/objects/contacts`
**Body:** `{"properties": {"email": "...", "firstname": "...", ...}}`

#### `hubspot_get_contact`
Get a contact by ID or email.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `contact_id` | str | Conditional | Contact ID (use this or `email`) |
| `email` | str | Conditional | Contact email (alternative lookup via `/crm/v3/objects/contacts/{email}?idProperty=email`) |
| `properties` | list[str] | No | Specific properties to return (default: email, firstname, lastname, phone, company) |

One of `contact_id` or `email` is required.
**Returns:** Contact object with requested properties.
**Endpoint:** `GET /crm/v3/objects/contacts/{contactId}?properties=...`

#### `hubspot_update_contact`
Update an existing contact's properties.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `contact_id` | str | Yes | Contact ID |
| `email` | str | No | Updated email |
| `firstname` | str | No | Updated first name |
| `lastname` | str | No | Updated last name |
| `phone` | str | No | Updated phone number |
| `company` | str | No | Updated company name |
| `jobtitle` | str | No | Updated job title |
| `lifecyclestage` | str | No | Updated lifecycle stage |
| `hubspot_owner_id` | str | No | Updated owner ID |
| `extra_properties` | dict | No | Additional properties to update |

At least one property must be provided.
**Returns:** Updated contact object.
**Endpoint:** `PATCH /crm/v3/objects/contacts/{contactId}`
**Body:** `{"properties": {...}}`

#### `hubspot_delete_contact`
Archive (soft-delete) a contact.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `contact_id` | str | Yes | Contact ID to archive |

**Returns:** Confirmation of archival.
**Endpoint:** `DELETE /crm/v3/objects/contacts/{contactId}`

#### `hubspot_list_contacts`
List contacts with pagination.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `after` | str | No | Pagination cursor from previous response |
| `properties` | list[str] | No | Properties to include (default: email, firstname, lastname) |

**Returns:** List of contacts with paging cursor.
**Endpoint:** `GET /crm/v3/objects/contacts?limit={limit}&after={after}&properties=...`

#### `hubspot_search_contacts`
Search contacts using filters or query string.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | No | Full-text search query (searches default searchable properties) |
| `filter_groups` | list[dict] | No | Filter groups for property-based search (see filter format below) |
| `sorts` | list[dict] | No | Sort criteria, e.g., `[{"propertyName": "createdate", "direction": "DESCENDING"}]` |
| `properties` | list[str] | No | Properties to return |
| `limit` | int | No | Number of results (default 10, max 100) |
| `after` | str | No | Pagination cursor |

Either `query` or `filter_groups` should be provided.

**Filter format:** `[{"filters": [{"propertyName": "email", "operator": "CONTAINS_TOKEN", "value": "@hubspot.com"}]}]`
**Operators:** `EQ`, `NEQ`, `LT`, `LTE`, `GT`, `GTE`, `HAS_PROPERTY`, `NOT_HAS_PROPERTY`, `CONTAINS_TOKEN`, `NOT_CONTAINS_TOKEN`

**Returns:** Matching contacts with total count and paging.
**Endpoint:** `POST /crm/v3/objects/contacts/search`

---

### Tier 2: Companies (6 tools)

#### `hubspot_create_company`
Create a new company in HubSpot CRM.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Company name |
| `domain` | str | No | Company website domain (e.g., `hubspot.com`) |
| `industry` | str | No | Industry |
| `phone` | str | No | Phone number |
| `city` | str | No | City |
| `state` | str | No | State/region |
| `country` | str | No | Country |
| `description` | str | No | Company description |
| `hubspot_owner_id` | str | No | Owner ID |
| `extra_properties` | dict | No | Additional properties |

**Returns:** Created company with ID and properties.
**Endpoint:** `POST /crm/v3/objects/companies`
**Body:** `{"properties": {"name": "...", "domain": "...", ...}}`

#### `hubspot_get_company`
Get a company by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `company_id` | str | Yes | Company ID |
| `properties` | list[str] | No | Properties to return (default: name, domain, industry, phone) |

**Returns:** Company object with requested properties.
**Endpoint:** `GET /crm/v3/objects/companies/{companyId}?properties=...`

#### `hubspot_update_company`
Update an existing company's properties.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `company_id` | str | Yes | Company ID |
| `name` | str | No | Updated name |
| `domain` | str | No | Updated domain |
| `industry` | str | No | Updated industry |
| `phone` | str | No | Updated phone |
| `city` | str | No | Updated city |
| `state` | str | No | Updated state/region |
| `country` | str | No | Updated country |
| `description` | str | No | Updated description |
| `hubspot_owner_id` | str | No | Updated owner |
| `extra_properties` | dict | No | Additional properties |

At least one property must be provided.
**Returns:** Updated company object.
**Endpoint:** `PATCH /crm/v3/objects/companies/{companyId}`

#### `hubspot_delete_company`
Archive (soft-delete) a company.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `company_id` | str | Yes | Company ID to archive |

**Returns:** Confirmation of archival.
**Endpoint:** `DELETE /crm/v3/objects/companies/{companyId}`

#### `hubspot_list_companies`
List companies with pagination.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `after` | str | No | Pagination cursor |
| `properties` | list[str] | No | Properties to include (default: name, domain, industry) |

**Returns:** List of companies with paging cursor.
**Endpoint:** `GET /crm/v3/objects/companies?limit={limit}&after={after}&properties=...`

#### `hubspot_search_companies`
Search companies using filters or query string.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | No | Full-text search query |
| `filter_groups` | list[dict] | No | Property-based filter groups |
| `sorts` | list[dict] | No | Sort criteria |
| `properties` | list[str] | No | Properties to return |
| `limit` | int | No | Number of results (default 10, max 100) |
| `after` | str | No | Pagination cursor |

**Returns:** Matching companies with total count and paging.
**Endpoint:** `POST /crm/v3/objects/companies/search`

---

### Tier 3: Deals (6 tools)

#### `hubspot_create_deal`
Create a new deal in HubSpot CRM.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `dealname` | str | Yes | Deal name |
| `amount` | str | No | Deal amount (string for decimal precision) |
| `dealstage` | str | No | Deal stage ID (from pipeline stages) |
| `pipeline` | str | No | Pipeline ID (default pipeline used if omitted) |
| `closedate` | str | No | Expected close date (ISO 8601, e.g., `2026-06-15`) |
| `hubspot_owner_id` | str | No | Owner ID |
| `deal_type` | str | No | Deal type (e.g., `newbusiness`, `existingbusiness`) |
| `description` | str | No | Deal description |
| `extra_properties` | dict | No | Additional properties |

**Returns:** Created deal with ID and properties.
**Endpoint:** `POST /crm/v3/objects/deals`
**Body:** `{"properties": {"dealname": "...", "amount": "...", ...}}`

#### `hubspot_get_deal`
Get a deal by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `deal_id` | str | Yes | Deal ID |
| `properties` | list[str] | No | Properties to return (default: dealname, amount, dealstage, pipeline, closedate) |

**Returns:** Deal object with requested properties.
**Endpoint:** `GET /crm/v3/objects/deals/{dealId}?properties=...`

#### `hubspot_update_deal`
Update an existing deal's properties.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `deal_id` | str | Yes | Deal ID |
| `dealname` | str | No | Updated deal name |
| `amount` | str | No | Updated amount |
| `dealstage` | str | No | Updated deal stage ID |
| `pipeline` | str | No | Updated pipeline ID |
| `closedate` | str | No | Updated close date (ISO 8601) |
| `hubspot_owner_id` | str | No | Updated owner |
| `description` | str | No | Updated description |
| `extra_properties` | dict | No | Additional properties |

At least one property must be provided.
**Returns:** Updated deal object.
**Endpoint:** `PATCH /crm/v3/objects/deals/{dealId}`

#### `hubspot_delete_deal`
Archive (soft-delete) a deal.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `deal_id` | str | Yes | Deal ID to archive |

**Returns:** Confirmation of archival.
**Endpoint:** `DELETE /crm/v3/objects/deals/{dealId}`

#### `hubspot_list_deals`
List deals with pagination.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `after` | str | No | Pagination cursor |
| `properties` | list[str] | No | Properties to include (default: dealname, amount, dealstage, pipeline, closedate) |

**Returns:** List of deals with paging cursor.
**Endpoint:** `GET /crm/v3/objects/deals?limit={limit}&after={after}&properties=...`

#### `hubspot_search_deals`
Search deals using filters or query string.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | No | Full-text search query |
| `filter_groups` | list[dict] | No | Property-based filter groups |
| `sorts` | list[dict] | No | Sort criteria |
| `properties` | list[str] | No | Properties to return |
| `limit` | int | No | Number of results (default 10, max 100) |
| `after` | str | No | Pagination cursor |

**Returns:** Matching deals with total count and paging.
**Endpoint:** `POST /crm/v3/objects/deals/search`

---

### Tier 4: Tickets (6 tools)

#### `hubspot_create_ticket`
Create a new support ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | str | Yes | Ticket subject line |
| `content` | str | No | Ticket description/body |
| `hs_pipeline` | str | No | Pipeline ID (default support pipeline if omitted) |
| `hs_pipeline_stage` | str | No | Pipeline stage ID |
| `hs_ticket_priority` | str | No | Priority: `LOW`, `MEDIUM`, `HIGH` |
| `hubspot_owner_id` | str | No | Owner ID |
| `extra_properties` | dict | No | Additional properties |

**Returns:** Created ticket with ID and properties.
**Endpoint:** `POST /crm/v3/objects/tickets`
**Body:** `{"properties": {"subject": "...", "content": "...", ...}}`

#### `hubspot_get_ticket`
Get a ticket by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | str | Yes | Ticket ID |
| `properties` | list[str] | No | Properties to return (default: subject, content, hs_pipeline, hs_pipeline_stage, hs_ticket_priority) |

**Returns:** Ticket object with requested properties.
**Endpoint:** `GET /crm/v3/objects/tickets/{ticketId}?properties=...`

#### `hubspot_update_ticket`
Update an existing ticket's properties.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | str | Yes | Ticket ID |
| `subject` | str | No | Updated subject |
| `content` | str | No | Updated description |
| `hs_pipeline` | str | No | Updated pipeline ID |
| `hs_pipeline_stage` | str | No | Updated stage ID |
| `hs_ticket_priority` | str | No | Updated priority |
| `hubspot_owner_id` | str | No | Updated owner |
| `extra_properties` | dict | No | Additional properties |

At least one property must be provided.
**Returns:** Updated ticket object.
**Endpoint:** `PATCH /crm/v3/objects/tickets/{ticketId}`

#### `hubspot_delete_ticket`
Archive (soft-delete) a ticket.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ticket_id` | str | Yes | Ticket ID to archive |

**Returns:** Confirmation of archival.
**Endpoint:** `DELETE /crm/v3/objects/tickets/{ticketId}`

#### `hubspot_list_tickets`
List tickets with pagination.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `after` | str | No | Pagination cursor |
| `properties` | list[str] | No | Properties to include (default: subject, content, hs_pipeline_stage, hs_ticket_priority) |

**Returns:** List of tickets with paging cursor.
**Endpoint:** `GET /crm/v3/objects/tickets?limit={limit}&after={after}&properties=...`

#### `hubspot_search_tickets`
Search tickets using filters or query string.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | No | Full-text search query |
| `filter_groups` | list[dict] | No | Property-based filter groups |
| `sorts` | list[dict] | No | Sort criteria |
| `properties` | list[str] | No | Properties to return |
| `limit` | int | No | Number of results (default 10, max 100) |
| `after` | str | No | Pagination cursor |

**Returns:** Matching tickets with total count and paging.
**Endpoint:** `POST /crm/v3/objects/tickets/search`

---

### Tier 5: Notes/Engagements (6 tools)

#### `hubspot_create_note`
Create a note and optionally associate it with a CRM record.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `body` | str | Yes | Note body text (supports HTML) |
| `timestamp` | str | No | Note timestamp (ISO 8601; defaults to now) |
| `hubspot_owner_id` | str | No | Owner ID |
| `associations` | list[dict] | No | Objects to associate with, e.g., `[{"to": {"id": "123"}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]}]` |

**Returns:** Created note with ID.
**Endpoint:** `POST /crm/v3/objects/notes`
**Body:**
```json
{
  "properties": {
    "hs_note_body": "...",
    "hs_timestamp": "..."
  },
  "associations": [...]
}
```

**Convenience parameters (alternative to raw `associations`):**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `contact_id` | str | No | Associate note with this contact (uses association type 202) |
| `deal_id` | str | No | Associate note with this deal (uses association type 214) |
| `company_id` | str | No | Associate note with this company (uses association type 190) |
| `ticket_id` | str | No | Associate note with this ticket (uses association type 218) |

If convenience params are provided, the tool builds the associations array automatically.

#### `hubspot_get_note`
Get a note by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `note_id` | str | Yes | Note ID |
| `properties` | list[str] | No | Properties to return (default: hs_note_body, hs_timestamp, hubspot_owner_id) |

**Returns:** Note object with properties.
**Endpoint:** `GET /crm/v3/objects/notes/{noteId}?properties=...`

#### `hubspot_list_notes`
List notes with pagination.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `after` | str | No | Pagination cursor |
| `properties` | list[str] | No | Properties to include (default: hs_note_body, hs_timestamp) |

**Returns:** List of notes with paging cursor.
**Endpoint:** `GET /crm/v3/objects/notes?limit={limit}&after={after}&properties=...`

**Note:** To list notes for a specific contact/deal, use `hubspot_get_associations` to find associated note IDs, then retrieve them individually or filter via search.

#### `hubspot_update_note`
Update an existing note's properties.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `note_id` | str | Yes | Note ID |
| `body` | str | No | Updated note body text (supports HTML) |
| `extra_properties` | dict | No | Additional properties to update |

At least one property must be provided.
**Returns:** Updated note object.
**Endpoint:** `PATCH /crm/v3/objects/notes/{noteId}`
**Body:** `{"properties": {...}}`

#### `hubspot_delete_note`
Archive (soft-delete) a note.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `note_id` | str | Yes | Note ID to archive |

**Returns:** Confirmation of archival.
**Endpoint:** `DELETE /crm/v3/objects/notes/{noteId}`

#### `hubspot_search_notes`
Search notes using filters or query string.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | No | Full-text search query |
| `filter_groups` | list[dict] | No | Property-based filter groups |
| `sorts` | list[dict] | No | Sort criteria |
| `properties` | list[str] | No | Properties to return |
| `limit` | int | No | Number of results (default 10, max 100) |
| `after` | str | No | Pagination cursor |

Either `query` or `filter_groups` should be provided.
**Returns:** Matching notes with total count and paging.
**Endpoint:** `POST /crm/v3/objects/notes/search`

---

### Tier 6: Associations (4 tools)

#### `hubspot_create_association`
Create an association between two CRM records.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `from_object_type` | str | Yes | Source object type (`contacts`, `companies`, `deals`, `tickets`, `notes`) |
| `from_object_id` | str | Yes | Source object ID |
| `to_object_type` | str | Yes | Target object type |
| `to_object_id` | str | Yes | Target object ID |
| `association_type_id` | int | No | Association type ID (if omitted, uses default/primary) |
| `association_category` | str | No | `HUBSPOT_DEFINED` (default) or `USER_DEFINED` |

**Returns:** Confirmation with association details.
**Endpoint:** `PUT /crm/v4/objects/{fromObjectType}/{fromObjectId}/associations/default/{toObjectType}/{toObjectId}` (when using default)
**Endpoint (labeled):** `PUT /crm/v4/objects/{fromObjectType}/{fromObjectId}/associations/{toObjectType}/{toObjectId}` with body `[{"associationCategory": "...", "associationTypeId": N}]`

**Common default association type IDs (HUBSPOT_DEFINED):**

> **Note:** These are well-known defaults but may vary by portal. Use `hubspot_list_association_types` to verify IDs for a specific account. For contact-to-company, type 1 = "Primary" label and 279 = unlabeled default.

| Association | Type ID | Notes |
|-------------|---------|-------|
| Contact to Company (primary) | 1 | Sets company as primary |
| Contact to Company (unlabeled) | 279 | Default/non-primary |
| Company to Contact | 280 | Reverse direction |
| Deal to Contact | 3 | |
| Contact to Deal | 4 | Reverse direction |
| Deal to Company | 341 | |
| Company to Deal | 342 | Reverse direction |
| Note to Contact | 202 | |
| Note to Company | 190 | |
| Note to Deal | 214 | |
| Note to Ticket | 218 | |

#### `hubspot_remove_association`
Remove an association between two CRM records.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `from_object_type` | str | Yes | Source object type |
| `from_object_id` | str | Yes | Source object ID |
| `to_object_type` | str | Yes | Target object type |
| `to_object_id` | str | Yes | Target object ID |

**Returns:** Confirmation of removal.
**Endpoint:** `DELETE /crm/v4/objects/{fromObjectType}/{fromObjectId}/associations/{toObjectType}/{toObjectId}`

#### `hubspot_get_associations`
List all associations of a specific type for a record.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `object_type` | str | Yes | Source object type (e.g., `contacts`) |
| `object_id` | str | Yes | Source object ID |
| `to_object_type` | str | Yes | Target object type to retrieve (e.g., `companies`) |
| `limit` | int | No | Number of results (default 100, max 500) |
| `after` | str | No | Pagination cursor |

**Returns:** List of associated object IDs with association types.
**Endpoint:** `GET /crm/v4/objects/{objectType}/{objectId}/associations/{toObjectType}`

#### `hubspot_list_association_types`
List available association types between two object types.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `from_object_type` | str | Yes | Source object type (e.g., `deals`) |
| `to_object_type` | str | Yes | Target object type (e.g., `contacts`) |

**Returns:** List of association type IDs, labels, and categories.
**Endpoint:** `GET /crm/v4/associations/{fromObjectType}/{toObjectType}/labels`

---

### Tier 7: Pipelines (2 tools)

#### `hubspot_list_pipelines`
List all pipelines for an object type.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `object_type` | str | No | Object type: `deals` (default) or `tickets` |

**Returns:** List of pipelines with IDs, labels, display order, stages.
**Endpoint:** `GET /crm/v3/pipelines/{objectType}`

#### `hubspot_list_pipeline_stages`
List stages for a specific pipeline.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `object_type` | str | No | Object type: `deals` (default) or `tickets` |
| `pipeline_id` | str | Yes | Pipeline ID |

**Returns:** List of stages with IDs, labels, display order, metadata (isClosed, probability).
**Endpoint:** `GET /crm/v3/pipelines/{objectType}/{pipelineId}/stages`

---

### Tier 8: Owners (2 tools)

#### `hubspot_list_owners`
List HubSpot account owners with optional email filter.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 100, max 500) |
| `after` | str | No | Pagination cursor |
| `email` | str | No | Filter owners by email address |

**Returns:** List of owners with IDs, email, first/last name, and paging cursor.
**Endpoint:** `GET /crm/v3/owners?limit={limit}&after={after}&email={email}`

#### `hubspot_get_owner`
Get an owner by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `owner_id` | str | Yes | Owner ID |

**Returns:** Owner object with ID, email, first name, last name, user ID.
**Endpoint:** `GET /crm/v3/owners/{ownerId}`

---

### Tier 9: Properties (3 tools)

#### `hubspot_list_properties`
List all properties defined for a CRM object type.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `object_type` | str | Yes | Object type: `contacts`, `companies`, `deals`, `tickets`, `notes` |

**Returns:** List of property definitions with name, label, type, field type, group, and options.
**Endpoint:** `GET /crm/v3/properties/{objectType}`

#### `hubspot_get_property`
Get a single property definition by name for a CRM object type.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `object_type` | str | Yes | Object type: `contacts`, `companies`, `deals`, `tickets`, `notes` |
| `property_name` | str | Yes | Property internal name (e.g., `email`, `dealstage`) |

**Returns:** Property definition with name, label, type, field type, group, description, and options.
**Endpoint:** `GET /crm/v3/properties/{objectType}/{propertyName}`

#### `hubspot_create_property`
Create a custom property for a CRM object type.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `object_type` | str | Yes | Object type: `contacts`, `companies`, `deals`, `tickets`, `notes` |
| `name` | str | Yes | Property internal name (lowercase, no spaces, use underscores) |
| `label` | str | Yes | Property display label |
| `type` | str | Yes | Data type: `string`, `number`, `date`, `datetime`, `enumeration`, `bool` |
| `field_type` | str | Yes | UI field type: `text`, `textarea`, `number`, `select`, `radio`, `checkbox`, `date`, `booleancheckbox` |
| `group_name` | str | No | Property group (default `contactinformation`) |
| `description` | str | No | Property description |
| `options` | list[dict] | No | Options for `enumeration` type, e.g., `[{"label": "Option A", "value": "option_a"}]` |

**Returns:** Created property definition.
**Endpoint:** `POST /crm/v3/properties/{objectType}`
**Body:**
```json
{
  "name": "...",
  "label": "...",
  "type": "...",
  "fieldType": "...",
  "groupName": "...",
  "description": "...",
  "options": [...]
}
```

---

### Tier 10: Batch Operations (2 tools)

#### `hubspot_batch_create`
Create multiple CRM objects in a single batch request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `object_type` | str | Yes | Object type: `contacts`, `companies`, `deals`, `tickets`, `notes` |
| `inputs` | list[dict] | Yes | List of objects to create, e.g., `[{"properties": {"email": "a@b.com"}}, {"properties": {"email": "c@d.com"}}]` |

**Returns:** List of created objects with IDs and properties, plus any errors.
**Endpoint:** `POST /crm/v3/objects/{objectType}/batch/create`
**Body:** `{"inputs": [{"properties": {...}}, ...]}`

#### `hubspot_batch_update`
Update multiple CRM objects in a single batch request.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `object_type` | str | Yes | Object type: `contacts`, `companies`, `deals`, `tickets`, `notes` |
| `inputs` | list[dict] | Yes | List of objects to update, e.g., `[{"id": "123", "properties": {"firstname": "Updated"}}, ...]` |

**Returns:** List of updated objects with IDs and properties, plus any errors.
**Endpoint:** `POST /crm/v3/objects/{objectType}/batch/update`
**Body:** `{"inputs": [{"id": "...", "properties": {...}}, ...]}`

---

## Architecture Decisions

### A1: Direct HTTP with httpx (no SDK)
Consistent with ClickUp pattern. Use `httpx` (already a project dependency) for async HTTP calls directly. No dependency on `hubspot-api-client` package.

### A2: Shared httpx Client
Create a shared `httpx.AsyncClient` with base URL and auth headers, reused across all tool calls.

```python
import httpx

_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    if not HUBSPOT_API_TOKEN:
        raise ToolError(
            "HUBSPOT_API_TOKEN is not configured. "
            "Set it in your environment or .env file."
        )
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url="https://api.hubapi.com",
            headers={"Authorization": f"Bearer {HUBSPOT_API_TOKEN}"},
            timeout=30.0,
        )
    return _client
```

**Lifecycle:** Same as ClickUp -- process-scoped, no explicit `aclose()` needed for STDIO transport.

### A3: Tool Naming Convention
All HubSpot tools prefixed with `hubspot_` to distinguish from other integrations.

### A4: Error Handling
Same pattern as ClickUp: catch `httpx` exceptions, convert to `ToolError` with human-readable messages. 429 responses include `Retry-After` info. No automatic retry.

### A5: Response Format
Consistent JSON convention: `{"status": "success", ...}` or `{"status": "error", ...}`.

### A6: Pagination Pattern
HubSpot uses cursor-based pagination with `after` parameter (not page numbers). Tools accept `limit` and `after` params. Responses include `paging.next.after` when more results are available. No auto-pagination -- callers request specific pages.

### A7: Properties Helper
Create a helper function `_build_properties()` that filters out `None` values and merges `extra_properties` dict into named properties. This avoids sending null properties to the API:

```python
def _build_properties(**kwargs) -> dict:
    extra = kwargs.pop("extra_properties", None) or {}
    props = {k: v for k, v in kwargs.items() if v is not None}
    props.update(extra)
    if not props:
        raise ToolError("At least one property must be provided.")
    return props
```

### A8: Search Helper
Create a shared `_search()` helper since all CRM object searches follow the same pattern (`POST /crm/v3/objects/{objectType}/search` with filterGroups/query body). Reduces code duplication across all 5 search tools (contacts, companies, deals, tickets, notes).

### A9: Association Convenience
The `hubspot_create_note` tool provides convenience params (`contact_id`, `deal_id`, etc.) that auto-build the associations array, while `hubspot_create_association` provides full control for arbitrary association creation.

### A10: Missing API Key Strategy
Same as ClickUp: register tools regardless, fail at invocation with clear `ToolError`.

---

## Configuration Requirements

### Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `HUBSPOT_API_TOKEN` | Private App access token (format: `pat-xx-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`) | Yes (at invocation) | `None` |

### Config Pattern
```python
HUBSPOT_API_TOKEN: str | None = os.getenv("HUBSPOT_API_TOKEN")
```

### No Secondary Config Needed
Unlike ClickUp (which needs `CLICKUP_TEAM_ID`), HubSpot does not require a workspace/portal ID -- the private app token is scoped to a single portal automatically.

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/config.py` | Modify | Add `HUBSPOT_API_TOKEN` |
| `.env.example` | Modify | Add `HUBSPOT_API_TOKEN` variable |
| `src/mcp_toolbox/tools/hubspot_tool.py` | **New** | All HubSpot CRM tools (~43 tools) |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register hubspot_tool |
| `tests/test_hubspot_tool.py` | **New** | Tests for all HubSpot tools |
| `CLAUDE.md` | Modify | Document HubSpot CRM integration |

---

## Testing Strategy

### Approach
Use `pytest` with `respx` (already used for ClickUp tests) for mocking HTTP calls. All HubSpot endpoints follow predictable REST patterns, making mocking straightforward.

```python
import respx
import httpx

@respx.mock
async def test_create_contact():
    respx.post("https://api.hubapi.com/crm/v3/objects/contacts").mock(
        return_value=httpx.Response(200, json={
            "id": "123",
            "properties": {"email": "test@example.com", "firstname": "Test"},
            "createdAt": "2026-04-01T00:00:00Z",
            "updatedAt": "2026-04-01T00:00:00Z"
        })
    )
    result = await server.call_tool("hubspot_create_contact", {"email": "test@example.com"})
    assert "success" in result
```

### Test Coverage
1. Happy path for every tool (43 tests minimum)
2. Missing API token -> ToolError
3. API errors (401 Unauthorized, 404 Not Found, 429 Rate Limit, 409 Conflict)
4. Property building (None filtering, extra_properties merge)
5. Pagination cursor passing
6. Search with query vs. filter_groups
7. Association convenience params in `hubspot_create_note`
8. Delete/archive confirmation
9. `hubspot_get_contact` with email lookup vs. ID lookup

---

## Dependencies

| Package | Purpose | Already in project? |
|---------|---------|-------------------|
| `httpx` | Async HTTP client | Yes |
| `respx` | httpx mock library (dev) | Yes (added for ClickUp) |

No new dependencies required.

---

## Success Criteria

1. `uv sync` installs without errors (no new runtime deps needed)
2. All 43 HubSpot tools register and are discoverable via MCP Inspector
3. Tools return meaningful errors when API token is missing
4. All tools return consistent JSON responses (`{"status": "success", ...}`)
5. New tests pass and full regression suite remains green
6. Config handles missing API token gracefully (tools register, fail at invocation)
7. Total tool count reaches **267** (current 224 + 43 new HubSpot tools)

---

## Scope Decision

**All 10 tiers (43 tools)** -- full CRM integration covering contacts, companies, deals, tickets, notes, associations, pipelines, owners, properties, and batch operations.

---

## Tool Summary (43 tools total)

### Tier 1 -- Contacts (6 tools)
1. `hubspot_create_contact` -- Create a contact with email, name, phone, lifecycle stage
2. `hubspot_get_contact` -- Get contact by ID or email with selected properties
3. `hubspot_update_contact` -- Update contact properties
4. `hubspot_delete_contact` -- Archive a contact
5. `hubspot_list_contacts` -- List contacts with cursor pagination
6. `hubspot_search_contacts` -- Search contacts with filters or full-text query

### Tier 2 -- Companies (6 tools)
7. `hubspot_create_company` -- Create a company with name, domain, industry
8. `hubspot_get_company` -- Get company by ID with selected properties
9. `hubspot_update_company` -- Update company properties
10. `hubspot_delete_company` -- Archive a company
11. `hubspot_list_companies` -- List companies with cursor pagination
12. `hubspot_search_companies` -- Search companies with filters or full-text query

### Tier 3 -- Deals (6 tools)
13. `hubspot_create_deal` -- Create a deal with name, amount, stage, pipeline
14. `hubspot_get_deal` -- Get deal by ID with selected properties
15. `hubspot_update_deal` -- Update deal properties (stage, amount, etc.)
16. `hubspot_delete_deal` -- Archive a deal
17. `hubspot_list_deals` -- List deals with cursor pagination
18. `hubspot_search_deals` -- Search deals with filters or full-text query

### Tier 4 -- Tickets (6 tools)
19. `hubspot_create_ticket` -- Create a ticket with subject, content, priority, pipeline
20. `hubspot_get_ticket` -- Get ticket by ID with selected properties
21. `hubspot_update_ticket` -- Update ticket properties
22. `hubspot_delete_ticket` -- Archive a ticket
23. `hubspot_list_tickets` -- List tickets with cursor pagination
24. `hubspot_search_tickets` -- Search tickets with filters or full-text query

### Tier 5 -- Notes/Engagements (6 tools)
25. `hubspot_create_note` -- Create a note with optional auto-association to contact/deal/company/ticket
26. `hubspot_get_note` -- Get note by ID
27. `hubspot_list_notes` -- List notes with cursor pagination
28. `hubspot_update_note` -- Update a note's body or properties
29. `hubspot_delete_note` -- Archive a note
30. `hubspot_search_notes` -- Search notes with filters or full-text query

### Tier 6 -- Associations (4 tools)
31. `hubspot_create_association` -- Associate two CRM records (default or labeled)
32. `hubspot_remove_association` -- Remove association between two records
33. `hubspot_get_associations` -- List associations of a record to a target object type
34. `hubspot_list_association_types` -- List available association type IDs between two object types

### Tier 7 -- Pipelines (2 tools)
35. `hubspot_list_pipelines` -- List deal or ticket pipelines with stages
36. `hubspot_list_pipeline_stages` -- List stages for a specific pipeline

### Tier 8 -- Owners (2 tools)
37. `hubspot_list_owners` -- List account owners with optional email filter
38. `hubspot_get_owner` -- Get owner by ID

### Tier 9 -- Properties (3 tools)
39. `hubspot_list_properties` -- List all property definitions for an object type
40. `hubspot_get_property` -- Get a single property definition by name
41. `hubspot_create_property` -- Create a custom property for an object type

### Tier 10 -- Batch Operations (2 tools)
42. `hubspot_batch_create` -- Create multiple CRM objects in a single request
43. `hubspot_batch_update` -- Update multiple CRM objects in a single request
