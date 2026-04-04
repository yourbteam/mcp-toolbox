# Task 22: Salesforce Integration - Analysis & Requirements

## Objective
Add Salesforce as a tool integration in mcp-toolbox, exposing CRM and platform capabilities (SObject CRUD for all major objects, SOQL queries, SOSL search, describe/metadata, bulk operations, reports, composite requests) as MCP tools for LLM clients.

---

## API Technical Details

### Salesforce REST API
- **Base URL:** `https://{instance}.salesforce.com/services/data/v{version}/`
- **Auth:** OAuth2 with refresh token grant (Bearer token per request)
- **Token Endpoint:** `https://login.salesforce.com/services/oauth2/token`
- **Request Format:** JSON (`Content-Type: application/json`) for most endpoints; some accept CSV for bulk
- **Response Format:** JSON
- **API Version:** Embedded in URL path (e.g., `v59.0`); default `v59.0`, configurable via `SF_API_VERSION`

### Authentication -- OAuth2 Refresh Token Flow

Follows the same pattern as QuickBooks (`quickbooks_tool.py`): pre-obtained refresh token exchanged for short-lived access tokens.

#### Token Exchange Request
```
POST https://login.salesforce.com/services/oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token
&client_id={SF_CLIENT_ID}
&client_secret={SF_CLIENT_SECRET}
&refresh_token={SF_REFRESH_TOKEN}
```

#### Token Response
```json
{
  "access_token": "00D...",
  "instance_url": "https://yourorg.my.salesforce.com",
  "id": "https://login.salesforce.com/id/00Dxx.../005xx...",
  "token_type": "Bearer",
  "issued_at": "1685000000000",
  "signature": "..."
}
```

**Key details:**
- Access tokens expire after ~2 hours (session timeout setting in Salesforce org)
- Refresh tokens do NOT rotate on use (unlike QuickBooks) -- the same refresh token stays valid until revoked
- `instance_url` in the response tells us the correct base URL for API calls -- this auto-detects the org's instance (na1, eu5, etc.) so `SF_INSTANCE_URL` is optional
- For sandbox orgs, use `https://test.salesforce.com/services/oauth2/token` instead

#### Implementation Pattern (mirrors quickbooks_tool.py)
```python
_access_token: str | None = None
_token_expires_at: float = 0.0
_instance_url: str | None = None
_token_lock: asyncio.Lock | None = None

async def _get_token() -> tuple[str, str]:
    """Returns (access_token, instance_url)."""
    # Lock, check expiry (with 60s buffer), refresh if needed
    # POST to token endpoint with refresh_token grant
    # Cache access_token + instance_url from response
    # issued_at is milliseconds; expires_in not returned -- use 7200s default
```

### Configuration Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SF_CLIENT_ID` | Yes | OAuth2 Connected App consumer key |
| `SF_CLIENT_SECRET` | Yes | OAuth2 Connected App consumer secret |
| `SF_REFRESH_TOKEN` | Yes | Pre-obtained OAuth2 refresh token |
| `SF_INSTANCE_URL` | No | Override instance URL (e.g., `https://myorg.my.salesforce.com`). Auto-detected from token response if omitted |
| `SF_API_VERSION` | No | API version string (default `v59.0`). Just the version, no leading slash |

### Rate Limits

| Limit Type | Value | Notes |
|------------|-------|-------|
| **Total API requests/24h** | Varies by edition | Developer: 15,000; Enterprise: 100,000 + 1,000/user license; Unlimited: 100,000 + 5,000/user license |
| **Concurrent API requests** | 25 | Per org, long-running requests |
| **Concurrent Bulk API batches** | 100 | Per org |
| **Bulk API batches/24h** | 15,000 | Per org |
| **SOQL query rows** | 50,000 | Per single query execution (use queryMore for pagination) |
| **SOSL search results** | 2,000 | Per search execution |
| **Composite subrequests** | 25 | Per composite request |
| **Composite graph subrequests** | 500 | Per composite graph request |

- HTTP 403 with `REQUEST_LIMIT_EXCEEDED` error code when daily limit hit
- `Sforce-Limit-Info` response header: `api-usage=25/100000` (current/max)
- Bulk API has separate limits from REST API

### Key Quirks

1. **API version in every URL** -- All REST endpoints include `/services/data/vXX.X/` in the path. Version must match org's enabled API versions.

2. **SObject API paths** -- CRUD operations use `/sobjects/{SObjectName}/` pattern:
   - Create: `POST /sobjects/Account/`
   - Get: `GET /sobjects/Account/{id}`
   - Update: `PATCH /sobjects/Account/{id}` (not POST or PUT)
   - Delete: `DELETE /sobjects/Account/{id}`
   - Upsert by external ID: `PATCH /sobjects/Account/External_Field__c/{value}`

3. **SOQL query language** -- Salesforce Object Query Language, SQL-like but not SQL:
   - `SELECT Id, Name, Email FROM Contact WHERE AccountId = '001xx...'`
   - Supports relationships: `SELECT Name, Account.Name FROM Contact`
   - Child subqueries: `SELECT Name, (SELECT LastName FROM Contacts) FROM Account`
   - No `JOIN` -- use relationship queries instead
   - Date literals: `TODAY`, `LAST_N_DAYS:30`, `THIS_FISCAL_QUARTER`
   - SOQL must be URL-encoded when passed as query parameter

4. **SOSL search syntax** -- Salesforce Object Search Language for full-text search:
   - `FIND {search term} IN ALL FIELDS RETURNING Account(Id, Name), Contact(Id, Name, Email)`
   - Supports wildcards: `FIND {john*}`
   - Must be URL-encoded

5. **Field types** -- Salesforce has specific field types:
   - IDs are 15 or 18 character strings (18-char is case-insensitive)
   - Dates: `YYYY-MM-DD`, DateTimes: `YYYY-MM-DDThh:mm:ss.000+0000`
   - Currency fields are decimals, not integers (unlike Stripe)
   - Picklist values must match defined values

6. **Error response format:**
   ```json
   [{"message": "...", "errorCode": "INVALID_FIELD", "fields": ["BadField__c"]}]
   ```
   Errors return as a JSON array (not a single object).

7. **No `expires_in` in token response** -- Unlike most OAuth2 implementations, Salesforce does not return `expires_in`. Access tokens last based on org's session timeout (default 2 hours). Use 7200s as default expiry.

8. **Query pagination** -- Large result sets return a `nextRecordsUrl` field:
   ```json
   {"totalSize": 5000, "done": false, "nextRecordsUrl": "/services/data/v59.0/query/01gxx...-2000", "records": [...]}
   ```
   Follow `nextRecordsUrl` to get next batch.

9. **Composite requests** -- Bundle up to 25 subrequests in a single HTTP call. Subrequests can reference each other's results using `@{refId.field}` syntax.

10. **Describe calls are heavy** -- `/sobjects/{SObject}/describe/` returns full metadata (all fields, picklists, record types). Cache results where possible.

11. **Record Types** -- Some objects have multiple record types affecting which fields and picklist values are available.

12. **Soft deletes** -- Deleted records go to Recycle Bin for 15 days. Query deleted records with `queryAll` endpoint or `isDeleted = true`.

---

## Salesforce Object Model

```
Account -----> Contacts (1:many)
   |               |
   |               v
   +---------> Opportunities (1:many) -----> OpportunityLineItems
   |               |
   v               v
 Cases          Tasks / Events (ActivityHistory)
   |
   v
CaseComments
```

### Core SObjects
| SObject | Description | Key Fields |
|---------|-------------|------------|
| Account | Company/organization | Id, Name, Industry, Type, Phone, Website, BillingAddress, OwnerId |
| Contact | Individual person | Id, FirstName, LastName, Email, Phone, AccountId, Title, OwnerId |
| Opportunity | Sales deal | Id, Name, StageName, Amount, CloseDate, AccountId, Probability, OwnerId |
| Lead | Unqualified prospect | Id, FirstName, LastName, Email, Company, Status, OwnerId, IsConverted |
| Case | Support ticket | Id, Subject, Description, Status, Priority, AccountId, ContactId, OwnerId |
| Task | To-do / call log | Id, Subject, Status, Priority, WhoId, WhatId, ActivityDate, OwnerId |
| Event | Calendar event | Id, Subject, StartDateTime, EndDateTime, WhoId, WhatId, Location, OwnerId |

---

## Tool Specifications

### Tier 1: Account SObject (6 tools)

#### `sf_create_account`
Create a new Account record.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Account name |
| `industry` | str | No | Industry (picklist value) |
| `type` | str | No | Account type (e.g., `Customer`, `Partner`, `Prospect`) |
| `phone` | str | No | Phone number |
| `website` | str | No | Website URL |
| `description` | str | No | Account description |
| `billing_street` | str | No | Billing street address |
| `billing_city` | str | No | Billing city |
| `billing_state` | str | No | Billing state/province |
| `billing_postal_code` | str | No | Billing postal/ZIP code |
| `billing_country` | str | No | Billing country |
| `owner_id` | str | No | Owner user ID |
| `parent_id` | str | No | Parent account ID (for hierarchies) |
| `annual_revenue` | float | No | Annual revenue |
| `number_of_employees` | int | No | Number of employees |
| `custom_fields` | dict | No | Any additional standard or custom fields as key-value pairs |

**Returns:** `{"id": "001xx...", "success": true, "errors": []}`
**Endpoint:** `POST /services/data/v59.0/sobjects/Account/`
**Body:** JSON `{"Name": "Acme Corp", "Industry": "Technology", ...}`

#### `sf_get_account`
Retrieve an Account by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `account_id` | str | Yes | Account ID (e.g., `001xx...`) |
| `fields` | list[str] | No | Specific fields to retrieve (default: all accessible fields) |

**Returns:** Account record with requested fields.
**Endpoint:** `GET /services/data/v59.0/sobjects/Account/{account_id}` or `GET /services/data/v59.0/sobjects/Account/{account_id}?fields=Id,Name,Industry`

#### `sf_update_account`
Update an existing Account.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `account_id` | str | Yes | Account ID |
| `name` | str | No | Updated name |
| `industry` | str | No | Updated industry |
| `type` | str | No | Updated type |
| `phone` | str | No | Updated phone |
| `website` | str | No | Updated website |
| `description` | str | No | Updated description |
| `billing_street` | str | No | Updated billing street |
| `billing_city` | str | No | Updated billing city |
| `billing_state` | str | No | Updated billing state |
| `billing_postal_code` | str | No | Updated billing postal code |
| `billing_country` | str | No | Updated billing country |
| `owner_id` | str | No | Updated owner |
| `parent_id` | str | No | Updated parent account |
| `custom_fields` | dict | No | Additional fields to update |

At least one field must be provided.
**Returns:** HTTP 204 No Content on success.
**Endpoint:** `PATCH /services/data/v59.0/sobjects/Account/{account_id}`

#### `sf_delete_account`
Delete an Account (moves to Recycle Bin).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `account_id` | str | Yes | Account ID to delete |

**Returns:** HTTP 204 No Content on success.
**Endpoint:** `DELETE /services/data/v59.0/sobjects/Account/{account_id}`

#### `sf_list_accounts`
List Accounts via SOQL query with common filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Max records to return (default 20, max 2000) |
| `offset` | int | No | Number of records to skip (max 2000) |
| `order_by` | str | No | Field to order by (default `Name`) |
| `order_dir` | str | No | `ASC` or `DESC` (default `ASC`) |
| `name_like` | str | No | Filter: Name contains this string (LIKE '%value%') |
| `industry` | str | No | Filter: exact Industry match |
| `type` | str | No | Filter: exact Type match |
| `owner_id` | str | No | Filter: exact Owner ID |
| `fields` | list[str] | No | Fields to return (default: Id, Name, Industry, Type, Phone, Website) |

**Returns:** `{"totalSize": N, "done": true/false, "records": [...]}`
**Endpoint:** `GET /services/data/v59.0/query/?q=SELECT+Id,Name,...+FROM+Account+WHERE+...+LIMIT+20`
**Note:** Builds SOQL query internally from filter params.

#### `sf_upsert_account`
Insert or update an Account using an external ID field.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `external_id_field` | str | Yes | API name of the external ID field (e.g., `External_Id__c`) |
| `external_id_value` | str | Yes | Value of the external ID |
| `name` | str | No | Account name (required for insert, optional for update) |
| `industry` | str | No | Industry |
| `type` | str | No | Account type |
| `phone` | str | No | Phone |
| `website` | str | No | Website |
| `custom_fields` | dict | No | Additional fields |

**Returns:** HTTP 201 (created) or 204 (updated). Created returns `{"id": "001xx...", "success": true}`.
**Endpoint:** `PATCH /services/data/v59.0/sobjects/Account/{external_id_field}/{external_id_value}`

---

### Tier 2: Contact SObject (6 tools)

#### `sf_create_contact`
Create a new Contact record.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `last_name` | str | Yes | Last name (required by Salesforce) |
| `first_name` | str | No | First name |
| `email` | str | No | Email address |
| `phone` | str | No | Phone number |
| `mobile_phone` | str | No | Mobile phone |
| `title` | str | No | Job title |
| `department` | str | No | Department |
| `account_id` | str | No | Associated Account ID |
| `mailing_street` | str | No | Mailing street |
| `mailing_city` | str | No | Mailing city |
| `mailing_state` | str | No | Mailing state |
| `mailing_postal_code` | str | No | Mailing postal code |
| `mailing_country` | str | No | Mailing country |
| `owner_id` | str | No | Owner user ID |
| `description` | str | No | Description |
| `custom_fields` | dict | No | Additional fields |

**Returns:** `{"id": "003xx...", "success": true, "errors": []}`
**Endpoint:** `POST /services/data/v59.0/sobjects/Contact/`

#### `sf_get_contact`
Retrieve a Contact by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `contact_id` | str | Yes | Contact ID |
| `fields` | list[str] | No | Specific fields to retrieve |

**Returns:** Contact record.
**Endpoint:** `GET /services/data/v59.0/sobjects/Contact/{contact_id}`

#### `sf_update_contact`
Update an existing Contact.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `contact_id` | str | Yes | Contact ID |
| `first_name` | str | No | Updated first name |
| `last_name` | str | No | Updated last name |
| `email` | str | No | Updated email |
| `phone` | str | No | Updated phone |
| `mobile_phone` | str | No | Updated mobile |
| `title` | str | No | Updated title |
| `department` | str | No | Updated department |
| `account_id` | str | No | Updated account association |
| `owner_id` | str | No | Updated owner |
| `description` | str | No | Updated description |
| `custom_fields` | dict | No | Additional fields |

**Returns:** HTTP 204 No Content on success.
**Endpoint:** `PATCH /services/data/v59.0/sobjects/Contact/{contact_id}`

#### `sf_delete_contact`
Delete a Contact.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `contact_id` | str | Yes | Contact ID to delete |

**Returns:** HTTP 204 No Content.
**Endpoint:** `DELETE /services/data/v59.0/sobjects/Contact/{contact_id}`

#### `sf_list_contacts`
List Contacts with common filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Max records (default 20, max 2000) |
| `offset` | int | No | Records to skip |
| `order_by` | str | No | Sort field (default `LastName`) |
| `order_dir` | str | No | `ASC` or `DESC` |
| `account_id` | str | No | Filter by Account ID |
| `email` | str | No | Filter by exact email |
| `name_like` | str | No | Filter: Name contains string |
| `owner_id` | str | No | Filter by owner |
| `fields` | list[str] | No | Fields to return (default: Id, FirstName, LastName, Email, Phone, AccountId, Title) |

**Returns:** SOQL query result with records array.
**Endpoint:** `GET /services/data/v59.0/query/?q=SELECT+...+FROM+Contact+WHERE+...`

#### `sf_upsert_contact`
Insert or update a Contact using an external ID field.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `external_id_field` | str | Yes | External ID field API name |
| `external_id_value` | str | Yes | External ID value |
| `last_name` | str | No | Last name |
| `first_name` | str | No | First name |
| `email` | str | No | Email |
| `phone` | str | No | Phone |
| `account_id` | str | No | Account ID |
| `custom_fields` | dict | No | Additional fields |

**Returns:** 201 (created) or 204 (updated).
**Endpoint:** `PATCH /services/data/v59.0/sobjects/Contact/{external_id_field}/{external_id_value}`

---

### Tier 3: Opportunity SObject (6 tools)

#### `sf_create_opportunity`
Create a new Opportunity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Opportunity name |
| `stage_name` | str | Yes | Current stage (must match a valid stage in the org) |
| `close_date` | str | Yes | Expected close date (`YYYY-MM-DD`) |
| `account_id` | str | No | Associated Account ID |
| `amount` | float | No | Deal amount |
| `probability` | float | No | Win probability (0-100) |
| `type` | str | No | Opportunity type |
| `lead_source` | str | No | Lead source |
| `description` | str | No | Description |
| `owner_id` | str | No | Owner user ID |
| `next_step` | str | No | Next step description |
| `custom_fields` | dict | No | Additional fields |

**Returns:** `{"id": "006xx...", "success": true, "errors": []}`
**Endpoint:** `POST /services/data/v59.0/sobjects/Opportunity/`

#### `sf_get_opportunity`
Retrieve an Opportunity by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `opportunity_id` | str | Yes | Opportunity ID |
| `fields` | list[str] | No | Specific fields to retrieve |

**Returns:** Opportunity record.
**Endpoint:** `GET /services/data/v59.0/sobjects/Opportunity/{opportunity_id}`

#### `sf_update_opportunity`
Update an existing Opportunity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `opportunity_id` | str | Yes | Opportunity ID |
| `name` | str | No | Updated name |
| `stage_name` | str | No | Updated stage |
| `close_date` | str | No | Updated close date |
| `amount` | float | No | Updated amount |
| `probability` | float | No | Updated probability |
| `type` | str | No | Updated type |
| `description` | str | No | Updated description |
| `owner_id` | str | No | Updated owner |
| `next_step` | str | No | Updated next step |
| `custom_fields` | dict | No | Additional fields |

**Returns:** HTTP 204 No Content.
**Endpoint:** `PATCH /services/data/v59.0/sobjects/Opportunity/{opportunity_id}`

#### `sf_delete_opportunity`
Delete an Opportunity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `opportunity_id` | str | Yes | Opportunity ID |

**Returns:** HTTP 204 No Content.
**Endpoint:** `DELETE /services/data/v59.0/sobjects/Opportunity/{opportunity_id}`

#### `sf_list_opportunities`
List Opportunities with common filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Max records (default 20) |
| `offset` | int | No | Records to skip |
| `order_by` | str | No | Sort field (default `CloseDate`) |
| `order_dir` | str | No | `ASC` or `DESC` |
| `account_id` | str | No | Filter by Account ID |
| `stage_name` | str | No | Filter by exact stage |
| `owner_id` | str | No | Filter by owner |
| `close_date_gte` | str | No | Filter: close date >= (`YYYY-MM-DD`) |
| `close_date_lte` | str | No | Filter: close date <= (`YYYY-MM-DD`) |
| `amount_gte` | float | No | Filter: amount >= |
| `amount_lte` | float | No | Filter: amount <= |
| `fields` | list[str] | No | Fields to return (default: Id, Name, StageName, Amount, CloseDate, AccountId, Probability) |

**Returns:** SOQL query result.
**Endpoint:** `GET /services/data/v59.0/query/?q=SELECT+...+FROM+Opportunity+WHERE+...`

#### `sf_upsert_opportunity`
Insert or update an Opportunity using an external ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `external_id_field` | str | Yes | External ID field API name |
| `external_id_value` | str | Yes | External ID value |
| `name` | str | No | Opportunity name |
| `stage_name` | str | No | Stage |
| `close_date` | str | No | Close date |
| `amount` | float | No | Amount |
| `account_id` | str | No | Account ID |
| `custom_fields` | dict | No | Additional fields |

**Returns:** 201 or 204.
**Endpoint:** `PATCH /services/data/v59.0/sobjects/Opportunity/{external_id_field}/{external_id_value}`

---

### Tier 4: Lead SObject (6 tools)

#### `sf_create_lead`
Create a new Lead.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `last_name` | str | Yes | Last name (required) |
| `company` | str | Yes | Company name (required) |
| `first_name` | str | No | First name |
| `email` | str | No | Email |
| `phone` | str | No | Phone |
| `title` | str | No | Job title |
| `status` | str | No | Lead status (picklist; default varies by org) |
| `lead_source` | str | No | Lead source |
| `industry` | str | No | Industry |
| `annual_revenue` | float | No | Annual revenue |
| `number_of_employees` | int | No | Employee count |
| `street` | str | No | Street address |
| `city` | str | No | City |
| `state` | str | No | State |
| `postal_code` | str | No | Postal code |
| `country` | str | No | Country |
| `description` | str | No | Description |
| `owner_id` | str | No | Owner user ID |
| `custom_fields` | dict | No | Additional fields |

**Returns:** `{"id": "00Qxx...", "success": true, "errors": []}`
**Endpoint:** `POST /services/data/v59.0/sobjects/Lead/`

#### `sf_get_lead`
Retrieve a Lead by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `lead_id` | str | Yes | Lead ID |
| `fields` | list[str] | No | Specific fields |

**Returns:** Lead record.
**Endpoint:** `GET /services/data/v59.0/sobjects/Lead/{lead_id}`

#### `sf_update_lead`
Update an existing Lead.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `lead_id` | str | Yes | Lead ID |
| `first_name` | str | No | Updated first name |
| `last_name` | str | No | Updated last name |
| `company` | str | No | Updated company |
| `email` | str | No | Updated email |
| `phone` | str | No | Updated phone |
| `title` | str | No | Updated title |
| `status` | str | No | Updated status |
| `lead_source` | str | No | Updated lead source |
| `description` | str | No | Updated description |
| `owner_id` | str | No | Updated owner |
| `custom_fields` | dict | No | Additional fields |

**Returns:** HTTP 204.
**Endpoint:** `PATCH /services/data/v59.0/sobjects/Lead/{lead_id}`

#### `sf_delete_lead`
Delete a Lead.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `lead_id` | str | Yes | Lead ID |

**Returns:** HTTP 204.
**Endpoint:** `DELETE /services/data/v59.0/sobjects/Lead/{lead_id}`

#### `sf_list_leads`
List Leads with filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Max records (default 20) |
| `offset` | int | No | Records to skip |
| `order_by` | str | No | Sort field (default `CreatedDate`) |
| `order_dir` | str | No | `ASC` or `DESC` |
| `status` | str | No | Filter by status |
| `owner_id` | str | No | Filter by owner |
| `company` | str | No | Filter by exact company |
| `is_converted` | bool | No | Filter by conversion status |
| `lead_source` | str | No | Filter by lead source |
| `fields` | list[str] | No | Fields to return (default: Id, FirstName, LastName, Email, Company, Status, LeadSource) |

**Returns:** SOQL query result.
**Endpoint:** `GET /services/data/v59.0/query/?q=SELECT+...+FROM+Lead+WHERE+...`

#### `sf_convert_lead`
Convert a Lead to Account, Contact, and optionally Opportunity. Uses the composite/sobject endpoint or custom Apex.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `lead_id` | str | Yes | Lead ID to convert |
| `account_id` | str | No | Existing Account to merge into (creates new if omitted) |
| `contact_id` | str | No | Existing Contact to merge into |
| `opportunity_name` | str | No | Opportunity name (omit or set `do_not_create_opportunity=true` to skip) |
| `do_not_create_opportunity` | bool | No | If true, skip Opportunity creation (default false) |
| `owner_id` | str | No | Owner for new records |
| `converted_status` | str | Yes | Lead status that represents "converted" (must be valid converted status in org) |

**Returns:** `{"accountId": "001xx...", "contactId": "003xx...", "opportunityId": "006xx..."}`
**Endpoint:** `POST /services/data/v59.0/actions/standard/convertLead` (Invocable Action)
**Body:**
```json
{"inputs": [{"leadId": "00Qxx...", "convertedStatus": "Closed - Converted", ...}]}
```

---

### Tier 5: Case SObject (6 tools)

#### `sf_create_case`
Create a new Case.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | str | No | Case subject |
| `description` | str | No | Case description |
| `status` | str | No | Case status (e.g., `New`, `Working`, `Closed`) |
| `priority` | str | No | Priority (e.g., `High`, `Medium`, `Low`) |
| `origin` | str | No | Case origin (e.g., `Phone`, `Email`, `Web`) |
| `type` | str | No | Case type |
| `account_id` | str | No | Associated Account ID |
| `contact_id` | str | No | Associated Contact ID |
| `owner_id` | str | No | Owner user ID |
| `reason` | str | No | Case reason |
| `custom_fields` | dict | No | Additional fields |

**Returns:** `{"id": "500xx...", "success": true, "errors": []}`
**Endpoint:** `POST /services/data/v59.0/sobjects/Case/`

#### `sf_get_case`
Retrieve a Case by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `case_id` | str | Yes | Case ID |
| `fields` | list[str] | No | Specific fields |

**Returns:** Case record.
**Endpoint:** `GET /services/data/v59.0/sobjects/Case/{case_id}`

#### `sf_update_case`
Update an existing Case.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `case_id` | str | Yes | Case ID |
| `subject` | str | No | Updated subject |
| `description` | str | No | Updated description |
| `status` | str | No | Updated status |
| `priority` | str | No | Updated priority |
| `origin` | str | No | Updated origin |
| `type` | str | No | Updated type |
| `owner_id` | str | No | Updated owner |
| `reason` | str | No | Updated reason |
| `custom_fields` | dict | No | Additional fields |

**Returns:** HTTP 204.
**Endpoint:** `PATCH /services/data/v59.0/sobjects/Case/{case_id}`

#### `sf_delete_case`
Delete a Case.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `case_id` | str | Yes | Case ID |

**Returns:** HTTP 204.
**Endpoint:** `DELETE /services/data/v59.0/sobjects/Case/{case_id}`

#### `sf_list_cases`
List Cases with filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Max records (default 20) |
| `offset` | int | No | Records to skip |
| `order_by` | str | No | Sort field (default `CreatedDate`) |
| `order_dir` | str | No | `ASC` or `DESC` (default `DESC`) |
| `status` | str | No | Filter by status |
| `priority` | str | No | Filter by priority |
| `account_id` | str | No | Filter by Account |
| `contact_id` | str | No | Filter by Contact |
| `owner_id` | str | No | Filter by owner |
| `fields` | list[str] | No | Fields to return (default: Id, Subject, Status, Priority, AccountId, ContactId, CreatedDate) |

**Returns:** SOQL query result.
**Endpoint:** `GET /services/data/v59.0/query/?q=SELECT+...+FROM+Case+WHERE+...`

#### `sf_add_case_comment`
Add a comment to a Case.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `case_id` | str | Yes | Parent Case ID |
| `body` | str | Yes | Comment text |
| `is_published` | bool | No | Visible to customer in portal (default false) |

**Returns:** `{"id": "00axx...", "success": true}`
**Endpoint:** `POST /services/data/v59.0/sobjects/CaseComment/`
**Body:** `{"ParentId": "{case_id}", "CommentBody": "...", "IsPublished": false}`

---

### Tier 6: Task SObject (5 tools)

#### `sf_create_task`
Create a new Task.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | str | No | Task subject |
| `status` | str | No | Status (e.g., `Not Started`, `In Progress`, `Completed`) |
| `priority` | str | No | Priority (e.g., `High`, `Normal`, `Low`) |
| `activity_date` | str | No | Due date (`YYYY-MM-DD`) |
| `who_id` | str | No | Related Contact or Lead ID |
| `what_id` | str | No | Related Account, Opportunity, or other object ID |
| `description` | str | No | Task description |
| `owner_id` | str | No | Owner user ID |
| `is_reminder_set` | bool | No | Enable reminder |
| `reminder_date_time` | str | No | Reminder datetime (ISO 8601) |
| `custom_fields` | dict | No | Additional fields |

**Returns:** `{"id": "00Txx...", "success": true}`
**Endpoint:** `POST /services/data/v59.0/sobjects/Task/`

#### `sf_get_task`
Retrieve a Task by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `fields` | list[str] | No | Specific fields |

**Returns:** Task record.
**Endpoint:** `GET /services/data/v59.0/sobjects/Task/{task_id}`

#### `sf_update_task`
Update a Task.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |
| `subject` | str | No | Updated subject |
| `status` | str | No | Updated status |
| `priority` | str | No | Updated priority |
| `activity_date` | str | No | Updated due date |
| `description` | str | No | Updated description |
| `owner_id` | str | No | Updated owner |
| `custom_fields` | dict | No | Additional fields |

**Returns:** HTTP 204.
**Endpoint:** `PATCH /services/data/v59.0/sobjects/Task/{task_id}`

#### `sf_delete_task`
Delete a Task.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | str | Yes | Task ID |

**Returns:** HTTP 204.
**Endpoint:** `DELETE /services/data/v59.0/sobjects/Task/{task_id}`

#### `sf_list_tasks`
List Tasks with filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Max records (default 20) |
| `offset` | int | No | Records to skip |
| `order_by` | str | No | Sort field (default `ActivityDate`) |
| `order_dir` | str | No | `ASC` or `DESC` |
| `status` | str | No | Filter by status |
| `priority` | str | No | Filter by priority |
| `who_id` | str | No | Filter by related Contact/Lead |
| `what_id` | str | No | Filter by related object |
| `owner_id` | str | No | Filter by owner |
| `fields` | list[str] | No | Fields to return (default: Id, Subject, Status, Priority, ActivityDate, WhoId, WhatId) |

**Returns:** SOQL query result.
**Endpoint:** `GET /services/data/v59.0/query/?q=SELECT+...+FROM+Task+WHERE+...`

---

### Tier 7: Event SObject (5 tools)

#### `sf_create_event`
Create a new Event.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | str | No | Event subject |
| `start_date_time` | str | Yes | Start datetime (ISO 8601, e.g., `2024-01-15T09:00:00.000+0000`) |
| `end_date_time` | str | Yes | End datetime |
| `is_all_day_event` | bool | No | All-day event (if true, use `ActivityDate` instead of datetimes) |
| `activity_date` | str | No | Date for all-day events (`YYYY-MM-DD`) |
| `location` | str | No | Event location |
| `who_id` | str | No | Related Contact or Lead ID |
| `what_id` | str | No | Related Account, Opportunity, etc. |
| `description` | str | No | Event description |
| `owner_id` | str | No | Owner user ID |
| `show_as` | str | No | Calendar display (`Busy`, `Free`, `OutOfOffice`) |
| `is_private` | bool | No | Private event |
| `is_reminder_set` | bool | No | Enable reminder |
| `reminder_date_time` | str | No | Reminder datetime |
| `custom_fields` | dict | No | Additional fields |

**Returns:** `{"id": "00Uxx...", "success": true}`
**Endpoint:** `POST /services/data/v59.0/sobjects/Event/`

#### `sf_get_event`
Retrieve an Event by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID |
| `fields` | list[str] | No | Specific fields |

**Returns:** Event record.
**Endpoint:** `GET /services/data/v59.0/sobjects/Event/{event_id}`

#### `sf_update_event`
Update an Event.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID |
| `subject` | str | No | Updated subject |
| `start_date_time` | str | No | Updated start |
| `end_date_time` | str | No | Updated end |
| `location` | str | No | Updated location |
| `description` | str | No | Updated description |
| `owner_id` | str | No | Updated owner |
| `show_as` | str | No | Updated calendar display |
| `custom_fields` | dict | No | Additional fields |

**Returns:** HTTP 204.
**Endpoint:** `PATCH /services/data/v59.0/sobjects/Event/{event_id}`

#### `sf_delete_event`
Delete an Event.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID |

**Returns:** HTTP 204.
**Endpoint:** `DELETE /services/data/v59.0/sobjects/Event/{event_id}`

#### `sf_list_events`
List Events with filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Max records (default 20) |
| `offset` | int | No | Records to skip |
| `order_by` | str | No | Sort field (default `StartDateTime`) |
| `order_dir` | str | No | `ASC` or `DESC` |
| `who_id` | str | No | Filter by related Contact/Lead |
| `what_id` | str | No | Filter by related object |
| `owner_id` | str | No | Filter by owner |
| `start_date_gte` | str | No | Filter: start >= (ISO datetime) |
| `start_date_lte` | str | No | Filter: start <= (ISO datetime) |
| `fields` | list[str] | No | Fields to return (default: Id, Subject, StartDateTime, EndDateTime, Location, WhoId, WhatId) |

**Returns:** SOQL query result.
**Endpoint:** `GET /services/data/v59.0/query/?q=SELECT+...+FROM+Event+WHERE+...`

---

### Tier 8: SOQL Queries (3 tools)

#### `sf_query`
Execute an arbitrary SOQL query.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | Yes | Full SOQL query string (e.g., `SELECT Id, Name FROM Account WHERE Industry = 'Technology'`) |

**Returns:** `{"totalSize": N, "done": true/false, "nextRecordsUrl": "...", "records": [...]}`
**Endpoint:** `GET /services/data/v59.0/query/?q={url_encoded_query}`
**Note:** Query string is URL-encoded automatically. Max 50,000 rows; if `done` is false, use `sf_query_more`.

#### `sf_query_more`
Retrieve the next page of a SOQL query result.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `next_records_url` | str | Yes | The `nextRecordsUrl` value from a previous query response (e.g., `/services/data/v59.0/query/01gxx...-2000`) |

**Returns:** Next batch of records with same structure as `sf_query`.
**Endpoint:** `GET {instance_url}{next_records_url}`

#### `sf_query_all`
Execute SOQL query including deleted and archived records.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | Yes | SOQL query string |

**Returns:** Same as `sf_query` but includes soft-deleted records.
**Endpoint:** `GET /services/data/v59.0/queryAll/?q={url_encoded_query}`
**Note:** Use this when you need to find records in the Recycle Bin.

---

### Tier 9: SOSL Search (1 tool)

#### `sf_search`
Execute a SOSL full-text search across multiple objects.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `search` | str | Yes | SOSL search string (e.g., `FIND {john doe} IN ALL FIELDS RETURNING Account(Id, Name), Contact(Id, Name, Email) LIMIT 20`) |

**Returns:** `{"searchRecords": [{"attributes": {"type": "Account", "url": "..."}, "Id": "001xx...", "Name": "..."}]}`
**Endpoint:** `GET /services/data/v59.0/search/?q={url_encoded_sosl}`
**Note:** Max 2,000 results. SOSL supports wildcards (`*`, `?`), phrase search with quotes, and logical operators (AND, OR, NOT).

---

### Tier 10: Describe / Metadata (4 tools)

#### `sf_describe_sobject`
Get full metadata description of an SObject (fields, picklists, record types, relationships).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sobject_name` | str | Yes | SObject API name (e.g., `Account`, `Contact`, `Custom_Object__c`) |

**Returns:** Full describe result including `fields[]` (each with name, type, label, picklist values, length), `recordTypeInfos[]`, `childRelationships[]`, and object-level metadata.
**Endpoint:** `GET /services/data/v59.0/sobjects/{sobject_name}/describe/`
**Note:** Heavy response -- can be 100KB+ for objects with many fields. Consider caching.

#### `sf_describe_global`
List all SObjects available in the org.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** `{"sobjects": [{"name": "Account", "label": "Account", "queryable": true, "createable": true, ...}]}`
**Endpoint:** `GET /services/data/v59.0/sobjects/`
**Note:** Returns high-level info about all objects. Does not include field details (use `sf_describe_sobject` for that).

#### `sf_get_record_types`
Get record types for an SObject (convenience wrapper around describe).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sobject_name` | str | Yes | SObject API name |

**Returns:** Array of `{"recordTypeId": "012xx...", "name": "...", "developerName": "...", "isActive": true, "isDefault": true}`.
**Endpoint:** Extracts `recordTypeInfos` from `GET /services/data/v59.0/sobjects/{sobject_name}/describe/`

#### `sf_get_picklist_values`
Get valid picklist values for a field on an SObject (convenience wrapper around describe).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sobject_name` | str | Yes | SObject API name |
| `field_name` | str | Yes | Field API name (e.g., `Industry`, `Status`, `StageName`) |

**Returns:** Array of `{"value": "...", "label": "...", "active": true, "defaultValue": false}`.
**Endpoint:** Extracts field's `picklistValues` from `GET /services/data/v59.0/sobjects/{sobject_name}/describe/`

---

### Tier 11: Generic SObject CRUD (5 tools)

For custom objects or less common standard objects not covered by dedicated tools.

#### `sf_create_record`
Create a record of any SObject type.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sobject_name` | str | Yes | SObject API name (e.g., `Custom_Object__c`, `OpportunityLineItem`) |
| `fields` | dict | Yes | Field name-value pairs for the new record |

**Returns:** `{"id": "...", "success": true, "errors": []}`
**Endpoint:** `POST /services/data/v59.0/sobjects/{sobject_name}/`

#### `sf_get_record`
Get a record of any SObject type by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sobject_name` | str | Yes | SObject API name |
| `record_id` | str | Yes | Record ID |
| `fields` | list[str] | No | Specific fields to retrieve |

**Returns:** Record with requested fields.
**Endpoint:** `GET /services/data/v59.0/sobjects/{sobject_name}/{record_id}`

#### `sf_update_record`
Update a record of any SObject type.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sobject_name` | str | Yes | SObject API name |
| `record_id` | str | Yes | Record ID |
| `fields` | dict | Yes | Field name-value pairs to update |

**Returns:** HTTP 204.
**Endpoint:** `PATCH /services/data/v59.0/sobjects/{sobject_name}/{record_id}`

#### `sf_delete_record`
Delete a record of any SObject type.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sobject_name` | str | Yes | SObject API name |
| `record_id` | str | Yes | Record ID |

**Returns:** HTTP 204.
**Endpoint:** `DELETE /services/data/v59.0/sobjects/{sobject_name}/{record_id}`

#### `sf_upsert_record`
Insert or update any SObject using an external ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sobject_name` | str | Yes | SObject API name |
| `external_id_field` | str | Yes | External ID field API name |
| `external_id_value` | str | Yes | External ID value |
| `fields` | dict | Yes | Field name-value pairs |

**Returns:** 201 or 204.
**Endpoint:** `PATCH /services/data/v59.0/sobjects/{sobject_name}/{external_id_field}/{external_id_value}`

---

### Tier 12: Bulk Operations (4 tools)

Uses Salesforce Bulk API 2.0 for large-volume operations.

#### `sf_bulk_create_job`
Create a new Bulk API 2.0 ingest job.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sobject_name` | str | Yes | SObject API name (e.g., `Account`) |
| `operation` | str | Yes | Operation type: `insert`, `update`, `upsert`, `delete`, `hardDelete` |
| `external_id_field` | str | No | Required for `upsert` -- external ID field name |
| `line_ending` | str | No | `CRLF` or `LF` (default `LF`) |
| `column_delimiter` | str | No | `COMMA`, `TAB`, `PIPE`, `SEMICOLON`, `CARET`, `BACKQUOTE` (default `COMMA`) |

**Returns:** Job info with `id`, `state` (`Open`), `jobType`, etc.
**Endpoint:** `POST /services/data/v59.0/jobs/ingest/`
**Body:** `{"object": "Account", "operation": "insert", "contentType": "CSV"}`

#### `sf_bulk_upload_data`
Upload CSV data to an open Bulk API 2.0 job.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `job_id` | str | Yes | Bulk job ID from `sf_bulk_create_job` |
| `csv_data` | str | Yes | CSV content with header row (e.g., `Name,Industry\nAcme,Technology\nGlobal Corp,Finance`) |

**Returns:** HTTP 201 on success.
**Endpoint:** `PUT /services/data/v59.0/jobs/ingest/{job_id}/batches`
**Content-Type:** `text/csv`
**Note:** Max 150 MB per upload. After uploading, close the job with `sf_bulk_close_job`.

#### `sf_bulk_close_job`
Close or abort a Bulk API 2.0 job. Closing triggers processing.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `job_id` | str | Yes | Bulk job ID |
| `state` | str | Yes | `UploadComplete` (to process) or `Aborted` (to cancel) |

**Returns:** Updated job info with new state.
**Endpoint:** `PATCH /services/data/v59.0/jobs/ingest/{job_id}`
**Body:** `{"state": "UploadComplete"}`

#### `sf_bulk_get_job_status`
Get the status and results of a Bulk API 2.0 job.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `job_id` | str | Yes | Bulk job ID |
| `result_type` | str | No | If set, retrieve results: `successfulResults`, `failedResults`, or `unprocessedrecords`. Omit to get job status only |

**Returns:** Job status: `{"id": "...", "state": "JobComplete", "numberRecordsProcessed": 100, "numberRecordsFailed": 2, ...}`. With `result_type`: CSV content of results.
**Endpoint:** `GET /services/data/v59.0/jobs/ingest/{job_id}` (status) or `GET /services/data/v59.0/jobs/ingest/{job_id}/{result_type}` (results)
**Note:** Poll until `state` is `JobComplete` or `Failed`. Result CSVs include `sf__Id` (created ID) and `sf__Error` columns.

---

### Tier 13: Composite Requests (2 tools)

#### `sf_composite`
Execute multiple API requests in a single call (up to 25 subrequests).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `composite_request` | list[dict] | Yes | Array of subrequests. Each: `{"method": "POST", "url": "/services/data/v59.0/sobjects/Account/", "referenceId": "newAccount", "body": {"Name": "Acme"}}` |
| `all_or_none` | bool | No | If true, rollback all on any failure (default false) |

**Returns:** `{"compositeResponse": [{"httpStatusCode": 200, "referenceId": "newAccount", "body": {...}}]}`
**Endpoint:** `POST /services/data/v59.0/composite/`
**Body:**
```json
{
  "allOrNone": true,
  "compositeRequest": [
    {"method": "POST", "url": "/services/data/v59.0/sobjects/Account/", "referenceId": "newAccount", "body": {"Name": "Acme"}},
    {"method": "POST", "url": "/services/data/v59.0/sobjects/Contact/", "referenceId": "newContact", "body": {"LastName": "Smith", "AccountId": "@{newAccount.id}"}}
  ]
}
```
**Note:** Subrequests can reference each other using `@{referenceId.field}` syntax. Max 25 subrequests. Processed in order.

#### `sf_composite_batch`
Execute multiple independent requests in a single call (up to 25, executed independently -- no cross-referencing).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `batch_requests` | list[dict] | Yes | Array of requests. Each: `{"method": "GET", "url": "/services/data/v59.0/sobjects/Account/001xx..."}` |
| `halt_on_error` | bool | No | If true, stop on first error (default false) |

**Returns:** `{"hasErrors": false, "results": [{"statusCode": 200, "result": {...}}]}`
**Endpoint:** `POST /services/data/v59.0/composite/batch`
**Note:** Unlike `sf_composite`, subrequests cannot reference each other. All execute independently. Slightly more efficient than composite when cross-references are not needed.

---

### Tier 14: Reports (3 tools)

#### `sf_list_reports`
List available reports.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Max results (default 20) |
| `offset` | int | No | Records to skip |
| `folder_id` | str | No | Filter by report folder ID |

**Returns:** SOQL query result of Report records.
**Endpoint:** `GET /services/data/v59.0/query/?q=SELECT+Id,Name,DeveloperName,FolderName+FROM+Report+LIMIT+20`

#### `sf_run_report`
Execute a report and get results.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `report_id` | str | Yes | Report ID (e.g., `00Oxx...`) |
| `include_details` | bool | No | Include detail rows (default true). Set false for summary only |
| `filters` | list[dict] | No | Runtime filter overrides. Each: `{"column": "ACCOUNT_NAME", "operator": "contains", "value": "Acme"}` |

**Returns:** Report results with `{"reportMetadata": {...}, "factMap": {...}, "groupingsDown": {...}, "groupingsAcross": {...}}`.
**Endpoint:** `POST /services/data/v59.0/analytics/reports/{report_id}` (POST with empty body runs synchronously; POST with filters body applies runtime filters)
**Body (with filters):**
```json
{
  "reportMetadata": {
    "reportFilters": [
      {"column": "ACCOUNT_NAME", "operator": "contains", "value": "Acme"}
    ]
  }
}
```
**Note:** Synchronous execution has a 2-minute timeout. For long reports, use async (not covered here -- requires polling).

#### `sf_describe_report`
Get report metadata (columns, filters, groupings) without running it.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `report_id` | str | Yes | Report ID |

**Returns:** `{"reportMetadata": {"id": "...", "name": "...", "reportType": {...}, "reportFormat": "TABULAR", "detailColumns": [...], "reportFilters": [...], "groupingsDown": [...]}}`
**Endpoint:** `GET /services/data/v59.0/analytics/reports/{report_id}/describe`

---

### Tier 15: Miscellaneous (4 tools)

#### `sf_get_limits`
Get current org API usage limits.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** `{"DailyApiRequests": {"Max": 100000, "Remaining": 99950}, "DailyBulkApiRequests": {"Max": 15000, "Remaining": 14990}, ...}`
**Endpoint:** `GET /services/data/v59.0/limits/`

#### `sf_get_user`
Get details about a user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | str | Yes | User ID (e.g., `005xx...`) |
| `fields` | list[str] | No | Specific fields |

**Returns:** User record.
**Endpoint:** `GET /services/data/v59.0/sobjects/User/{user_id}`

#### `sf_get_current_user`
Get details about the authenticated user.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** User info from the identity URL.
**Endpoint:** Uses `id` URL from token response: `GET {id_url}`
**Note:** The token response includes an `id` field with the user info URL.

#### `sf_get_api_versions`
List available API versions on the Salesforce instance.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | |

**Returns:** Array of `{"version": "59.0", "label": "Winter '24", "url": "/services/data/v59.0"}`.
**Endpoint:** `GET /services/data/`

---

## Tool Count Summary

| Tier | Category | Tools |
|------|----------|-------|
| 1 | Account SObject | 6 |
| 2 | Contact SObject | 6 |
| 3 | Opportunity SObject | 6 |
| 4 | Lead SObject | 6 |
| 5 | Case SObject | 6 |
| 6 | Task SObject | 5 |
| 7 | Event SObject | 5 |
| 8 | SOQL Queries | 3 |
| 9 | SOSL Search | 1 |
| 10 | Describe / Metadata | 4 |
| 11 | Generic SObject CRUD | 5 |
| 12 | Bulk Operations | 4 |
| 13 | Composite Requests | 2 |
| 14 | Reports | 3 |
| 15 | Miscellaneous | 4 |
| **Total** | | **66** |

---

## Dependencies

### Required (already in project)
- `httpx` -- Async HTTP client for all REST calls
- `mcp` -- FastMCP framework

### No New Dependencies
No Salesforce SDK needed. The REST API is straightforward JSON over HTTP. Using `httpx` directly (consistent with ClickUp, HubSpot, Stripe patterns) provides full async control and avoids heavyweight SDK dependencies.

---

## Implementation Notes

### File Structure
- **Config:** Add `SF_CLIENT_ID`, `SF_CLIENT_SECRET`, `SF_REFRESH_TOKEN`, `SF_INSTANCE_URL`, `SF_API_VERSION` to `config.py`
- **Tool file:** `src/mcp_toolbox/tools/salesforce_tool.py`
- **Registration:** Add to `tools/__init__.py` `register_all_tools()`

### Auth Pattern (from quickbooks_tool.py)
```python
async def _get_token() -> tuple[str, str]:
    """Returns (access_token, instance_url)."""
    global _access_token, _token_expires_at, _instance_url, _token_lock
    _check_config()
    if _token_lock is None:
        _token_lock = asyncio.Lock()
    async with _token_lock:
        if _access_token and _instance_url and time.time() < _token_expires_at - 60:
            return _access_token, _instance_url
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                "https://login.salesforce.com/services/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": SF_CLIENT_ID,
                    "client_secret": SF_CLIENT_SECRET,
                    "refresh_token": SF_REFRESH_TOKEN,
                },
                timeout=30.0,
            )
        if resp.status_code != 200:
            raise ToolError(f"SF token refresh failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        _access_token = data["access_token"]
        _instance_url = SF_INSTANCE_URL or data["instance_url"]
        # SF doesn't return expires_in; default to 2 hours
        _token_expires_at = time.time() + 7200
        return _access_token, _instance_url
```

### HTTP Helper
```python
async def _sf_request(method: str, path: str, **kwargs) -> dict | str | None:
    """Make authenticated request to Salesforce REST API."""
    token, instance_url = await _get_token()
    url = f"{instance_url}/services/data/{SF_API_VERSION}/{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        resp = await client.request(method, url, headers=headers, timeout=60.0, **kwargs)
    if resp.status_code == 204:
        return None  # Success with no content (update/delete)
    if resp.status_code >= 400:
        raise ToolError(f"Salesforce API error ({resp.status_code}): {resp.text}")
    return resp.json()
```

### SOQL Query Builder
A helper function to build SOQL queries from filter parameters, preventing SOQL injection by sanitizing string values:
```python
def _build_soql(sobject: str, fields: list[str], filters: dict, order_by: str, order_dir: str, limit: int, offset: int) -> str:
    """Build a safe SOQL query string."""
    where_clauses = []
    for field, value in filters.items():
        if isinstance(value, str):
            escaped = value.replace("'", "\\'")
            where_clauses.append(f"{field} = '{escaped}'")
        elif isinstance(value, bool):
            where_clauses.append(f"{field} = {str(value).lower()}")
        else:
            where_clauses.append(f"{field} = {value}")
    # ... build SELECT ... FROM ... WHERE ... ORDER BY ... LIMIT ... OFFSET
```

### pyright Configuration
Include this file in pyright checks -- no untyped SDKs involved (pure httpx + JSON).

### Test Strategy
- Unit tests with httpx mock transport (consistent with other tool tests)
- Test token refresh flow (mock token endpoint)
- Test SOQL query builder with various filter combinations
- Test error handling for Salesforce error response format (JSON array)
- Test 204 No Content handling for update/delete operations
