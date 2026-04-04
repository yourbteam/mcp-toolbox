# Task 15: QuickBooks Online Integration - Analysis & Requirements

## Objective
Add QuickBooks Online (QBO) as a tool integration in mcp-toolbox, exposing accounting and financial management capabilities (customers, invoices, payments, items, accounts, bills, vendors, estimates, credit memos, purchases, reports, company info) as MCP tools for LLM clients.

---

## API Technical Details

### QuickBooks Online Accounting API v3 -- REST
- **Production Base URL:** `https://quickbooks.api.intuit.com/v3/company/{realmId}/`
- **Sandbox Base URL:** `https://sandbox-quickbooks.api.intuit.com/v3/company/{realmId}/`
- **Auth:** OAuth 2.0 with Bearer token (access token obtained via refresh token flow)
- **Format:** JSON request/response (set `Accept: application/json` and `Content-Type: application/json`)
- **Minor Version:** Append `?minorversion=75` (current base version as of Aug 2025) to all requests for consistent behavior

### OAuth 2.0 Authentication Flow
QuickBooks uses OAuth 2.0 authorization code flow. For a service/daemon context (MCP toolbox), we use a **pre-obtained refresh token** stored in configuration. The tool auto-refreshes the access token when it expires.

**Token Refresh Endpoint:** `POST https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer`
- Content-Type: `application/x-www-form-urlencoded`
- Body: `grant_type=refresh_token&refresh_token={QB_REFRESH_TOKEN}`
- Authorization: `Basic base64(client_id:client_secret)`
- Response: `{"access_token": "...", "refresh_token": "...", "expires_in": 3600, "token_type": "bearer"}`

**Key behavior:**
- Access tokens expire after **1 hour** (3600 seconds)
- Refresh tokens expire after **100 days** but are rolling -- each refresh returns a new refresh token with a reset 100-day window
- **Important (Nov 2025 policy change):** All refresh tokens now have a **maximum lifetime of 5 years** from initial generation, regardless of rolling. Tokens generated from Oct 2023 (accounting/payments scopes) expire in Oct 2028
- The new refresh token must be persisted (in-memory is fine for session lifetime; log a warning about rotation)
- Token refresh is thread-safe via a lock to prevent concurrent refreshes

### Rate Limits

| Metric | Limit |
|--------|-------|
| Concurrent requests | 10 per realm (company) |
| Throttle | 500 requests / minute per realm |
| Batch size | Up to 30 entities per batch request |

- HTTP 429 on exceed; responses include `Retry-After` header
- HTTP 503 for temporary service unavailability (treat as transient)

### No Official Python SDK Needed
Intuit provides `python-quickbooks` (third-party) but it adds ORM complexity and sync-only HTTP. **Recommendation:** Use `httpx` (already in our dependencies) for direct async HTTP calls -- consistent with HubSpot/ClickUp pattern, simpler, full async control.

### Key Quirks
- **SyncToken required for updates** -- every entity has a `SyncToken` field (optimistic concurrency). You must read the current entity, get its SyncToken, and include it in the update. Omitting or using a stale SyncToken returns HTTP 400 with `stale object` error.
- **Sparse updates** -- set `"sparse": true` in update body to send only changed fields (otherwise the entire entity is overwritten).
- **Delete = deactivate for most entities** -- Customers, Vendors, Items, and Accounts use `"Active": false` (soft delete). Only Invoices, Payments, Bills, Estimates, Credit Memos, and Purchases support true `DELETE` or void operations.
- **Query language** -- QBO uses a SQL-like query language for listing/searching: `SELECT * FROM Customer WHERE DisplayName LIKE '%Smith%' MAXRESULTS 100 STARTPOSITION 1`
- **Pagination via STARTPOSITION** -- not cursor-based. Use `STARTPOSITION` (1-based) and `MAXRESULTS` (max 1000) in queries.
- **Line items pattern** -- Invoices, Estimates, Bills, Credit Memos, and Purchases use `"Line"` arrays with `DetailType` discriminator (`SalesItemLineDetail`, `ItemBasedExpenseLineDetail`, `AccountBasedExpenseLineDetail`).
- **Reference objects** -- related entities use `{"value": "id", "name": "display_name"}` reference format (e.g., `CustomerRef`, `ItemRef`, `AccountRef`).
- **Amounts as decimals** -- all monetary values are decimal numbers (not strings), precision to 2 decimal places.
- **Date format** -- dates use `YYYY-MM-DD` format (not ISO 8601 with time).
- **MetaData is read-only** -- `CreateTime` and `LastUpdatedTime` are in `MetaData` object, set by QBO.
- **Void vs Delete** -- voiding keeps the transaction visible but zeroes amounts; deleting removes it entirely. Voiding is preferred for audit trail.
- **Minor version parameter** -- append `?minorversion=75` to all API calls for consistent field behavior across API updates.

---

## QuickBooks Online Entity Model

```
Customers -----> Invoices -----> Payments
                    |
                    v
              Credit Memos
                    
Vendors -------> Bills --------> Bill Payments
                    
Items (Products/Services)
                    
Accounts (Chart of Accounts)
                    
Estimates (Quotes)
                    
Purchases (Expenses/Checks)
                    
Reports (P&L, Balance Sheet, AR Aging)
                    
Company Info
```

### Core Entities
| Entity | API Path | Key Fields |
|--------|----------|------------|
| Customer | `customer` | DisplayName, PrimaryEmailAddr, PrimaryPhone, BillAddr, Balance |
| Invoice | `invoice` | CustomerRef, Line[], TxnDate, DueDate, TotalAmt, Balance, EmailStatus |
| Payment | `payment` | CustomerRef, TotalAmt, TxnDate, Line[] (linked invoices) |
| Item | `item` | Name, Type (Service/Inventory/NonInventory), UnitPrice, IncomeAccountRef |
| Account | `account` | Name, AccountType, AccountSubType, CurrentBalance, Classification |
| Bill | `bill` | VendorRef, Line[], TxnDate, DueDate, TotalAmt, Balance |
| Vendor | `vendor` | DisplayName, PrimaryEmailAddr, PrimaryPhone, Balance |
| Estimate | `estimate` | CustomerRef, Line[], TxnDate, ExpirationDate, TotalAmt |
| Credit Memo | `creditmemo` | CustomerRef, Line[], TxnDate, TotalAmt, RemainingCredit |
| Purchase | `purchase` | AccountRef, PaymentType, Line[], TxnDate, TotalAmt |
| Company Info | `companyinfo` | CompanyName, LegalName, Country, FiscalYearStartMonth |

---

## Tool Specifications

### Tier 1: Customers (5 tools)

#### `qb_create_customer`
Create a new customer in QuickBooks Online.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `display_name` | str | Yes | Customer display name (must be unique across all name lists) |
| `given_name` | str | No | First name |
| `family_name` | str | No | Last name |
| `company_name` | str | No | Company/business name |
| `email` | str | No | Primary email address |
| `phone` | str | No | Primary phone number |
| `mobile` | str | No | Mobile phone number |
| `bill_address` | dict | No | Billing address: `{"Line1": "...", "City": "...", "CountrySubDivisionCode": "CA", "PostalCode": "94043", "Country": "US"}` |
| `ship_address` | dict | No | Shipping address (same format as bill_address) |
| `notes` | str | No | Free-form notes about the customer |
| `taxable` | bool | No | Whether the customer is taxable (default true) |
| `balance_opening` | float | No | Opening balance amount |
| `balance_opening_date` | str | No | Opening balance date (YYYY-MM-DD) |
| `payment_method_ref` | str | No | Default payment method ID |
| `term_ref` | str | No | Default payment terms ID (e.g., Net 30) |
| `extra_fields` | dict | No | Additional QBO fields as key-value pairs |

**Returns:** Created customer with Id, SyncToken, and all fields.
**Endpoint:** `POST /v3/company/{realmId}/customer`
**Body:**
```json
{
  "DisplayName": "Amy's Bird Sanctuary",
  "GivenName": "Amy",
  "FamilyName": "Lauterbach",
  "PrimaryEmailAddr": {"Address": "amy@birdssanctuary.com"},
  "PrimaryPhone": {"FreeFormNumber": "(555) 555-5555"},
  "BillAddr": {"Line1": "123 Main St", "City": "Bayshore", "CountrySubDivisionCode": "CA", "PostalCode": "94326"}
}
```

#### `qb_get_customer`
Get a customer by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer_id` | str | Yes | Customer ID |

**Returns:** Customer object with all fields including Balance and SyncToken.
**Endpoint:** `GET /v3/company/{realmId}/customer/{customerId}?minorversion=75`

#### `qb_update_customer`
Update an existing customer (sparse update).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer_id` | str | Yes | Customer ID |
| `sync_token` | str | Yes | Current SyncToken (from a previous GET; required for optimistic concurrency) |
| `display_name` | str | No | Updated display name |
| `given_name` | str | No | Updated first name |
| `family_name` | str | No | Updated last name |
| `company_name` | str | No | Updated company name |
| `email` | str | No | Updated email |
| `phone` | str | No | Updated phone |
| `bill_address` | dict | No | Updated billing address |
| `ship_address` | dict | No | Updated shipping address |
| `notes` | str | No | Updated notes |
| `taxable` | bool | No | Updated taxable flag |
| `active` | bool | No | Set false to deactivate (soft delete) |
| `term_ref` | str | No | Updated payment terms ID |
| `extra_fields` | dict | No | Additional QBO fields |

At least one field besides customer_id and sync_token must be provided.
**Returns:** Updated customer object.
**Endpoint:** `POST /v3/company/{realmId}/customer`
**Body:** `{"Id": "...", "SyncToken": "...", "sparse": true, "DisplayName": "...", ...}`

**Note:** QBO uses POST (not PATCH/PUT) for updates. The presence of `Id` + `SyncToken` indicates an update.

#### `qb_query_customers`
Query customers using QBO SQL-like query language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `where` | str | No | WHERE clause (e.g., `DisplayName LIKE '%Smith%'`, `Active = true`, `Balance > '0'`) |
| `order_by` | str | No | ORDER BY clause (e.g., `DisplayName ASC`) |
| `start_position` | int | No | 1-based start position for pagination (default 1) |
| `max_results` | int | No | Max results to return (default 100, max 1000) |

**Returns:** List of matching customers with count.
**Endpoint:** `GET /v3/company/{realmId}/query?query=SELECT * FROM Customer WHERE ... ORDERBY ... STARTPOSITION ... MAXRESULTS ...&minorversion=75`

#### `qb_delete_customer`
Deactivate (soft-delete) a customer by setting Active=false.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer_id` | str | Yes | Customer ID |
| `sync_token` | str | Yes | Current SyncToken |

**Returns:** Updated customer with Active=false.
**Endpoint:** `POST /v3/company/{realmId}/customer`
**Body:** `{"Id": "...", "SyncToken": "...", "sparse": true, "Active": false}`

**Note:** QBO customers cannot be hard-deleted. Deactivation hides them from active lists but preserves transaction history.

---

### Tier 2: Invoices (7 tools)

#### `qb_create_invoice`
Create a new invoice for a customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer_id` | str | Yes | Customer ID (CustomerRef.value) |
| `line_items` | list[dict] | Yes | Line items array. Each item: `{"DetailType": "SalesItemLineDetail", "Amount": 100.00, "SalesItemLineDetail": {"ItemRef": {"value": "1"}, "Qty": 2, "UnitPrice": 50.00}}` |
| `txn_date` | str | No | Transaction date (YYYY-MM-DD, default today) |
| `due_date` | str | No | Due date (YYYY-MM-DD) |
| `doc_number` | str | No | Custom invoice number (auto-generated if omitted) |
| `bill_email` | str | No | Email address for sending the invoice |
| `ship_address` | dict | No | Shipping address |
| `bill_address` | dict | No | Billing address (defaults to customer's billing address) |
| `customer_memo` | str | No | Memo visible to customer |
| `private_note` | str | No | Internal note (not visible to customer) |
| `term_ref` | str | No | Payment terms ID (e.g., Net 30) |
| `sales_term_ref` | str | No | Sales term reference ID |
| `deposit` | float | No | Deposit amount already received |
| `discount_percent` | float | No | Discount percentage (applied as a discount line) |
| `apply_tax_after_discount` | bool | No | Apply tax after discount (default false) |
| `extra_fields` | dict | No | Additional QBO fields |

**Returns:** Created invoice with Id, DocNumber, TotalAmt, Balance.
**Endpoint:** `POST /v3/company/{realmId}/invoice`
**Body:**
```json
{
  "CustomerRef": {"value": "1"},
  "Line": [
    {
      "DetailType": "SalesItemLineDetail",
      "Amount": 100.00,
      "SalesItemLineDetail": {
        "ItemRef": {"value": "1"},
        "Qty": 2,
        "UnitPrice": 50.00
      }
    }
  ],
  "TxnDate": "2026-04-01",
  "DueDate": "2026-05-01"
}
```

#### `qb_get_invoice`
Get an invoice by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID |

**Returns:** Invoice object with all fields including Line items, TotalAmt, Balance, SyncToken.
**Endpoint:** `GET /v3/company/{realmId}/invoice/{invoiceId}?minorversion=75`

#### `qb_update_invoice`
Update an existing invoice (sparse update).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID |
| `sync_token` | str | Yes | Current SyncToken |
| `customer_id` | str | No | Updated customer ID |
| `line_items` | list[dict] | No | Updated line items (replaces all lines when provided) |
| `txn_date` | str | No | Updated transaction date |
| `due_date` | str | No | Updated due date |
| `doc_number` | str | No | Updated invoice number |
| `bill_email` | str | No | Updated email address |
| `customer_memo` | str | No | Updated customer memo |
| `private_note` | str | No | Updated private note |
| `extra_fields` | dict | No | Additional QBO fields |

At least one field besides invoice_id and sync_token must be provided.
**Returns:** Updated invoice object.
**Endpoint:** `POST /v3/company/{realmId}/invoice`
**Body:** `{"Id": "...", "SyncToken": "...", "sparse": true, ...}`

#### `qb_query_invoices`
Query invoices using QBO SQL-like query language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `where` | str | No | WHERE clause (e.g., `CustomerRef = '123'`, `Balance > '0'`, `TxnDate >= '2026-01-01'`, `DocNumber = 'INV-001'`) |
| `order_by` | str | No | ORDER BY clause (e.g., `TxnDate DESC`) |
| `start_position` | int | No | 1-based start position (default 1) |
| `max_results` | int | No | Max results (default 100, max 1000) |

**Returns:** List of matching invoices with count.
**Endpoint:** `GET /v3/company/{realmId}/query?query=SELECT * FROM Invoice WHERE ...&minorversion=75`

#### `qb_send_invoice`
Send an invoice via email to the customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID to send |
| `email` | str | No | Override email address (defaults to customer's email on file) |

**Returns:** Updated invoice with EmailStatus set to `EmailSent`.
**Endpoint:** `POST /v3/company/{realmId}/invoice/{invoiceId}/send?sendTo={email}&minorversion=75`

#### `qb_void_invoice`
Void an invoice (zeros out amounts but keeps it visible for audit trail).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID |
| `sync_token` | str | Yes | Current SyncToken |

**Returns:** Voided invoice object.
**Endpoint:** `POST /v3/company/{realmId}/invoice?operation=void&minorversion=75`
**Body:** `{"Id": "...", "SyncToken": "..."}`

**Note:** QBO uses the `?operation=void` query parameter (not a body flag). The body only needs `Id` and `SyncToken`. Voiding zeros all amounts/quantities and injects "Voided" into PrivateNote.

#### `qb_delete_invoice`
Permanently delete an invoice.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID |
| `sync_token` | str | Yes | Current SyncToken |

**Returns:** Confirmation of deletion with deleted entity reference.
**Endpoint:** `POST /v3/company/{realmId}/invoice?operation=delete`
**Body:** `{"Id": "...", "SyncToken": "..."}`

**Note:** Prefer `qb_void_invoice` over delete for audit trail compliance. Deletion is irreversible.

---

### Tier 3: Payments (5 tools)

#### `qb_create_payment`
Record a payment received from a customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer_id` | str | Yes | Customer ID (CustomerRef.value) |
| `total_amt` | float | Yes | Total payment amount |
| `txn_date` | str | No | Payment date (YYYY-MM-DD, default today) |
| `payment_method_ref` | str | No | Payment method ID (Cash, Check, Credit Card, etc.) |
| `deposit_to_account_ref` | str | No | Account ID to deposit to (e.g., Undeposited Funds) |
| `invoice_refs` | list[dict] | No | Invoices to apply payment to: `[{"TxnId": "123", "TxnType": "Invoice"}]` with optional `"Amount"` per line |
| `payment_ref_num` | str | No | Reference number (e.g., check number) |
| `private_note` | str | No | Internal note |
| `currency_ref` | str | No | Currency code (e.g., `USD`) for multi-currency companies |
| `extra_fields` | dict | No | Additional QBO fields |

**Returns:** Created payment with Id, TotalAmt.
**Endpoint:** `POST /v3/company/{realmId}/payment`
**Body:**
```json
{
  "CustomerRef": {"value": "1"},
  "TotalAmt": 150.00,
  "TxnDate": "2026-04-01",
  "Line": [
    {
      "Amount": 150.00,
      "LinkedTxn": [{"TxnId": "123", "TxnType": "Invoice"}]
    }
  ]
}
```

#### `qb_get_payment`
Get a payment by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `payment_id` | str | Yes | Payment ID |

**Returns:** Payment object with all fields including linked transactions.
**Endpoint:** `GET /v3/company/{realmId}/payment/{paymentId}?minorversion=75`

#### `qb_query_payments`
Query payments using QBO SQL-like query language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `where` | str | No | WHERE clause (e.g., `CustomerRef = '123'`, `TxnDate >= '2026-01-01'`, `TotalAmt > '100'`) |
| `order_by` | str | No | ORDER BY clause (e.g., `TxnDate DESC`) |
| `start_position` | int | No | 1-based start position (default 1) |
| `max_results` | int | No | Max results (default 100, max 1000) |

**Returns:** List of matching payments with count.
**Endpoint:** `GET /v3/company/{realmId}/query?query=SELECT * FROM Payment WHERE ...&minorversion=75`

#### `qb_void_payment`
Void a payment (reverses the payment but keeps it visible for audit trail).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `payment_id` | str | Yes | Payment ID |
| `sync_token` | str | Yes | Current SyncToken |

**Returns:** Voided payment object.
**Endpoint:** `POST /v3/company/{realmId}/payment?operation=void&minorversion=75`
**Body:** `{"Id": "...", "SyncToken": "..."}`

#### `qb_delete_payment`
Permanently delete a payment.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `payment_id` | str | Yes | Payment ID |
| `sync_token` | str | Yes | Current SyncToken |

**Returns:** Confirmation of deletion.
**Endpoint:** `POST /v3/company/{realmId}/payment?operation=delete`
**Body:** `{"Id": "...", "SyncToken": "..."}`

---

### Tier 4: Items / Products & Services (4 tools)

#### `qb_create_item`
Create a new product or service item.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Item name (must be unique) |
| `type` | str | No | Item type: `Service` (default), `Inventory`, `NonInventory`, `Group`, `Category` |
| `description` | str | No | Sales description shown on invoices |
| `unit_price` | float | No | Sales price per unit |
| `purchase_desc` | str | No | Purchase description shown on bills |
| `purchase_cost` | float | No | Purchase cost per unit |
| `income_account_ref` | str | Yes (for Service/Inventory) | Income account ID for sales revenue |
| `expense_account_ref` | str | No | Expense account ID for cost of goods/purchases |
| `asset_account_ref` | str | Yes (for Inventory) | Inventory asset account ID |
| `qty_on_hand` | float | Yes (for Inventory) | Initial quantity on hand |
| `inv_start_date` | str | Yes (for Inventory) | Inventory tracking start date (YYYY-MM-DD) |
| `sku` | str | No | SKU/part number |
| `taxable` | bool | No | Whether item is taxable (default true) |
| `active` | bool | No | Whether item is active (default true) |
| `extra_fields` | dict | No | Additional QBO fields |

**Returns:** Created item with Id and SyncToken.
**Endpoint:** `POST /v3/company/{realmId}/item`
**Body:**
```json
{
  "Name": "Landscaping Service",
  "Type": "Service",
  "Description": "Weekly landscaping",
  "UnitPrice": 75.00,
  "IncomeAccountRef": {"value": "1"}
}
```

#### `qb_get_item`
Get an item by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `item_id` | str | Yes | Item ID |

**Returns:** Item object with all fields including QtyOnHand (for inventory items).
**Endpoint:** `GET /v3/company/{realmId}/item/{itemId}?minorversion=75`

#### `qb_update_item`
Update an existing item (sparse update).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `item_id` | str | Yes | Item ID |
| `sync_token` | str | Yes | Current SyncToken |
| `name` | str | No | Updated name |
| `description` | str | No | Updated sales description |
| `unit_price` | float | No | Updated unit price |
| `purchase_desc` | str | No | Updated purchase description |
| `purchase_cost` | float | No | Updated purchase cost |
| `income_account_ref` | str | No | Updated income account ID |
| `expense_account_ref` | str | No | Updated expense account ID |
| `sku` | str | No | Updated SKU |
| `taxable` | bool | No | Updated taxable flag |
| `active` | bool | No | Set false to deactivate (soft delete) |
| `qty_on_hand` | float | No | Updated quantity on hand (inventory items only) |
| `extra_fields` | dict | No | Additional QBO fields |

At least one field besides item_id and sync_token must be provided.
**Returns:** Updated item object.
**Endpoint:** `POST /v3/company/{realmId}/item`
**Body:** `{"Id": "...", "SyncToken": "...", "sparse": true, ...}`

#### `qb_query_items`
Query items using QBO SQL-like query language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `where` | str | No | WHERE clause (e.g., `Name LIKE '%Service%'`, `Type = 'Inventory'`, `Active = true`) |
| `order_by` | str | No | ORDER BY clause (e.g., `Name ASC`) |
| `start_position` | int | No | 1-based start position (default 1) |
| `max_results` | int | No | Max results (default 100, max 1000) |

**Returns:** List of matching items with count.
**Endpoint:** `GET /v3/company/{realmId}/query?query=SELECT * FROM Item WHERE ...&minorversion=75`

---

### Tier 5: Accounts / Chart of Accounts (2 tools)

#### `qb_get_account`
Get an account by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `account_id` | str | Yes | Account ID |

**Returns:** Account object with Name, AccountType, AccountSubType, CurrentBalance, Classification.
**Endpoint:** `GET /v3/company/{realmId}/account/{accountId}?minorversion=75`

#### `qb_query_accounts`
Query accounts (chart of accounts) using QBO SQL-like query language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `where` | str | No | WHERE clause (e.g., `AccountType = 'Income'`, `Classification = 'Asset'`, `Active = true`, `Name LIKE '%Bank%'`) |
| `order_by` | str | No | ORDER BY clause (e.g., `Name ASC`) |
| `start_position` | int | No | 1-based start position (default 1) |
| `max_results` | int | No | Max results (default 100, max 1000) |

**Returns:** List of matching accounts with count.
**Endpoint:** `GET /v3/company/{realmId}/query?query=SELECT * FROM Account WHERE ...&minorversion=75`

**Common AccountType values:** `Bank`, `Accounts Receivable`, `Other Current Asset`, `Fixed Asset`, `Other Asset`, `Accounts Payable`, `Credit Card`, `Other Current Liability`, `Long Term Liability`, `Equity`, `Income`, `Cost of Goods Sold`, `Expense`, `Other Income`, `Other Expense`

**Common Classification values:** `Asset`, `Liability`, `Equity`, `Revenue`, `Expense`

---

### Tier 6: Bills (4 tools)

#### `qb_create_bill`
Create a new bill (payable to a vendor).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `vendor_id` | str | Yes | Vendor ID (VendorRef.value) |
| `line_items` | list[dict] | Yes | Line items array. Each item: `{"DetailType": "AccountBasedExpenseLineDetail", "Amount": 200.00, "AccountBasedExpenseLineDetail": {"AccountRef": {"value": "7"}}}` or `{"DetailType": "ItemBasedExpenseLineDetail", "Amount": 100.00, "ItemBasedExpenseLineDetail": {"ItemRef": {"value": "3"}, "Qty": 2, "UnitPrice": 50.00}}` |
| `txn_date` | str | No | Bill date (YYYY-MM-DD, default today) |
| `due_date` | str | No | Due date (YYYY-MM-DD) |
| `doc_number` | str | No | Bill reference number |
| `ap_account_ref` | str | No | Accounts Payable account ID (defaults to primary AP account) |
| `term_ref` | str | No | Payment terms ID |
| `private_note` | str | No | Internal memo |
| `extra_fields` | dict | No | Additional QBO fields |

**Returns:** Created bill with Id, TotalAmt, Balance.
**Endpoint:** `POST /v3/company/{realmId}/bill`
**Body:**
```json
{
  "VendorRef": {"value": "56"},
  "Line": [
    {
      "DetailType": "AccountBasedExpenseLineDetail",
      "Amount": 200.00,
      "AccountBasedExpenseLineDetail": {
        "AccountRef": {"value": "7"},
        "BillableStatus": "NotBillable"
      }
    }
  ],
  "TxnDate": "2026-04-01",
  "DueDate": "2026-05-01"
}
```

#### `qb_get_bill`
Get a bill by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `bill_id` | str | Yes | Bill ID |

**Returns:** Bill object with all fields including Line items, Balance, SyncToken.
**Endpoint:** `GET /v3/company/{realmId}/bill/{billId}?minorversion=75`

#### `qb_update_bill`
Update an existing bill (sparse update).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `bill_id` | str | Yes | Bill ID |
| `sync_token` | str | Yes | Current SyncToken |
| `vendor_id` | str | No | Updated vendor ID |
| `line_items` | list[dict] | No | Updated line items (replaces all lines when provided) |
| `txn_date` | str | No | Updated bill date |
| `due_date` | str | No | Updated due date |
| `doc_number` | str | No | Updated reference number |
| `private_note` | str | No | Updated memo |
| `extra_fields` | dict | No | Additional QBO fields |

At least one field besides bill_id and sync_token must be provided.
**Returns:** Updated bill object.
**Endpoint:** `POST /v3/company/{realmId}/bill`
**Body:** `{"Id": "...", "SyncToken": "...", "sparse": true, ...}`

#### `qb_query_bills`
Query bills using QBO SQL-like query language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `where` | str | No | WHERE clause (e.g., `VendorRef = '56'`, `Balance > '0'`, `TxnDate >= '2026-01-01'`) |
| `order_by` | str | No | ORDER BY clause (e.g., `DueDate ASC`) |
| `start_position` | int | No | 1-based start position (default 1) |
| `max_results` | int | No | Max results (default 100, max 1000) |

**Returns:** List of matching bills with count.
**Endpoint:** `GET /v3/company/{realmId}/query?query=SELECT * FROM Bill WHERE ...&minorversion=75`

---

### Tier 7: Vendors (4 tools)

#### `qb_create_vendor`
Create a new vendor (supplier).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `display_name` | str | Yes | Vendor display name (must be unique across all name lists) |
| `given_name` | str | No | First name |
| `family_name` | str | No | Last name |
| `company_name` | str | No | Company/business name |
| `email` | str | No | Primary email address |
| `phone` | str | No | Primary phone number |
| `bill_address` | dict | No | Billing address (same format as customer addresses) |
| `tax_identifier` | str | No | Tax ID / EIN |
| `account_number` | str | No | Vendor account number |
| `term_ref` | str | No | Default payment terms ID |
| `vendor_1099` | bool | No | Whether vendor receives 1099 (default false) |
| `notes` | str | No | Notes about the vendor |
| `extra_fields` | dict | No | Additional QBO fields |

**Returns:** Created vendor with Id and SyncToken.
**Endpoint:** `POST /v3/company/{realmId}/vendor`
**Body:**
```json
{
  "DisplayName": "Acme Supplies",
  "CompanyName": "Acme Supplies Inc.",
  "PrimaryEmailAddr": {"Address": "accounts@acme.com"},
  "PrimaryPhone": {"FreeFormNumber": "(555) 123-4567"},
  "Vendor1099": true
}
```

#### `qb_get_vendor`
Get a vendor by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `vendor_id` | str | Yes | Vendor ID |

**Returns:** Vendor object with all fields including Balance and SyncToken.
**Endpoint:** `GET /v3/company/{realmId}/vendor/{vendorId}?minorversion=75`

#### `qb_update_vendor`
Update an existing vendor (sparse update).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `vendor_id` | str | Yes | Vendor ID |
| `sync_token` | str | Yes | Current SyncToken |
| `display_name` | str | No | Updated display name |
| `given_name` | str | No | Updated first name |
| `family_name` | str | No | Updated last name |
| `company_name` | str | No | Updated company name |
| `email` | str | No | Updated email |
| `phone` | str | No | Updated phone |
| `bill_address` | dict | No | Updated billing address |
| `tax_identifier` | str | No | Updated tax ID |
| `vendor_1099` | bool | No | Updated 1099 flag |
| `active` | bool | No | Set false to deactivate (soft delete) |
| `notes` | str | No | Updated notes |
| `extra_fields` | dict | No | Additional QBO fields |

At least one field besides vendor_id and sync_token must be provided.
**Returns:** Updated vendor object.
**Endpoint:** `POST /v3/company/{realmId}/vendor`
**Body:** `{"Id": "...", "SyncToken": "...", "sparse": true, ...}`

#### `qb_query_vendors`
Query vendors using QBO SQL-like query language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `where` | str | No | WHERE clause (e.g., `DisplayName LIKE '%Acme%'`, `Active = true`, `Balance > '0'`) |
| `order_by` | str | No | ORDER BY clause (e.g., `DisplayName ASC`) |
| `start_position` | int | No | 1-based start position (default 1) |
| `max_results` | int | No | Max results (default 100, max 1000) |

**Returns:** List of matching vendors with count.
**Endpoint:** `GET /v3/company/{realmId}/query?query=SELECT * FROM Vendor WHERE ...&minorversion=75`

---

### Tier 8: Estimates / Quotes (5 tools)

#### `qb_create_estimate`
Create a new estimate (quote) for a customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer_id` | str | Yes | Customer ID (CustomerRef.value) |
| `line_items` | list[dict] | Yes | Line items array (same format as invoice line items) |
| `txn_date` | str | No | Estimate date (YYYY-MM-DD, default today) |
| `expiration_date` | str | No | Expiration date (YYYY-MM-DD) |
| `doc_number` | str | No | Custom estimate number |
| `bill_email` | str | No | Email address for sending the estimate |
| `bill_address` | dict | No | Billing address |
| `ship_address` | dict | No | Shipping address |
| `customer_memo` | str | No | Memo visible to customer |
| `private_note` | str | No | Internal note |
| `txn_status` | str | No | Status: `Pending` (default), `Accepted`, `Closed`, `Rejected` |
| `extra_fields` | dict | No | Additional QBO fields |

**Returns:** Created estimate with Id, DocNumber, TotalAmt.
**Endpoint:** `POST /v3/company/{realmId}/estimate`
**Body:**
```json
{
  "CustomerRef": {"value": "1"},
  "Line": [...],
  "TxnDate": "2026-04-01",
  "ExpirationDate": "2026-04-30",
  "TxnStatus": "Pending"
}
```

#### `qb_get_estimate`
Get an estimate by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `estimate_id` | str | Yes | Estimate ID |

**Returns:** Estimate object with all fields including Line items, TotalAmt, TxnStatus, SyncToken.
**Endpoint:** `GET /v3/company/{realmId}/estimate/{estimateId}?minorversion=75`

#### `qb_update_estimate`
Update an existing estimate (sparse update).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `estimate_id` | str | Yes | Estimate ID |
| `sync_token` | str | Yes | Current SyncToken |
| `customer_id` | str | No | Updated customer ID |
| `line_items` | list[dict] | No | Updated line items |
| `txn_date` | str | No | Updated estimate date |
| `expiration_date` | str | No | Updated expiration date |
| `doc_number` | str | No | Updated estimate number |
| `customer_memo` | str | No | Updated customer memo |
| `private_note` | str | No | Updated private note |
| `txn_status` | str | No | Updated status |
| `extra_fields` | dict | No | Additional QBO fields |

At least one field besides estimate_id and sync_token must be provided.
**Returns:** Updated estimate object.
**Endpoint:** `POST /v3/company/{realmId}/estimate`
**Body:** `{"Id": "...", "SyncToken": "...", "sparse": true, ...}`

#### `qb_query_estimates`
Query estimates using QBO SQL-like query language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `where` | str | No | WHERE clause (e.g., `CustomerRef = '123'`, `TxnStatus = 'Pending'`, `TxnDate >= '2026-01-01'`) |
| `order_by` | str | No | ORDER BY clause (e.g., `TxnDate DESC`) |
| `start_position` | int | No | 1-based start position (default 1) |
| `max_results` | int | No | Max results (default 100, max 1000) |

**Returns:** List of matching estimates with count.
**Endpoint:** `GET /v3/company/{realmId}/query?query=SELECT * FROM Estimate WHERE ...&minorversion=75`

#### `qb_send_estimate`
Send an estimate via email to the customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `estimate_id` | str | Yes | Estimate ID to send |
| `email` | str | No | Override email address (defaults to customer's email on file) |

**Returns:** Updated estimate with EmailStatus set to `EmailSent`.
**Endpoint:** `POST /v3/company/{realmId}/estimate/{estimateId}/send?sendTo={email}&minorversion=75`

---

### Tier 9: Credit Memos (3 tools)

#### `qb_create_credit_memo`
Create a credit memo for a customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer_id` | str | Yes | Customer ID (CustomerRef.value) |
| `line_items` | list[dict] | Yes | Line items array (same format as invoice line items) |
| `txn_date` | str | No | Credit memo date (YYYY-MM-DD, default today) |
| `doc_number` | str | No | Custom credit memo number |
| `bill_email` | str | No | Email address |
| `customer_memo` | str | No | Memo visible to customer |
| `private_note` | str | No | Internal note |
| `extra_fields` | dict | No | Additional QBO fields |

**Returns:** Created credit memo with Id, DocNumber, TotalAmt, RemainingCredit.
**Endpoint:** `POST /v3/company/{realmId}/creditmemo`
**Body:**
```json
{
  "CustomerRef": {"value": "1"},
  "Line": [
    {
      "DetailType": "SalesItemLineDetail",
      "Amount": 50.00,
      "SalesItemLineDetail": {
        "ItemRef": {"value": "1"},
        "Qty": 1,
        "UnitPrice": 50.00
      }
    }
  ]
}
```

#### `qb_get_credit_memo`
Get a credit memo by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `credit_memo_id` | str | Yes | Credit Memo ID |

**Returns:** Credit memo object with all fields including RemainingCredit, SyncToken.
**Endpoint:** `GET /v3/company/{realmId}/creditmemo/{creditMemoId}?minorversion=75`

#### `qb_query_credit_memos`
Query credit memos using QBO SQL-like query language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `where` | str | No | WHERE clause (e.g., `CustomerRef = '123'`, `RemainingCredit > '0'`, `TxnDate >= '2026-01-01'`) |
| `order_by` | str | No | ORDER BY clause (e.g., `TxnDate DESC`) |
| `start_position` | int | No | 1-based start position (default 1) |
| `max_results` | int | No | Max results (default 100, max 1000) |

**Returns:** List of matching credit memos with count.
**Endpoint:** `GET /v3/company/{realmId}/query?query=SELECT * FROM CreditMemo WHERE ...&minorversion=75`

---

### Tier 10: Purchases / Expenses (3 tools)

#### `qb_create_purchase`
Create a purchase (expense, check, or credit card charge).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `account_ref` | str | Yes | Bank/credit card account ID (AccountRef.value) the purchase is paid from |
| `payment_type` | str | Yes | Payment type: `Cash`, `Check`, `CreditCard` |
| `line_items` | list[dict] | Yes | Line items array: `{"DetailType": "AccountBasedExpenseLineDetail", "Amount": 100.00, "AccountBasedExpenseLineDetail": {"AccountRef": {"value": "7"}}}` |
| `txn_date` | str | No | Purchase date (YYYY-MM-DD, default today) |
| `entity_ref` | dict | No | Payee reference: `{"value": "vendor_id", "type": "Vendor"}` or `{"value": "customer_id", "type": "Customer"}` |
| `doc_number` | str | No | Reference/check number |
| `private_note` | str | No | Internal memo |
| `department_ref` | str | No | Department/location ID |
| `total_amt` | float | No | Total amount (calculated from lines if omitted) |
| `credit` | bool | No | If true, this is a refund/credit (default false) |
| `extra_fields` | dict | No | Additional QBO fields |

**Returns:** Created purchase with Id, TotalAmt.
**Endpoint:** `POST /v3/company/{realmId}/purchase`
**Body:**
```json
{
  "AccountRef": {"value": "35"},
  "PaymentType": "Cash",
  "Line": [
    {
      "DetailType": "AccountBasedExpenseLineDetail",
      "Amount": 25.00,
      "AccountBasedExpenseLineDetail": {
        "AccountRef": {"value": "7"}
      }
    }
  ],
  "TxnDate": "2026-04-01"
}
```

#### `qb_get_purchase`
Get a purchase by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `purchase_id` | str | Yes | Purchase ID |

**Returns:** Purchase object with all fields including Line items, TotalAmt, SyncToken.
**Endpoint:** `GET /v3/company/{realmId}/purchase/{purchaseId}?minorversion=75`

#### `qb_query_purchases`
Query purchases using QBO SQL-like query language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `where` | str | No | WHERE clause (e.g., `PaymentType = 'CreditCard'`, `TxnDate >= '2026-01-01'`, `TotalAmt > '100'`) |
| `order_by` | str | No | ORDER BY clause (e.g., `TxnDate DESC`) |
| `start_position` | int | No | 1-based start position (default 1) |
| `max_results` | int | No | Max results (default 100, max 1000) |

**Returns:** List of matching purchases with count.
**Endpoint:** `GET /v3/company/{realmId}/query?query=SELECT * FROM Purchase WHERE ...&minorversion=75`

---

### Tier 11: Reports (3 tools)

#### `qb_report_profit_and_loss`
Run a Profit and Loss (Income Statement) report.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `start_date` | str | No | Report start date (YYYY-MM-DD, defaults to fiscal year start) |
| `end_date` | str | No | Report end date (YYYY-MM-DD, defaults to today) |
| `accounting_method` | str | No | `Cash` or `Accrual` (defaults to company preference) |
| `summarize_column_by` | str | No | Column grouping: `Total` (default), `Month`, `Quarter`, `Year`, `Week`, `Days` |
| `customer` | str | No | Filter by customer ID |
| `vendor` | str | No | Filter by vendor ID |
| `department` | str | No | Filter by department/location ID |
| `class_id` | str | No | Filter by class ID |

**Returns:** Report data with Header, Columns, Rows (hierarchical structure with account groups, subtotals, and net income).
**Endpoint:** `GET /v3/company/{realmId}/reports/ProfitAndLoss?start_date={start}&end_date={end}&accounting_method={method}&summarize_column_by={col}&minorversion=75`

**Response structure:**
```json
{
  "Header": {"ReportName": "ProfitAndLoss", "StartPeriod": "...", "EndPeriod": "..."},
  "Columns": {"Column": [{"ColTitle": "Total", "ColType": "Money"}]},
  "Rows": {"Row": [{"group": "Income", "Rows": {"Row": [...]}, "Summary": {"ColData": [...]}}]}
}
```

#### `qb_report_balance_sheet`
Run a Balance Sheet report.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `start_date` | str | No | Report start date (YYYY-MM-DD) |
| `end_date` | str | No | Report end date (YYYY-MM-DD, defaults to today) |
| `accounting_method` | str | No | `Cash` or `Accrual` (defaults to company preference) |
| `summarize_column_by` | str | No | Column grouping: `Total` (default), `Month`, `Quarter`, `Year` |
| `customer` | str | No | Filter by customer ID |
| `department` | str | No | Filter by department/location ID |
| `class_id` | str | No | Filter by class ID |

**Returns:** Report data with Assets, Liabilities, Equity sections and their balances.
**Endpoint:** `GET /v3/company/{realmId}/reports/BalanceSheet?start_date={start}&end_date={end}&accounting_method={method}&summarize_column_by={col}&minorversion=75`

#### `qb_report_accounts_receivable_aging`
Run an Accounts Receivable Aging Summary report.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `report_date` | str | No | Report as-of date (YYYY-MM-DD, defaults to today) |
| `aging_period` | int | No | Number of days per aging period (default 30) |
| `num_periods` | int | No | Number of aging periods to show (default 4; e.g., Current, 1-30, 31-60, 61-90) |
| `customer` | str | No | Filter by customer ID |
| `department` | str | No | Filter by department/location ID |

**Returns:** Aging report with customer rows and aging bucket columns (Current, 1-30, 31-60, 61-90, 91+ days).
**Endpoint:** `GET /v3/company/{realmId}/reports/AgedReceivables?report_date={date}&aging_period={period}&num_periods={num}&minorversion=75`

---

### Tier 12: Company Info (1 tool)

#### `qb_get_company_info`
Get the connected company's information.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| _(none)_ | | | No parameters required |

**Returns:** Company info including CompanyName, LegalName, CompanyAddr, Country, FiscalYearStartMonth, CompanyStartDate, and supported features.
**Endpoint:** `GET /v3/company/{realmId}/companyinfo/{realmId}?minorversion=75`

**Note:** The realmId is used twice in the URL -- once in the base path and once as the entity ID.

---

## Architecture Decisions

### A1: Direct HTTP with httpx (no SDK)
Consistent with HubSpot/ClickUp pattern. Use `httpx` (already a project dependency) for async HTTP calls directly. No dependency on `python-quickbooks` or `intuitlib` packages.

### A2: OAuth 2.0 Token Management
Unlike HubSpot (static Bearer token), QuickBooks requires OAuth 2.0 with token refresh. Implement a token manager class:

```python
import asyncio
import base64
import time

import httpx

class _QBTokenManager:
    """Manages OAuth 2.0 access token with automatic refresh."""
    
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()
    
    async def get_access_token(self) -> str:
        async with self._lock:
            if self._access_token and time.time() < self._expires_at - 60:
                return self._access_token
            return await self._refresh()
    
    async def _refresh(self) -> str:
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                timeout=30.0,
            )
        if resp.status_code != 200:
            raise ToolError(f"QBO token refresh failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        self._access_token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 3600)
        # Rolling refresh token -- update for next refresh
        new_refresh = data.get("refresh_token")
        if new_refresh:
            self._refresh_token = new_refresh
            logger.info("QBO refresh token rotated (in-memory only).")
        return self._access_token
```

**Important:** The refresh token is rolling. Each refresh returns a new refresh token that replaces the old one. The in-memory update is sufficient for session lifetime, but the user should be warned that long-running sessions will have a different refresh token than what is in their config.

### A3: Shared httpx Client with Dynamic Auth
Create a shared `httpx.AsyncClient` with the base URL, but set the Authorization header dynamically on each request (since the access token rotates):

```python
_client: httpx.AsyncClient | None = None
_token_mgr: _QBTokenManager | None = None

def _get_base_url() -> str:
    if QB_ENVIRONMENT == "sandbox":
        return f"https://sandbox-quickbooks.api.intuit.com/v3/company/{QB_REALM_ID}"
    return f"https://quickbooks.api.intuit.com/v3/company/{QB_REALM_ID}"

def _get_client() -> httpx.AsyncClient:
    global _client
    if not all([QB_CLIENT_ID, QB_CLIENT_SECRET, QB_REFRESH_TOKEN, QB_REALM_ID]):
        raise ToolError(
            "QuickBooks not configured. Set QB_CLIENT_ID, QB_CLIENT_SECRET, "
            "QB_REFRESH_TOKEN, and QB_REALM_ID."
        )
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=_get_base_url(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    return _client
```

### A4: Tool Naming Convention
All QuickBooks tools prefixed with `qb_` to distinguish from other integrations. Short prefix chosen because "quickbooks_" would make tool names excessively long.

### A5: SyncToken Pattern
QBO update/delete operations require the current `SyncToken` for optimistic concurrency. Tools that modify entities require `sync_token` as a mandatory parameter. The caller must first GET the entity to obtain its SyncToken. This is a fundamental QBO API requirement that cannot be abstracted away without adding implicit GET calls (which would double API usage).

### A6: Sparse Updates
All update tools use `"sparse": true` in the request body. This allows sending only changed fields without overwriting the entire entity. Without sparse mode, any omitted field would be set to null.

### A7: Query Helper
Create a shared `_query()` helper since all entity queries follow the same pattern (SQL-like SELECT with WHERE, ORDER BY, STARTPOSITION, MAXRESULTS):

```python
async def _query(entity: str, where: str | None, order_by: str | None,
                 start_position: int, max_results: int) -> str:
    query = f"SELECT * FROM {entity}"
    if where:
        query += f" WHERE {where}"
    if order_by:
        query += f" ORDERBY {order_by}"
    query += f" STARTPOSITION {start_position} MAXRESULTS {max_results}"
    data = await _request("GET", "/query", params={"query": query, "minorversion": "75"})
    response = data.get("QueryResponse", {})
    entities = response.get(entity, [])
    count = response.get("totalCount", len(entities))
    return _success(200, data=entities, count=count,
                    start_position=start_position, max_results=max_results)
```

### A8: Error Handling
Same pattern as HubSpot: catch `httpx` exceptions, convert to `ToolError` with human-readable messages. QBO-specific error handling:
- **401 Unauthorized**: Token expired mid-request (retry after refresh)
- **400 Bad Request**: Often `stale object` error (SyncToken mismatch) or validation error
- **429 Rate Limit**: Include `Retry-After` info in error message
- **503 Service Unavailable**: Transient QBO issue, suggest retry

QBO errors return structured JSON:
```json
{
  "Fault": {
    "Error": [{"Message": "...", "Detail": "...", "code": "..."}],
    "type": "ValidationFault"
  }
}
```

### A9: Response Format
Consistent JSON convention: `{"status": "success", ...}` or raised `ToolError` for failures. Same as HubSpot/ClickUp.

### A10: Environment Toggle
Support both sandbox and production environments via `QB_ENVIRONMENT` config variable. Default to `production` if not set. Sandbox base URL differs only in the hostname prefix.

### A11: Minor Version
All requests include `?minorversion=75` (the current base version as of Aug 2025 migration). This ensures consistent field behavior regardless of when the QBO company was created. Check [Intuit minor versions page](https://developer.intuit.com/app/developer/qbo/docs/learn/explore-the-quickbooks-online-api/minor-versions) for updates.

### A12: Missing Config Strategy
Same as HubSpot: register tools regardless, fail at invocation with clear `ToolError` listing which config values are missing.

---

## Configuration Requirements

### Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `QB_CLIENT_ID` | OAuth 2.0 Client ID from Intuit Developer portal | Yes (at invocation) | `None` |
| `QB_CLIENT_SECRET` | OAuth 2.0 Client Secret from Intuit Developer portal | Yes (at invocation) | `None` |
| `QB_REFRESH_TOKEN` | Pre-obtained OAuth 2.0 refresh token | Yes (at invocation) | `None` |
| `QB_REALM_ID` | QuickBooks company ID (also called realm ID or company ID) | Yes (at invocation) | `None` |
| `QB_ENVIRONMENT` | `sandbox` or `production` | No | `production` |

### Config Pattern
```python
QB_CLIENT_ID: str | None = os.getenv("QB_CLIENT_ID")
QB_CLIENT_SECRET: str | None = os.getenv("QB_CLIENT_SECRET")
QB_REFRESH_TOKEN: str | None = os.getenv("QB_REFRESH_TOKEN")
QB_REALM_ID: str | None = os.getenv("QB_REALM_ID")
QB_ENVIRONMENT: str = os.getenv("QB_ENVIRONMENT", "production")
```

### Obtaining a Refresh Token
To get the initial refresh token for daemon use:
1. Create an app at [developer.intuit.com](https://developer.intuit.com)
2. Set redirect URI (e.g., `https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl`)
3. Use the OAuth 2.0 Playground to complete the authorization code flow
4. Copy the refresh token from the playground response
5. Store it in `QB_REFRESH_TOKEN`

The refresh token is valid for 100 days (rolling) but has a 5-year maximum lifetime from generation. The tool manages rotation in-memory during the session.

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/config.py` | Modify | Add `QB_CLIENT_ID`, `QB_CLIENT_SECRET`, `QB_REFRESH_TOKEN`, `QB_REALM_ID`, `QB_ENVIRONMENT` |
| `.env.example` | Modify | Add all QB_ variables |
| `src/mcp_toolbox/tools/quickbooks_tool.py` | **New** | All QuickBooks tools (~46 tools) + token manager |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register quickbooks_tool |
| `tests/test_quickbooks_tool.py` | **New** | Tests for all QuickBooks tools |
| `CLAUDE.md` | Modify | Document QuickBooks Online integration |

---

## Testing Strategy

### Approach
Use `pytest` with `respx` (already used for HubSpot/ClickUp tests) for mocking HTTP calls. Mock both the token refresh endpoint and the QBO API endpoints.

```python
import respx
import httpx

@respx.mock
async def test_create_customer():
    # Mock token refresh
    respx.post("https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer").mock(
        return_value=httpx.Response(200, json={
            "access_token": "test_token",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
            "token_type": "bearer"
        })
    )
    # Mock QBO API
    respx.post(
        url__startswith="https://sandbox-quickbooks.api.intuit.com/v3/company/"
    ).mock(
        return_value=httpx.Response(200, json={
            "Customer": {
                "Id": "123",
                "SyncToken": "0",
                "DisplayName": "Test Customer",
                "MetaData": {"CreateTime": "2026-04-01T00:00:00Z"}
            }
        })
    )
    result = await server.call_tool("qb_create_customer", {
        "display_name": "Test Customer"
    })
    assert "success" in result
```

### Test Coverage
1. Happy path for every tool (46 tests minimum)
2. Missing config variables -> ToolError with list of missing vars
3. Token refresh flow (initial, expired, rotation)
4. Token refresh failure (invalid refresh token, network error)
5. API errors (400 validation, 401 unauthorized, 404 not found, 429 rate limit, 503 unavailable)
6. SyncToken stale object error
7. Sparse update field filtering
8. Query builder with various WHERE/ORDER BY combinations
9. Void vs delete operations
10. Send invoice/estimate email
11. Report parameter combinations
12. Sandbox vs production URL selection
13. Line items construction for invoices, bills, estimates, credit memos, purchases

---

## Dependencies

| Package | Purpose | Already in project? |
|---------|---------|-------------------|
| `httpx` | Async HTTP client | Yes |
| `respx` | httpx mock library (dev) | Yes |

No new dependencies required.

---

## Success Criteria

1. `uv sync` installs without errors (no new runtime deps needed)
2. All 46 QuickBooks tools register and are discoverable via MCP Inspector
3. OAuth 2.0 token refresh works transparently (no manual token management by caller)
4. Tools return meaningful errors when config is missing
5. All tools return consistent JSON responses (`{"status": "success", ...}`)
6. SyncToken concurrency is enforced (update/delete tools require sync_token)
7. New tests pass and full regression suite remains green
8. Config handles missing values gracefully (tools register, fail at invocation)
9. Total tool count reaches **384** (current 338 + 46 new QuickBooks tools)

---

## Scope Decision

**All 12 tiers (46 tools)** -- full accounting integration covering customers, invoices, payments, items, accounts, bills, vendors, estimates, credit memos, purchases, reports, and company info.

---

## Tool Summary (46 tools total)

### Tier 1 -- Customers (5 tools)
1. `qb_create_customer` -- Create a customer with name, email, phone, address
2. `qb_get_customer` -- Get customer by ID with all fields
3. `qb_update_customer` -- Sparse update customer properties (requires SyncToken)
4. `qb_query_customers` -- Query customers with SQL-like WHERE clause and pagination
5. `qb_delete_customer` -- Deactivate a customer (soft delete via Active=false)

### Tier 2 -- Invoices (7 tools)
6. `qb_create_invoice` -- Create an invoice with line items for a customer
7. `qb_get_invoice` -- Get invoice by ID with all fields
8. `qb_update_invoice` -- Sparse update invoice (requires SyncToken)
9. `qb_query_invoices` -- Query invoices with SQL-like WHERE clause and pagination
10. `qb_send_invoice` -- Send invoice via email to the customer
11. `qb_void_invoice` -- Void invoice (zero out amounts, keep for audit trail)
12. `qb_delete_invoice` -- Permanently delete an invoice

### Tier 3 -- Payments (5 tools)
13. `qb_create_payment` -- Record a customer payment with optional invoice linking
14. `qb_get_payment` -- Get payment by ID with all fields
15. `qb_query_payments` -- Query payments with SQL-like WHERE clause and pagination
16. `qb_void_payment` -- Void a payment (reverse but keep for audit)
17. `qb_delete_payment` -- Permanently delete a payment

### Tier 4 -- Items / Products & Services (4 tools)
18. `qb_create_item` -- Create a product or service item
19. `qb_get_item` -- Get item by ID with all fields
20. `qb_update_item` -- Sparse update item properties (requires SyncToken)
21. `qb_query_items` -- Query items with SQL-like WHERE clause and pagination

### Tier 5 -- Accounts / Chart of Accounts (2 tools)
22. `qb_get_account` -- Get account by ID with all fields
23. `qb_query_accounts` -- Query chart of accounts with SQL-like WHERE clause and pagination

### Tier 6 -- Bills (4 tools)
24. `qb_create_bill` -- Create a bill payable to a vendor with line items
25. `qb_get_bill` -- Get bill by ID with all fields
26. `qb_update_bill` -- Sparse update bill (requires SyncToken)
27. `qb_query_bills` -- Query bills with SQL-like WHERE clause and pagination

### Tier 7 -- Vendors (4 tools)
28. `qb_create_vendor` -- Create a vendor/supplier
29. `qb_get_vendor` -- Get vendor by ID with all fields
30. `qb_update_vendor` -- Sparse update vendor properties (requires SyncToken)
31. `qb_query_vendors` -- Query vendors with SQL-like WHERE clause and pagination

### Tier 8 -- Estimates / Quotes (5 tools)
32. `qb_create_estimate` -- Create an estimate/quote for a customer with line items
33. `qb_get_estimate` -- Get estimate by ID with all fields
34. `qb_update_estimate` -- Sparse update estimate (requires SyncToken)
35. `qb_query_estimates` -- Query estimates with SQL-like WHERE clause and pagination
36. `qb_send_estimate` -- Send estimate via email to the customer

### Tier 9 -- Credit Memos (3 tools)
37. `qb_create_credit_memo` -- Create a credit memo for a customer
38. `qb_get_credit_memo` -- Get credit memo by ID with all fields
39. `qb_query_credit_memos` -- Query credit memos with SQL-like WHERE clause and pagination

### Tier 10 -- Purchases / Expenses (3 tools)
40. `qb_create_purchase` -- Create a purchase/expense (cash, check, or credit card)
41. `qb_get_purchase` -- Get purchase by ID with all fields
42. `qb_query_purchases` -- Query purchases with SQL-like WHERE clause and pagination

### Tier 11 -- Reports (3 tools)
43. `qb_report_profit_and_loss` -- Run Profit & Loss report with date range and filters
44. `qb_report_balance_sheet` -- Run Balance Sheet report with date range and filters
45. `qb_report_accounts_receivable_aging` -- Run AR Aging Summary report with aging periods

### Tier 12 -- Company Info (1 tool)
46. `qb_get_company_info` -- Get connected company information (name, address, fiscal year, etc.)
