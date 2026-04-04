# Task 17: Stripe Payment Integration - Analysis & Requirements

## Objective
Add Stripe as a tool integration in mcp-toolbox, exposing payment processing capabilities (customers, payment intents, charges, invoices, subscriptions, products, prices, payment methods, refunds, balance, payouts, coupons, promotion codes, events, webhooks) as MCP tools for LLM clients.

---

## API Technical Details

### Stripe REST API v1
- **Base URL:** `https://api.stripe.com/v1`
- **Auth:** Secret API key via `Authorization: Bearer sk_test_xxx` or `Authorization: Bearer sk_live_xxx` header
- **Request Format:** `application/x-www-form-urlencoded` (form encoding, NOT JSON)
- **Response Format:** JSON
- **API Version:** Set via `Stripe-Version` header (optional; defaults to account's pinned version)

### CRITICAL: Form-Encoded Request Bodies
Unlike most modern APIs, Stripe uses `application/x-www-form-urlencoded` for all POST/PUT/PATCH request bodies. Nested objects use bracket notation:

```
# Flat params
name=John+Doe&email=john%40example.com

# Nested objects
address[line1]=123+Main+St&address[city]=San+Francisco&address[state]=CA

# Arrays
items[0][price]=price_xxx&items[0][quantity]=1&items[1][price]=price_yyy&items[1][quantity]=2

# Metadata
metadata[order_id]=12345&metadata[source]=mcp
```

**httpx handles this automatically** with the `data=` parameter (not `json=`):
```python
response = await client.request("POST", "/v1/customers", data={"name": "John", "email": "john@example.com"})
```

For nested objects, httpx requires pre-flattened keys or use of `httpx`'s built-in form encoding with bracket notation in key names:
```python
data = {
    "name": "John",
    "address[line1]": "123 Main St",
    "address[city]": "San Francisco",
    "metadata[order_id]": "12345",
}
```

### Rate Limits

| Mode | Default Limit | Notes |
|------|--------------|-------|
| All endpoints (default) | 25/sec | Stripe may increase for specific accounts based on usage |
| Search endpoints | 20/sec | Lower limit for search operations |
| Files API | 20/sec read, 20/sec write | Separate read/write limits |
| Create Payout API | 15/sec | 30 concurrent requests per business |

- HTTP 429 on rate limit exceeded
- Rate limit headers: `Stripe-RateLimit-Limit`, `Stripe-RateLimit-Remaining`, `Stripe-RateLimit-Reset`
- Per-API-key limits
- Payment Intents: 1000 update operations per PaymentIntent per hour

### No Official Python SDK Needed
Stripe offers `stripe` Python package but it adds unnecessary complexity and is synchronous by default. **Recommendation:** Use `httpx` (already in our dependencies) for direct async HTTP calls -- consistent with HubSpot pattern, simpler, full async control. Stripe's REST API is straightforward with form encoding.

### Key Quirks
- **Form-encoded bodies** -- all mutating requests use `application/x-www-form-urlencoded`, NOT JSON
- **Nested params use bracket notation** -- e.g., `address[city]=SF`, `metadata[key]=value`
- **Array params use indexed brackets** -- e.g., `items[0][price]=price_xxx`
- **Amounts in smallest currency unit** -- cents for USD (e.g., `$10.00` = `1000`), yen for JPY (e.g., `1000` = 1000 JPY)
- **Idempotency** -- POST requests accept `Idempotency-Key` header for safe retries
- **Expandable objects** -- use `expand[]` param to inline related objects (e.g., `expand[]=customer`)
- **Pagination via `starting_after` / `ending_before`** -- cursor-based using object IDs, not page numbers
- **List responses** -- wrapped in `{"object": "list", "data": [...], "has_more": bool, "url": "..."}`
- **Deletion returns** -- `{"id": "xxx", "object": "xxx", "deleted": true}`
- **Test mode vs. live mode** -- determined by API key prefix (`sk_test_` vs. `sk_live_`)
- **Metadata on most objects** -- arbitrary key-value pairs (up to 50 keys, 500 char values)
- **Timestamps in Unix epoch** -- integer seconds since epoch, NOT ISO 8601
- **Currency codes lowercase** -- e.g., `usd`, `eur`, `gbp`
- **Search uses GET with query string** -- unlike HubSpot, search endpoints use `GET` with a `query` parameter containing a Stripe search query language string

---

## Stripe Object Model

```
Customers -----> Payment Methods
    |                 |
    v                 v
Subscriptions   Payment Intents ---> Charges
    |                 |
    v                 v
Invoices          Refunds
    |
    v
Invoice Items / Line Items

Products ---> Prices ---> Subscriptions / Invoice Items

Coupons ---> Promotion Codes ---> Subscriptions / Invoices

Balance ---> Balance Transactions ---> Payouts

Events (webhook log of all changes)
Webhook Endpoints (delivery configuration)
```

### Core Object Relationships
| Object | Description | Key Relationships |
|--------|-------------|-------------------|
| Customer | Person or business | Has payment methods, subscriptions, invoices |
| Payment Intent | Tracks a payment lifecycle | Links to customer, payment method, charges |
| Charge | Single payment attempt | Created by payment intent or directly |
| Invoice | Bill for a customer | Contains line items, linked to subscription |
| Invoice Item | Pending item before invoice finalization | Added to next invoice |
| Subscription | Recurring billing | Links to customer, prices, invoices |
| Product | Good or service for sale | Has one or more prices |
| Price | How much and how often to charge | Links to product |
| Payment Method | Card, bank account, etc. | Attached to customer |
| Refund | Reversal of a charge | Links to charge or payment intent |
| Balance | Account funds | Balance transactions record movements |
| Payout | Transfer to bank account | From Stripe balance |
| Coupon | Discount definition | Applied via promotion codes |
| Promotion Code | Customer-facing code for coupon | Links to coupon |
| Event | API event log entry | Records all object changes |
| Webhook Endpoint | URL to receive events | Configured event types |

---

## Tool Specifications

### Tier 1: Customers (6 tools)

#### `stripe_create_customer`
Create a new customer in Stripe.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | str | No | Customer email address |
| `name` | str | No | Customer full name |
| `phone` | str | No | Customer phone number |
| `description` | str | No | Arbitrary description |
| `address_line1` | str | No | Address line 1 |
| `address_line2` | str | No | Address line 2 |
| `address_city` | str | No | City |
| `address_state` | str | No | State/province |
| `address_postal_code` | str | No | ZIP/postal code |
| `address_country` | str | No | Two-letter country code (e.g., `US`) |
| `payment_method` | str | No | Default payment method ID to attach |
| `metadata` | dict | No | Arbitrary key-value metadata (up to 50 keys) |

**Returns:** Created customer object with ID.
**Endpoint:** `POST /v1/customers`
**Body (form-encoded):** `email=john%40example.com&name=John+Doe&address[line1]=123+Main&metadata[source]=mcp`

#### `stripe_get_customer`
Retrieve a customer by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer_id` | str | Yes | Customer ID (e.g., `cus_xxx`) |
| `expand` | list[str] | No | Related objects to expand inline (e.g., `["default_source", "subscriptions"]`) |

**Returns:** Customer object with all properties.
**Endpoint:** `GET /v1/customers/{customer_id}`

#### `stripe_update_customer`
Update an existing customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer_id` | str | Yes | Customer ID |
| `email` | str | No | Updated email |
| `name` | str | No | Updated name |
| `phone` | str | No | Updated phone |
| `description` | str | No | Updated description |
| `address_line1` | str | No | Updated address line 1 |
| `address_line2` | str | No | Updated address line 2 |
| `address_city` | str | No | Updated city |
| `address_state` | str | No | Updated state |
| `address_postal_code` | str | No | Updated postal code |
| `address_country` | str | No | Updated country |
| `default_payment_method` | str | No | Default payment method ID |
| `metadata` | dict | No | Updated metadata (merges with existing; set key to empty string to remove) |

At least one property must be provided.
**Returns:** Updated customer object.
**Endpoint:** `POST /v1/customers/{customer_id}`

#### `stripe_delete_customer`
Permanently delete a customer and cancel active subscriptions.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer_id` | str | Yes | Customer ID to delete |

**Returns:** Deletion confirmation with `{"id": "cus_xxx", "deleted": true}`.
**Endpoint:** `DELETE /v1/customers/{customer_id}`

#### `stripe_list_customers`
List customers with pagination.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: customer ID to start after |
| `ending_before` | str | No | Cursor: customer ID to end before |
| `email` | str | No | Filter by exact email address |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |

**Returns:** List object with `data` array and `has_more` boolean.
**Endpoint:** `GET /v1/customers?limit={limit}&starting_after={cursor}&email={email}`

#### `stripe_search_customers`
Search customers using Stripe's search query language.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | Yes | Search query string (e.g., `email:"john@example.com"` or `name~"John"` or `metadata["key"]:"value"`) |
| `limit` | int | No | Number of results (default 10, max 100) |
| `page` | str | No | Pagination cursor from `next_page` in previous response |

**Search query syntax:** `field:value`, `field~"partial"`, `-field:value` (negation), `AND`/`OR` operators.
**Searchable fields:** `email`, `name`, `phone`, `metadata`, `created`.
**Returns:** Search result with `data` array, `has_more`, `next_page`.
**Endpoint:** `GET /v1/customers/search?query={query}&limit={limit}`

---

### Tier 2: Payment Intents (6 tools)

#### `stripe_create_payment_intent`
Create a payment intent to track a payment lifecycle.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `amount` | int | Yes | Amount in smallest currency unit (e.g., cents). `1000` = $10.00 |
| `currency` | str | Yes | Three-letter ISO currency code, lowercase (e.g., `usd`, `eur`) |
| `customer` | str | No | Customer ID to associate |
| `payment_method` | str | No | Payment method ID |
| `description` | str | No | Description for the payment |
| `receipt_email` | str | No | Email to send receipt to |
| `confirm` | bool | No | If `true`, confirm the intent immediately (default `false`) |
| `automatic_payment_methods` | bool | No | Enable automatic payment methods (default `true` for new intents) |
| `payment_method_types` | list[str] | No | Allowed payment method types (e.g., `["card", "us_bank_account"]`) |
| `setup_future_usage` | str | No | `off_session` or `on_session` -- save payment method for future use |
| `capture_method` | str | No | `automatic` (default) or `manual` for auth-only then capture later |
| `statement_descriptor` | str | No | Text on customer's statement (max 22 chars) |
| `metadata` | dict | No | Arbitrary key-value metadata |
| `return_url` | str | No | URL to redirect to after payment confirmation (required for some payment methods) |

**Returns:** Payment intent object with `id`, `status`, `client_secret`.
**Endpoint:** `POST /v1/payment_intents`
**Body (form-encoded):** `amount=1000&currency=usd&customer=cus_xxx&metadata[order_id]=123`

#### `stripe_get_payment_intent`
Retrieve a payment intent by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `payment_intent_id` | str | Yes | Payment Intent ID (e.g., `pi_xxx`) |
| `expand` | list[str] | No | Objects to expand (e.g., `["customer", "latest_charge"]`) |

**Returns:** Payment intent object with full details.
**Endpoint:** `GET /v1/payment_intents/{payment_intent_id}`

#### `stripe_update_payment_intent`
Update a payment intent before confirmation.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `payment_intent_id` | str | Yes | Payment Intent ID |
| `amount` | int | No | Updated amount |
| `currency` | str | No | Updated currency |
| `customer` | str | No | Updated customer ID |
| `description` | str | No | Updated description |
| `payment_method` | str | No | Updated payment method ID |
| `receipt_email` | str | No | Updated receipt email |
| `statement_descriptor` | str | No | Updated statement descriptor |
| `metadata` | dict | No | Updated metadata |
| `setup_future_usage` | str | No | Updated future usage setting (`""` to clear) |

At least one property must be provided.
**Returns:** Updated payment intent object.
**Endpoint:** `POST /v1/payment_intents/{payment_intent_id}`

#### `stripe_confirm_payment_intent`
Confirm a payment intent to initiate payment processing.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `payment_intent_id` | str | Yes | Payment Intent ID to confirm |
| `payment_method` | str | No | Payment method to use (overrides existing) |
| `return_url` | str | No | URL for redirect-based payment methods |

**Returns:** Confirmed payment intent with updated `status`.
**Endpoint:** `POST /v1/payment_intents/{payment_intent_id}/confirm`

#### `stripe_cancel_payment_intent`
Cancel a payment intent (only if not already succeeded).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `payment_intent_id` | str | Yes | Payment Intent ID to cancel |
| `cancellation_reason` | str | No | Reason: `duplicate`, `fraudulent`, `requested_by_customer`, `abandoned` |

**Returns:** Canceled payment intent with `status: "canceled"`.
**Endpoint:** `POST /v1/payment_intents/{payment_intent_id}/cancel`

#### `stripe_list_payment_intents`
List payment intents with pagination and filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: payment intent ID to start after |
| `ending_before` | str | No | Cursor: payment intent ID to end before |
| `customer` | str | No | Filter by customer ID |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/payment_intents?limit={limit}&customer={customer}`

---

### Tier 3: Charges (5 tools)

#### `stripe_create_charge`
Create a charge directly (legacy approach; prefer Payment Intents for new integrations).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `amount` | int | Yes | Amount in smallest currency unit |
| `currency` | str | Yes | Three-letter currency code (e.g., `usd`) |
| `customer` | str | No | Customer ID (required if no `source`) |
| `source` | str | No | Payment source token or ID |
| `description` | str | No | Charge description |
| `receipt_email` | str | No | Email for receipt |
| `capture` | bool | No | Whether to capture immediately (default `true`; set `false` for auth-only) |
| `statement_descriptor` | str | No | Statement text (max 22 chars) |
| `metadata` | dict | No | Arbitrary metadata |

**Returns:** Charge object with `id`, `status`, `paid`, `amount`.
**Endpoint:** `POST /v1/charges`

#### `stripe_get_charge`
Retrieve a charge by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `charge_id` | str | Yes | Charge ID (e.g., `ch_xxx`) |
| `expand` | list[str] | No | Objects to expand (e.g., `["customer", "balance_transaction"]`) |

**Returns:** Charge object with full details.
**Endpoint:** `GET /v1/charges/{charge_id}`

#### `stripe_update_charge`
Update a charge (description, metadata, fraud details, etc.).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `charge_id` | str | Yes | Charge ID |
| `description` | str | No | Updated description |
| `receipt_email` | str | No | Updated receipt email |
| `metadata` | dict | No | Updated metadata |
| `fraud_details_user_report` | str | No | Report fraud: `fraudulent` or `safe` |

At least one property must be provided.
**Returns:** Updated charge object.
**Endpoint:** `POST /v1/charges/{charge_id}`

#### `stripe_list_charges`
List charges with pagination and filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: charge ID to start after |
| `ending_before` | str | No | Cursor: charge ID to end before |
| `customer` | str | No | Filter by customer ID |
| `payment_intent` | str | No | Filter by payment intent ID |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/charges?limit={limit}&customer={customer}`

#### `stripe_capture_charge`
Capture a previously authorized (uncaptured) charge.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `charge_id` | str | Yes | Charge ID to capture |
| `amount` | int | No | Amount to capture (partial capture; defaults to full authorized amount) |
| `receipt_email` | str | No | Email for receipt |
| `statement_descriptor` | str | No | Statement descriptor override |

**Returns:** Captured charge object with `captured: true`.
**Endpoint:** `POST /v1/charges/{charge_id}/capture`

---

### Tier 4: Invoices (10 tools)

#### `stripe_create_invoice`
Create a draft invoice for a customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer` | str | Yes | Customer ID |
| `auto_advance` | bool | No | Whether to auto-finalize and send (default `true`) |
| `collection_method` | str | No | `charge_automatically` (default) or `send_invoice` |
| `days_until_due` | int | No | Number of days until invoice is due (for `send_invoice` collection) |
| `description` | str | No | Invoice memo/description |
| `currency` | str | No | Currency code (defaults to customer's currency) |
| `subscription` | str | No | Subscription ID to invoice |
| `pending_invoice_items_behavior` | str | No | `include` (default) or `exclude` pending invoice items |
| `metadata` | dict | No | Arbitrary metadata |

**Returns:** Draft invoice object with `id`, `status: "draft"`.
**Endpoint:** `POST /v1/invoices`
**Body (form-encoded):** `customer=cus_xxx&collection_method=send_invoice&days_until_due=30`

#### `stripe_get_invoice`
Retrieve an invoice by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID (e.g., `in_xxx`) |
| `expand` | list[str] | No | Objects to expand (e.g., `["customer", "subscription", "charge"]`) |

**Returns:** Invoice object with full details.
**Endpoint:** `GET /v1/invoices/{invoice_id}`

#### `stripe_update_invoice`
Update a draft or open invoice.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID |
| `description` | str | No | Updated description |
| `auto_advance` | bool | No | Updated auto-advance setting |
| `collection_method` | str | No | Updated collection method |
| `days_until_due` | int | No | Updated days until due |
| `default_payment_method` | str | No | Default payment method ID |
| `metadata` | dict | No | Updated metadata |

At least one property must be provided.
**Returns:** Updated invoice object.
**Endpoint:** `POST /v1/invoices/{invoice_id}`

#### `stripe_finalize_invoice`
Finalize a draft invoice, transitioning it to `open` status ready for payment.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID to finalize |
| `auto_advance` | bool | No | Whether to auto-send/charge after finalization |

**Returns:** Finalized invoice with `status: "open"`.
**Endpoint:** `POST /v1/invoices/{invoice_id}/finalize`

#### `stripe_pay_invoice`
Pay an open invoice using the customer's default payment method or a specified one.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID to pay |
| `payment_method` | str | No | Payment method ID to use (overrides default) |
| `source` | str | No | Source ID to use (legacy) |

**Returns:** Paid invoice with `status: "paid"`.
**Endpoint:** `POST /v1/invoices/{invoice_id}/pay`

#### `stripe_void_invoice`
Void an open invoice (marks it as uncollectible without attempting payment).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID to void |

**Returns:** Voided invoice with `status: "void"`.
**Endpoint:** `POST /v1/invoices/{invoice_id}/void`

#### `stripe_send_invoice`
Send a finalized invoice to the customer via email.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID to send (must be `open` status with `collection_method: "send_invoice"`) |

**Returns:** Sent invoice object.
**Endpoint:** `POST /v1/invoices/{invoice_id}/send`

#### `stripe_list_invoices`
List invoices with pagination and filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: invoice ID to start after |
| `ending_before` | str | No | Cursor: invoice ID to end before |
| `customer` | str | No | Filter by customer ID |
| `subscription` | str | No | Filter by subscription ID |
| `status` | str | No | Filter by status: `draft`, `open`, `paid`, `uncollectible`, `void` |
| `collection_method` | str | No | Filter by `charge_automatically` or `send_invoice` |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |
| `due_date_gte` | int | No | Filter: due at or after (Unix timestamp) |
| `due_date_lte` | int | No | Filter: due at or before (Unix timestamp) |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/invoices?limit={limit}&customer={customer}&status={status}`

#### `stripe_list_invoice_line_items`
List line items for a specific invoice.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID |
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: line item ID to start after |
| `ending_before` | str | No | Cursor: line item ID to end before |

**Returns:** List of line items with amounts, descriptions, prices.
**Endpoint:** `GET /v1/invoices/{invoice_id}/lines`

#### `stripe_add_invoice_line_item`
Add a line item to a draft invoice.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_id` | str | Yes | Invoice ID (must be `draft` status) |
| `price` | str | No | Price ID for a recurring or one-time price |
| `quantity` | int | No | Quantity (default 1) |
| `amount` | int | No | Amount in smallest currency unit (use instead of `price` for ad-hoc items) |
| `currency` | str | No | Currency (required with `amount`) |
| `description` | str | No | Line item description |
| `metadata` | dict | No | Metadata |

One of `price` or `amount` must be provided.
**Returns:** Updated invoice object or the line item added.
**Endpoint:** `POST /v1/invoices/{invoice_id}/add_lines`
**Body (form-encoded):** `lines[0][price]=price_xxx&lines[0][quantity]=1` or `lines[0][amount]=5000&lines[0][currency]=usd&lines[0][description]=Consulting`

---

### Tier 5: Invoice Items (5 tools)

#### `stripe_create_invoice_item`
Create an invoice item to be added to the customer's next invoice.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer` | str | Yes | Customer ID |
| `amount` | int | No | Amount in smallest currency unit (use instead of `price`) |
| `currency` | str | No | Currency code (required with `amount`) |
| `price` | str | No | Price ID (alternative to `amount`) |
| `quantity` | int | No | Quantity (default 1, used with `price`) |
| `description` | str | No | Description |
| `invoice` | str | No | Invoice ID to add to (if omitted, added to next upcoming invoice) |
| `subscription` | str | No | Subscription ID to tie item to |
| `discountable` | bool | No | Whether discounts apply (default `true`) |
| `metadata` | dict | No | Arbitrary metadata |

**Returns:** Invoice item object with `id`.
**Endpoint:** `POST /v1/invoiceitems`

#### `stripe_get_invoice_item`
Retrieve an invoice item by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_item_id` | str | Yes | Invoice item ID (e.g., `ii_xxx`) |

**Returns:** Invoice item object.
**Endpoint:** `GET /v1/invoiceitems/{invoice_item_id}`

#### `stripe_update_invoice_item`
Update an invoice item (only before invoice is finalized).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_item_id` | str | Yes | Invoice item ID |
| `amount` | int | No | Updated amount |
| `description` | str | No | Updated description |
| `quantity` | int | No | Updated quantity |
| `price` | str | No | Updated price ID |
| `discountable` | bool | No | Updated discountable flag |
| `metadata` | dict | No | Updated metadata |

At least one property must be provided.
**Returns:** Updated invoice item object.
**Endpoint:** `POST /v1/invoiceitems/{invoice_item_id}`

#### `stripe_delete_invoice_item`
Delete an invoice item (only if invoice is still draft or item is pending).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `invoice_item_id` | str | Yes | Invoice item ID to delete |

**Returns:** Deletion confirmation with `{"id": "ii_xxx", "deleted": true}`.
**Endpoint:** `DELETE /v1/invoiceitems/{invoice_item_id}`

#### `stripe_list_invoice_items`
List invoice items with pagination and filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: invoice item ID to start after |
| `ending_before` | str | No | Cursor: invoice item ID to end before |
| `customer` | str | No | Filter by customer ID |
| `invoice` | str | No | Filter by invoice ID |
| `pending` | bool | No | Filter for only pending items (not yet attached to an invoice) |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/invoiceitems?limit={limit}&customer={customer}`

---

### Tier 6: Subscriptions (6 tools)

#### `stripe_create_subscription`
Create a subscription for a customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer` | str | Yes | Customer ID |
| `items` | list[dict] | Yes | Subscription items: `[{"price": "price_xxx", "quantity": 1}]` |
| `default_payment_method` | str | No | Payment method ID |
| `cancel_at_period_end` | bool | No | Whether to cancel at period end (default `false`) |
| `trial_period_days` | int | No | Number of trial days |
| `trial_end` | int | No | Unix timestamp for trial end (alternative to `trial_period_days`; use `"now"` to end trial immediately) |
| `billing_cycle_anchor` | int | No | Unix timestamp to anchor billing cycle |
| `proration_behavior` | str | No | `create_prorations` (default), `none`, `always_invoice` |
| `coupon` | str | No | Coupon ID to apply |
| `promotion_code` | str | No | Promotion code ID to apply |
| `collection_method` | str | No | `charge_automatically` (default) or `send_invoice` |
| `days_until_due` | int | No | Days until due (for `send_invoice`) |
| `metadata` | dict | No | Arbitrary metadata |

**Returns:** Subscription object with `id`, `status`, `current_period_start`, `current_period_end`.
**Endpoint:** `POST /v1/subscriptions`
**Body (form-encoded):** `customer=cus_xxx&items[0][price]=price_xxx&items[0][quantity]=1&trial_period_days=14`

#### `stripe_get_subscription`
Retrieve a subscription by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subscription_id` | str | Yes | Subscription ID (e.g., `sub_xxx`) |
| `expand` | list[str] | No | Objects to expand (e.g., `["customer", "latest_invoice", "default_payment_method"]`) |

**Returns:** Subscription object with full details.
**Endpoint:** `GET /v1/subscriptions/{subscription_id}`

#### `stripe_update_subscription`
Update an existing subscription.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subscription_id` | str | Yes | Subscription ID |
| `items` | list[dict] | No | Updated items (include `id` for existing items): `[{"id": "si_xxx", "price": "price_yyy"}]` |
| `default_payment_method` | str | No | Updated default payment method |
| `cancel_at_period_end` | bool | No | Updated cancel-at-period-end flag |
| `proration_behavior` | str | No | Proration behavior for this update |
| `trial_end` | int | No | Updated trial end (Unix timestamp or `"now"`) |
| `coupon` | str | No | Coupon ID to apply (empty string to remove) |
| `promotion_code` | str | No | Promotion code ID to apply |
| `collection_method` | str | No | Updated collection method |
| `days_until_due` | int | No | Updated days until due |
| `metadata` | dict | No | Updated metadata |

At least one property must be provided.
**Returns:** Updated subscription object.
**Endpoint:** `POST /v1/subscriptions/{subscription_id}`

#### `stripe_cancel_subscription`
Cancel an active subscription.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subscription_id` | str | Yes | Subscription ID to cancel |
| `invoice_now` | bool | No | Generate a final invoice immediately (default `false`) |
| `prorate` | bool | No | Prorate the final invoice (default `false`) |
| `cancellation_details_comment` | str | No | Reason for cancellation |

**Returns:** Canceled subscription with `status: "canceled"`.
**Endpoint:** `DELETE /v1/subscriptions/{subscription_id}`

#### `stripe_list_subscriptions`
List subscriptions with pagination and filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: subscription ID to start after |
| `ending_before` | str | No | Cursor: subscription ID to end before |
| `customer` | str | No | Filter by customer ID |
| `price` | str | No | Filter by price ID |
| `status` | str | No | Filter: `active`, `past_due`, `unpaid`, `canceled`, `incomplete`, `incomplete_expired`, `trialing`, `all` |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |
| `current_period_start_gte` | int | No | Filter: current period started at or after |
| `current_period_start_lte` | int | No | Filter: current period started at or before |
| `current_period_end_gte` | int | No | Filter: current period ends at or after |
| `current_period_end_lte` | int | No | Filter: current period ends at or before |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/subscriptions?limit={limit}&customer={customer}&status={status}`

#### `stripe_resume_subscription`
Resume a paused subscription.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `subscription_id` | str | Yes | Subscription ID to resume |
| `billing_cycle_anchor` | str | No | `now` or `unchanged` (default `now`) |
| `proration_behavior` | str | No | `create_prorations` (default), `none`, `always_invoice` |

**Returns:** Resumed subscription with updated `status`.
**Endpoint:** `POST /v1/subscriptions/{subscription_id}/resume`

---

### Tier 7: Products (5 tools)

#### `stripe_create_product`
Create a product (good or service).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Product name |
| `description` | str | No | Product description |
| `active` | bool | No | Whether the product is active (default `true`) |
| `images` | list[str] | No | List of image URLs (up to 8) |
| `url` | str | No | Product URL |
| `default_price_data_unit_amount` | int | No | Default price amount (cents) |
| `default_price_data_currency` | str | No | Default price currency |
| `default_price_data_recurring_interval` | str | No | Recurring interval: `day`, `week`, `month`, `year` |
| `default_price_data_recurring_interval_count` | int | No | Number of intervals between billings |
| `metadata` | dict | No | Arbitrary metadata |

**Returns:** Product object with `id`.
**Endpoint:** `POST /v1/products`

#### `stripe_get_product`
Retrieve a product by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `product_id` | str | Yes | Product ID (e.g., `prod_xxx`) |
| `expand` | list[str] | No | Objects to expand (e.g., `["default_price"]`) |

**Returns:** Product object with full details.
**Endpoint:** `GET /v1/products/{product_id}`

#### `stripe_update_product`
Update an existing product.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `product_id` | str | Yes | Product ID |
| `name` | str | No | Updated name |
| `description` | str | No | Updated description |
| `active` | bool | No | Updated active status |
| `images` | list[str] | No | Updated image URLs |
| `url` | str | No | Updated URL |
| `default_price` | str | No | Default price ID |
| `metadata` | dict | No | Updated metadata |

At least one property must be provided.
**Returns:** Updated product object.
**Endpoint:** `POST /v1/products/{product_id}`

#### `stripe_delete_product`
Delete a product (only if it has no prices).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `product_id` | str | Yes | Product ID to delete |

**Returns:** Deletion confirmation with `{"id": "prod_xxx", "deleted": true}`.
**Endpoint:** `DELETE /v1/products/{product_id}`

#### `stripe_list_products`
List products with pagination and filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: product ID to start after |
| `ending_before` | str | No | Cursor: product ID to end before |
| `active` | bool | No | Filter by active status |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |
| `url` | str | No | Filter by exact URL |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/products?limit={limit}&active={active}`

---

### Tier 8: Prices (4 tools)

#### `stripe_create_price`
Create a price for a product.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `product` | str | Yes | Product ID |
| `unit_amount` | int | No | Price in smallest currency unit (e.g., `1000` = $10.00). Use this or `unit_amount_decimal`. |
| `currency` | str | Yes | Three-letter currency code (e.g., `usd`) |
| `recurring_interval` | str | No | Billing interval: `day`, `week`, `month`, `year` (omit for one-time prices) |
| `recurring_interval_count` | int | No | Number of intervals between charges (default 1) |
| `recurring_usage_type` | str | No | `licensed` (default) or `metered` |
| `billing_scheme` | str | No | `per_unit` (default) or `tiered` |
| `tiers_mode` | str | No | `graduated` or `volume` (required for tiered billing) |
| `tiers` | list[dict] | No | Tier definitions for tiered pricing |
| `unit_amount_decimal` | str | No | Price as decimal string for sub-cent precision (e.g., `"10.25"`) |
| `nickname` | str | No | Nickname for the price |
| `active` | bool | No | Whether price is active (default `true`) |
| `tax_behavior` | str | No | `inclusive`, `exclusive`, or `unspecified` |
| `metadata` | dict | No | Arbitrary metadata |

**Returns:** Price object with `id`.
**Endpoint:** `POST /v1/prices`
**Body (form-encoded):** `product=prod_xxx&unit_amount=1000&currency=usd&recurring[interval]=month`

#### `stripe_get_price`
Retrieve a price by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `price_id` | str | Yes | Price ID (e.g., `price_xxx`) |
| `expand` | list[str] | No | Objects to expand (e.g., `["product"]`) |

**Returns:** Price object with full details.
**Endpoint:** `GET /v1/prices/{price_id}`

#### `stripe_update_price`
Update an existing price (limited fields; cannot change amount or currency).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `price_id` | str | Yes | Price ID |
| `active` | bool | No | Updated active status |
| `nickname` | str | No | Updated nickname |
| `tax_behavior` | str | No | Updated tax behavior |
| `metadata` | dict | No | Updated metadata |

At least one property must be provided.
**Returns:** Updated price object.
**Endpoint:** `POST /v1/prices/{price_id}`

#### `stripe_list_prices`
List prices with pagination and filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: price ID to start after |
| `ending_before` | str | No | Cursor: price ID to end before |
| `product` | str | No | Filter by product ID |
| `active` | bool | No | Filter by active status |
| `type` | str | No | Filter by type: `one_time` or `recurring` |
| `currency` | str | No | Filter by currency |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/prices?limit={limit}&product={product}&active={active}`

---

### Tier 9: Payment Methods (5 tools)

#### `stripe_create_payment_method`
Create a payment method (typically used in testing; production usually uses Stripe.js).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | str | Yes | Payment method type: `card`, `us_bank_account`, `sepa_debit`, etc. |
| `card_number` | str | No | Card number (test mode only, e.g., `4242424242424242`) |
| `card_exp_month` | int | No | Card expiry month (1-12) |
| `card_exp_year` | int | No | Card expiry year (e.g., 2028) |
| `card_cvc` | str | No | Card CVC |
| `billing_details_name` | str | No | Cardholder name |
| `billing_details_email` | str | No | Billing email |
| `billing_details_phone` | str | No | Billing phone |
| `billing_details_address_line1` | str | No | Billing address line 1 |
| `billing_details_address_city` | str | No | Billing city |
| `billing_details_address_state` | str | No | Billing state |
| `billing_details_address_postal_code` | str | No | Billing postal code |
| `billing_details_address_country` | str | No | Billing country |
| `metadata` | dict | No | Arbitrary metadata |

**Returns:** Payment method object with `id`.
**Endpoint:** `POST /v1/payment_methods`
**Body (form-encoded):** `type=card&card[number]=4242424242424242&card[exp_month]=12&card[exp_year]=2028&card[cvc]=123`

#### `stripe_get_payment_method`
Retrieve a payment method by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `payment_method_id` | str | Yes | Payment method ID (e.g., `pm_xxx`) |
| `expand` | list[str] | No | Objects to expand |

**Returns:** Payment method object with type-specific details.
**Endpoint:** `GET /v1/payment_methods/{payment_method_id}`

#### `stripe_list_payment_methods`
List payment methods for a customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `customer` | str | Yes | Customer ID |
| `type` | str | No | Filter by type: `card`, `us_bank_account`, `sepa_debit`, etc. |
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: payment method ID to start after |
| `ending_before` | str | No | Cursor: payment method ID to end before |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/payment_methods?customer={customer}&type={type}`

#### `stripe_attach_payment_method`
Attach a payment method to a customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `payment_method_id` | str | Yes | Payment method ID to attach |
| `customer` | str | Yes | Customer ID to attach to |

**Returns:** Attached payment method object.
**Endpoint:** `POST /v1/payment_methods/{payment_method_id}/attach`
**Body (form-encoded):** `customer=cus_xxx`

#### `stripe_detach_payment_method`
Detach a payment method from a customer.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `payment_method_id` | str | Yes | Payment method ID to detach |

**Returns:** Detached payment method object (no longer has `customer` field).
**Endpoint:** `POST /v1/payment_methods/{payment_method_id}/detach`

---

### Tier 10: Refunds (4 tools)

#### `stripe_create_refund`
Refund a charge or payment intent.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `charge` | str | No | Charge ID to refund (use this or `payment_intent`) |
| `payment_intent` | str | No | Payment intent ID to refund (use this or `charge`) |
| `amount` | int | No | Amount to refund in smallest currency unit (partial refund; defaults to full amount) |
| `reason` | str | No | Reason: `duplicate`, `fraudulent`, `requested_by_customer` |
| `metadata` | dict | No | Arbitrary metadata |
| `reverse_transfer` | bool | No | Reverse the Connect transfer (for Connect platforms) |
| `refund_application_fee` | bool | No | Refund the application fee (for Connect platforms) |

One of `charge` or `payment_intent` must be provided.
**Returns:** Refund object with `id`, `status`, `amount`.
**Endpoint:** `POST /v1/refunds`

#### `stripe_get_refund`
Retrieve a refund by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `refund_id` | str | Yes | Refund ID (e.g., `re_xxx`) |
| `expand` | list[str] | No | Objects to expand (e.g., `["charge", "payment_intent"]`) |

**Returns:** Refund object with full details.
**Endpoint:** `GET /v1/refunds/{refund_id}`

#### `stripe_update_refund`
Update a refund's metadata.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `refund_id` | str | Yes | Refund ID |
| `metadata` | dict | No | Updated metadata |

**Returns:** Updated refund object.
**Endpoint:** `POST /v1/refunds/{refund_id}`

#### `stripe_list_refunds`
List refunds with pagination and filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: refund ID to start after |
| `ending_before` | str | No | Cursor: refund ID to end before |
| `charge` | str | No | Filter by charge ID |
| `payment_intent` | str | No | Filter by payment intent ID |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/refunds?limit={limit}&charge={charge}`

---

### Tier 11: Balance (2 tools)

#### `stripe_get_balance`
Retrieve the current account balance.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| (none) | | | No parameters required |

**Returns:** Balance object with `available` and `pending` arrays (each with `amount`, `currency`).
**Endpoint:** `GET /v1/balance`

#### `stripe_list_balance_transactions`
List balance transactions (movements of funds).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: balance transaction ID to start after |
| `ending_before` | str | No | Cursor: balance transaction ID to end before |
| `type` | str | No | Filter by type: `charge`, `refund`, `adjustment`, `payout`, `transfer`, etc. |
| `source` | str | No | Filter by source ID (charge, refund, payout, etc.) |
| `payout` | str | No | Filter by payout ID |
| `currency` | str | No | Filter by currency |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |
| `available_on_gte` | int | No | Filter: available at or after (Unix timestamp) |
| `available_on_lte` | int | No | Filter: available at or before (Unix timestamp) |

**Returns:** List object with `data` array of balance transaction objects and `has_more`.
**Endpoint:** `GET /v1/balance_transactions?limit={limit}&type={type}`

---

### Tier 12: Payouts (3 tools)

#### `stripe_create_payout`
Create a payout to your bank account.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `amount` | int | Yes | Amount in smallest currency unit |
| `currency` | str | Yes | Currency code |
| `description` | str | No | Payout description |
| `destination` | str | No | Bank account or card ID (defaults to default external account) |
| `method` | str | No | `standard` (default) or `instant` |
| `source_type` | str | No | Source of funds: `card`, `fpx`, `bank_account` |
| `statement_descriptor` | str | No | Statement text (max 22 chars) |
| `metadata` | dict | No | Arbitrary metadata |

**Returns:** Payout object with `id`, `status`, `arrival_date`.
**Endpoint:** `POST /v1/payouts`

#### `stripe_get_payout`
Retrieve a payout by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `payout_id` | str | Yes | Payout ID (e.g., `po_xxx`) |
| `expand` | list[str] | No | Objects to expand (e.g., `["destination"]`) |

**Returns:** Payout object with full details.
**Endpoint:** `GET /v1/payouts/{payout_id}`

#### `stripe_list_payouts`
List payouts with pagination and filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: payout ID to start after |
| `ending_before` | str | No | Cursor: payout ID to end before |
| `status` | str | No | Filter: `pending`, `paid`, `failed`, `canceled` |
| `destination` | str | No | Filter by destination ID |
| `arrival_date_gte` | int | No | Filter: arrives at or after (Unix timestamp) |
| `arrival_date_lte` | int | No | Filter: arrives at or before (Unix timestamp) |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/payouts?limit={limit}&status={status}`

---

### Tier 13: Coupons (5 tools)

#### `stripe_create_coupon`
Create a coupon for discounts.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `percent_off` | float | No | Percentage discount (e.g., `25.0` for 25%). Use this or `amount_off`. |
| `amount_off` | int | No | Fixed amount discount in smallest currency unit. Use this or `percent_off`. |
| `currency` | str | No | Currency (required with `amount_off`) |
| `duration` | str | Yes | `once`, `repeating`, or `forever` |
| `duration_in_months` | int | No | Number of months (required if `duration` is `repeating`) |
| `id` | str | No | Custom coupon ID (e.g., `SUMMER25`; auto-generated if omitted) |
| `name` | str | No | Coupon name (displayed to customers) |
| `max_redemptions` | int | No | Maximum number of times coupon can be used |
| `redeem_by` | int | No | Unix timestamp after which coupon cannot be redeemed |
| `applies_to_products` | list[str] | No | Product IDs this coupon applies to |
| `metadata` | dict | No | Arbitrary metadata |

One of `percent_off` or `amount_off` must be provided.
**Returns:** Coupon object with `id`.
**Endpoint:** `POST /v1/coupons`

#### `stripe_get_coupon`
Retrieve a coupon by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `coupon_id` | str | Yes | Coupon ID |

**Returns:** Coupon object with full details.
**Endpoint:** `GET /v1/coupons/{coupon_id}`

#### `stripe_update_coupon`
Update a coupon's metadata or name.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `coupon_id` | str | Yes | Coupon ID |
| `name` | str | No | Updated name |
| `metadata` | dict | No | Updated metadata |

At least one property must be provided.
**Returns:** Updated coupon object.
**Endpoint:** `POST /v1/coupons/{coupon_id}`

#### `stripe_delete_coupon`
Delete a coupon (existing discounts using it remain active).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `coupon_id` | str | Yes | Coupon ID to delete |

**Returns:** Deletion confirmation with `{"id": "xxx", "deleted": true}`.
**Endpoint:** `DELETE /v1/coupons/{coupon_id}`

#### `stripe_list_coupons`
List coupons with pagination.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: coupon ID to start after |
| `ending_before` | str | No | Cursor: coupon ID to end before |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/coupons?limit={limit}`

---

### Tier 14: Promotion Codes (4 tools)

#### `stripe_create_promotion_code`
Create a customer-facing promotion code for a coupon.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `coupon` | str | Yes | Coupon ID this code activates |
| `code` | str | No | Customer-facing code (e.g., `SUMMER2026`; auto-generated if omitted) |
| `active` | bool | No | Whether the code is active (default `true`) |
| `customer` | str | No | Restrict to a specific customer ID |
| `max_redemptions` | int | No | Maximum number of times code can be used |
| `expires_at` | int | No | Unix timestamp when code expires |
| `restrictions_first_time_transaction` | bool | No | Restrict to first-time customers |
| `restrictions_minimum_amount` | int | No | Minimum order amount required (smallest currency unit) |
| `restrictions_minimum_amount_currency` | str | No | Currency for minimum amount |
| `metadata` | dict | No | Arbitrary metadata |

**Returns:** Promotion code object with `id`, `code`.
**Endpoint:** `POST /v1/promotion_codes`

#### `stripe_get_promotion_code`
Retrieve a promotion code by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `promotion_code_id` | str | Yes | Promotion code ID (e.g., `promo_xxx`) |
| `expand` | list[str] | No | Objects to expand (e.g., `["coupon"]`) |

**Returns:** Promotion code object with full details.
**Endpoint:** `GET /v1/promotion_codes/{promotion_code_id}`

#### `stripe_update_promotion_code`
Update a promotion code.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `promotion_code_id` | str | Yes | Promotion code ID |
| `active` | bool | No | Updated active status |
| `metadata` | dict | No | Updated metadata |

At least one property must be provided.
**Returns:** Updated promotion code object.
**Endpoint:** `POST /v1/promotion_codes/{promotion_code_id}`

#### `stripe_list_promotion_codes`
List promotion codes with pagination and filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: promotion code ID to start after |
| `ending_before` | str | No | Cursor: promotion code ID to end before |
| `active` | bool | No | Filter by active status |
| `coupon` | str | No | Filter by coupon ID |
| `code` | str | No | Filter by exact code string |
| `customer` | str | No | Filter by customer ID |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/promotion_codes?limit={limit}&active={active}&coupon={coupon}`

---

### Tier 15: Events (2 tools)

#### `stripe_get_event`
Retrieve an event by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | str | Yes | Event ID (e.g., `evt_xxx`) |

**Returns:** Event object with `type`, `data.object`, `created`.
**Endpoint:** `GET /v1/events/{event_id}`

#### `stripe_list_events`
List events (API event log) with pagination and filters.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: event ID to start after |
| `ending_before` | str | No | Cursor: event ID to end before |
| `type` | str | No | Filter by event type (e.g., `charge.succeeded`, `invoice.paid`, `customer.created`) |
| `types` | list[str] | No | Filter by multiple event types |
| `delivery_success` | bool | No | Filter by webhook delivery status |
| `created_gte` | int | No | Filter: created at or after (Unix timestamp) |
| `created_lte` | int | No | Filter: created at or before (Unix timestamp) |

**Note:** Events are only available for 30 days.
**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/events?limit={limit}&type={type}`

---

### Tier 16: Webhook Endpoints (5 tools)

#### `stripe_create_webhook_endpoint`
Create a webhook endpoint to receive events.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | str | Yes | URL to receive webhook events |
| `enabled_events` | list[str] | Yes | Event types to subscribe to (e.g., `["charge.succeeded", "invoice.paid"]` or `["*"]` for all) |
| `description` | str | No | Endpoint description |
| `api_version` | str | No | Stripe API version for events (e.g., `2024-12-18`) |
| `metadata` | dict | No | Arbitrary metadata |

**Returns:** Webhook endpoint object with `id`, `secret` (signing secret for verification).
**Endpoint:** `POST /v1/webhook_endpoints`
**Body (form-encoded):** `url=https://example.com/webhooks&enabled_events[0]=charge.succeeded&enabled_events[1]=invoice.paid`

#### `stripe_get_webhook_endpoint`
Retrieve a webhook endpoint by ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `webhook_endpoint_id` | str | Yes | Webhook endpoint ID (e.g., `we_xxx`) |

**Returns:** Webhook endpoint object with full details (excluding signing secret).
**Endpoint:** `GET /v1/webhook_endpoints/{webhook_endpoint_id}`

#### `stripe_update_webhook_endpoint`
Update a webhook endpoint.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `webhook_endpoint_id` | str | Yes | Webhook endpoint ID |
| `url` | str | No | Updated URL |
| `enabled_events` | list[str] | No | Updated event types |
| `description` | str | No | Updated description |
| `disabled` | bool | No | Set `true` to disable the endpoint |
| `metadata` | dict | No | Updated metadata |

At least one property must be provided.
**Returns:** Updated webhook endpoint object.
**Endpoint:** `POST /v1/webhook_endpoints/{webhook_endpoint_id}`

#### `stripe_delete_webhook_endpoint`
Delete a webhook endpoint.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `webhook_endpoint_id` | str | Yes | Webhook endpoint ID to delete |

**Returns:** Deletion confirmation with `{"id": "we_xxx", "deleted": true}`.
**Endpoint:** `DELETE /v1/webhook_endpoints/{webhook_endpoint_id}`

#### `stripe_list_webhook_endpoints`
List webhook endpoints with pagination.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | int | No | Number of results (default 10, max 100) |
| `starting_after` | str | No | Cursor: webhook endpoint ID to start after |
| `ending_before` | str | No | Cursor: webhook endpoint ID to end before |

**Returns:** List object with `data` array and `has_more`.
**Endpoint:** `GET /v1/webhook_endpoints?limit={limit}`

---

## Architecture Decisions

### A1: Direct HTTP with httpx (no SDK)
Consistent with HubSpot pattern. Use `httpx` (already a project dependency) for async HTTP calls directly. No dependency on `stripe` Python package. Stripe's REST API is simple and well-documented; form encoding is handled natively by httpx.

### A2: Shared httpx Client with Form Encoding
Create a shared `httpx.AsyncClient` with base URL and auth headers. **Critical difference from HubSpot:** Stripe uses form-encoded bodies, so we use `data=` instead of `json=` for all POST requests.

```python
import httpx

_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    if not STRIPE_API_KEY:
        raise ToolError(
            "STRIPE_API_KEY is not configured. "
            "Set it in your environment or .env file."
        )
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url="https://api.stripe.com/v1",
            headers={"Authorization": f"Bearer {STRIPE_API_KEY}"},
            timeout=30.0,
        )
    return _client
```

### A3: Form-Encoded Request Helper

Unlike HubSpot (JSON bodies), Stripe requires form-encoded bodies. The `_request` helper must use `data=` for POST bodies and handle nested parameter flattening:

```python
def _flatten_params(params: dict, prefix: str = "") -> dict:
    """Flatten nested dicts/lists into bracket-notation keys for form encoding.

    Examples:
        {"address": {"city": "SF"}} -> {"address[city]": "SF"}
        {"items": [{"price": "p_x"}]} -> {"items[0][price]": "p_x"}
        {"metadata": {"k": "v"}} -> {"metadata[k]": "v"}
    """
    flat = {}
    for key, value in params.items():
        full_key = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_params(value, full_key))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    flat.update(_flatten_params(item, f"{full_key}[{i}]"))
                else:
                    flat[f"{full_key}[{i}]"] = item
        elif value is not None:
            if isinstance(value, bool):
                flat[full_key] = "true" if value else "false"
            else:
                flat[full_key] = str(value)
    return flat


async def _request(method: str, path: str, **kwargs) -> dict | list:
    client = _get_client()
    # For POST/PUT/PATCH, flatten nested params into form-encoded data
    if "body" in kwargs:
        kwargs["data"] = _flatten_params(kwargs.pop("body"))
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as e:
        raise ToolError(f"Stripe request failed: {e}") from e
    if response.status_code == 429:
        raise ToolError("Stripe rate limit exceeded.")
    if response.status_code >= 400:
        try:
            err = response.json()
            msg = err.get("error", {}).get("message", response.text)
        except Exception:
            msg = response.text
        raise ToolError(f"Stripe error ({response.status_code}): {msg}")
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}
```

**Key design:** The `_flatten_params` function converts nested Python dicts/lists into Stripe's bracket-notation form encoding. This lets tool functions pass clean Python dicts while the helper handles serialization:

```python
# Tool code writes clean Python:
await _request("POST", "/customers", body={
    "name": "John",
    "address": {"line1": "123 Main", "city": "SF"},
    "metadata": {"source": "mcp"},
})

# Helper flattens to form-encoded:
# name=John&address[line1]=123+Main&address[city]=SF&metadata[source]=mcp
```

### A4: Tool Naming Convention
All Stripe tools prefixed with `stripe_` to distinguish from other integrations.

### A5: Error Handling
Same pattern as HubSpot: catch `httpx` exceptions, convert to `ToolError` with human-readable messages. Stripe error responses have a consistent structure: `{"error": {"type": "...", "message": "...", "code": "..."}}`. Extract the `message` field for user-friendly errors. 429 responses handled explicitly. No automatic retry.

### A6: Response Format
Consistent JSON convention: `{"status": "success", "status_code": N, ...}` wrapping the Stripe response data.

### A7: Pagination Pattern
Stripe uses cursor-based pagination with `starting_after` and `ending_before` parameters (object IDs, not opaque cursors). List responses include `has_more` boolean. Tools accept `limit`, `starting_after`, and `ending_before` params. No auto-pagination -- callers request specific pages.

### A8: Parameter Builder Helper
Create a helper function `_build_params()` that filters out `None` values, handles metadata merging, and converts address/billing_details fields into nested dicts for flattening:

```python
def _build_params(**kwargs) -> dict:
    """Build request params, filtering None values and nesting address fields."""
    params = {}
    address = {}
    billing_details = {}
    metadata = kwargs.pop("metadata", None)

    for key, value in kwargs.items():
        if value is None:
            continue
        if key.startswith("address_"):
            address[key[8:]] = value  # Strip "address_" prefix
        elif key.startswith("billing_details_address_"):
            billing_details.setdefault("address", {})[key[24:]] = value
        elif key.startswith("billing_details_"):
            billing_details[key[16:]] = value
        else:
            params[key] = value

    if address:
        params["address"] = address
    if billing_details:
        params["billing_details"] = billing_details
    if metadata:
        params["metadata"] = metadata
    return params
```

### A9: Expand Parameter Handling
Stripe's `expand[]` parameter uses array bracket notation. The helper converts a Python list like `["customer", "latest_charge"]` into query params `expand[0]=customer&expand[1]=latest_charge`. Handle this in the list-flattening logic.

### A10: Amount Convention Documentation
Tool docstrings must clearly state that amounts are in the smallest currency unit (cents for USD). Example: `$10.00 = 1000`. This is critical to avoid off-by-100x errors.

### A11: Missing API Key Strategy
Same as HubSpot: register tools regardless, fail at invocation with clear `ToolError`.

### A12: Subscription Items Flattening
Subscription `items` param requires special handling: `items[0][price]=price_xxx&items[0][quantity]=1`. The `_flatten_params` helper handles this automatically via the list-of-dicts logic.

---

## Configuration Requirements

### Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `STRIPE_API_KEY` | Stripe secret API key (format: `sk_test_xxx` or `sk_live_xxx`) | Yes (at invocation) | `None` |

### Config Pattern
```python
# Stripe
STRIPE_API_KEY: str | None = os.getenv("STRIPE_API_KEY")
```

### No Secondary Config Needed
Unlike some APIs, Stripe does not require a workspace/account ID -- the secret key is scoped to a single Stripe account automatically. The key prefix (`sk_test_` vs. `sk_live_`) determines test vs. live mode.

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/config.py` | Modify | Add `STRIPE_API_KEY` |
| `.env.example` | Modify | Add `STRIPE_API_KEY` variable |
| `src/mcp_toolbox/tools/stripe_tool.py` | **New** | All Stripe tools (77 tools) |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register stripe_tool |
| `tests/test_stripe_tool.py` | **New** | Tests for all Stripe tools |

---

## Testing Strategy

### Approach
Use `pytest` with `respx` (already used for HubSpot/ClickUp tests) for mocking HTTP calls. All Stripe endpoints follow predictable REST patterns, making mocking straightforward. Test both the form-encoding logic and the parameter flattening.

```python
import respx
import httpx

@respx.mock
async def test_create_customer():
    respx.post("https://api.stripe.com/v1/customers").mock(
        return_value=httpx.Response(200, json={
            "id": "cus_xxx",
            "object": "customer",
            "email": "test@example.com",
            "name": "Test User",
            "created": 1711929600,
        })
    )
    result = await server.call_tool("stripe_create_customer", {"email": "test@example.com", "name": "Test User"})
    assert "success" in result

@respx.mock
async def test_create_payment_intent():
    respx.post("https://api.stripe.com/v1/payment_intents").mock(
        return_value=httpx.Response(200, json={
            "id": "pi_xxx",
            "object": "payment_intent",
            "amount": 1000,
            "currency": "usd",
            "status": "requires_payment_method",
        })
    )
    result = await server.call_tool("stripe_create_payment_intent", {"amount": 1000, "currency": "usd"})
    assert "success" in result
```

### Test Coverage
1. Happy path for every tool (77 tests minimum)
2. Missing API key -> ToolError
3. API errors (401 Unauthorized, 402 Card Declined, 404 Not Found, 429 Rate Limit)
4. Form-encoded body generation (verify `data=` not `json=`)
5. Parameter flattening (nested address, metadata, subscription items)
6. Boolean conversion (`true`/`false` strings in form encoding)
7. Pagination cursor passing (`starting_after`, `ending_before`)
8. `expand[]` parameter serialization
9. Partial capture/refund amount handling
10. Delete confirmation format (`{"deleted": true}`)

### Key Test: Form Encoding Verification

```python
@respx.mock
async def test_form_encoding_not_json():
    """Verify Stripe requests use form encoding, not JSON."""
    route = respx.post("https://api.stripe.com/v1/customers").mock(
        return_value=httpx.Response(200, json={"id": "cus_xxx", "object": "customer"})
    )
    await server.call_tool("stripe_create_customer", {"name": "Test", "email": "t@t.com"})
    request = route.calls[0].request
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert b"name=Test" in request.content
```

### Key Test: Nested Parameter Flattening

```python
def test_flatten_params():
    result = _flatten_params({
        "name": "John",
        "address": {"line1": "123 Main", "city": "SF"},
        "metadata": {"order_id": "123"},
        "items": [{"price": "price_xxx", "quantity": 1}],
    })
    assert result == {
        "name": "John",
        "address[line1]": "123 Main",
        "address[city]": "SF",
        "metadata[order_id]": "123",
        "items[0][price]": "price_xxx",
        "items[0][quantity]": "1",
    }
```

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
2. All 77 Stripe tools register and are discoverable via MCP Inspector
3. Tools return meaningful errors when API key is missing
4. All tools return consistent JSON responses (`{"status": "success", ...}`)
5. Form-encoded request bodies (NOT JSON) are used for all POST requests
6. Nested parameters (address, metadata, items) flatten correctly to bracket notation
7. New tests pass and full regression suite remains green
8. Config handles missing API key gracefully (tools register, fail at invocation)
9. Total tool count reaches **415** (current 338 + 77 new Stripe tools)

---

## Scope Decision

**All 16 tiers (77 tools)** -- full Stripe payment integration covering customers, payment intents, charges, invoices, invoice items, subscriptions, products, prices, payment methods, refunds, balance, payouts, coupons, promotion codes, events, and webhook endpoints.

---

## Tool Summary (77 tools total)

### Tier 1 -- Customers (6 tools)
1. `stripe_create_customer` -- Create a customer with email, name, address, metadata
2. `stripe_get_customer` -- Get customer by ID with optional expand
3. `stripe_update_customer` -- Update customer properties
4. `stripe_delete_customer` -- Permanently delete a customer
5. `stripe_list_customers` -- List customers with pagination and email/date filters
6. `stripe_search_customers` -- Search customers using Stripe query language

### Tier 2 -- Payment Intents (6 tools)
7. `stripe_create_payment_intent` -- Create payment intent with amount, currency, customer
8. `stripe_get_payment_intent` -- Get payment intent by ID
9. `stripe_update_payment_intent` -- Update payment intent before confirmation
10. `stripe_confirm_payment_intent` -- Confirm payment intent to initiate processing
11. `stripe_cancel_payment_intent` -- Cancel an unconfirmed payment intent
12. `stripe_list_payment_intents` -- List payment intents with filters

### Tier 3 -- Charges (5 tools)
13. `stripe_create_charge` -- Create a direct charge (legacy)
14. `stripe_get_charge` -- Get charge by ID
15. `stripe_update_charge` -- Update charge description/metadata
16. `stripe_list_charges` -- List charges with filters
17. `stripe_capture_charge` -- Capture an authorized charge

### Tier 4 -- Invoices (10 tools)
18. `stripe_create_invoice` -- Create a draft invoice for a customer
19. `stripe_get_invoice` -- Get invoice by ID
20. `stripe_update_invoice` -- Update draft/open invoice properties
21. `stripe_finalize_invoice` -- Finalize draft to open status
22. `stripe_pay_invoice` -- Pay an open invoice
23. `stripe_void_invoice` -- Void an open invoice
24. `stripe_send_invoice` -- Send invoice email to customer
25. `stripe_list_invoices` -- List invoices with status/date filters
26. `stripe_list_invoice_line_items` -- List line items for an invoice
27. `stripe_add_invoice_line_item` -- Add line item to a draft invoice

### Tier 5 -- Invoice Items (5 tools)
28. `stripe_create_invoice_item` -- Create pending invoice item for next invoice
29. `stripe_get_invoice_item` -- Get invoice item by ID
30. `stripe_update_invoice_item` -- Update invoice item before finalization
31. `stripe_delete_invoice_item` -- Delete pending invoice item
32. `stripe_list_invoice_items` -- List invoice items with filters

### Tier 6 -- Subscriptions (6 tools)
33. `stripe_create_subscription` -- Create subscription with items, trial, coupon
34. `stripe_get_subscription` -- Get subscription by ID
35. `stripe_update_subscription` -- Update subscription items, payment method, coupon
36. `stripe_cancel_subscription` -- Cancel active subscription
37. `stripe_list_subscriptions` -- List subscriptions with status/customer filters
38. `stripe_resume_subscription` -- Resume a paused subscription

### Tier 7 -- Products (5 tools)
39. `stripe_create_product` -- Create product with name, description, images
40. `stripe_get_product` -- Get product by ID
41. `stripe_update_product` -- Update product properties
42. `stripe_delete_product` -- Delete product (no prices)
43. `stripe_list_products` -- List products with active/date filters

### Tier 8 -- Prices (4 tools)
44. `stripe_create_price` -- Create price for product (one-time or recurring)
45. `stripe_get_price` -- Get price by ID
46. `stripe_update_price` -- Update price metadata/active status
47. `stripe_list_prices` -- List prices with product/type/currency filters

### Tier 9 -- Payment Methods (5 tools)
48. `stripe_create_payment_method` -- Create payment method (test mode)
49. `stripe_get_payment_method` -- Get payment method by ID
50. `stripe_list_payment_methods` -- List payment methods for a customer
51. `stripe_attach_payment_method` -- Attach payment method to customer
52. `stripe_detach_payment_method` -- Detach payment method from customer

### Tier 10 -- Refunds (4 tools)
53. `stripe_create_refund` -- Refund a charge or payment intent (full or partial)
54. `stripe_get_refund` -- Get refund by ID
55. `stripe_update_refund` -- Update refund metadata
56. `stripe_list_refunds` -- List refunds with charge/PI filters

### Tier 11 -- Balance (2 tools)
57. `stripe_get_balance` -- Get current account balance
58. `stripe_list_balance_transactions` -- List balance transactions with type/date filters

### Tier 12 -- Payouts (3 tools)
59. `stripe_create_payout` -- Create payout to bank account
60. `stripe_get_payout` -- Get payout by ID
61. `stripe_list_payouts` -- List payouts with status/date filters

### Tier 13 -- Coupons (5 tools)
62. `stripe_create_coupon` -- Create discount coupon (percent or fixed amount)
63. `stripe_get_coupon` -- Get coupon by ID
64. `stripe_update_coupon` -- Update coupon name/metadata
65. `stripe_delete_coupon` -- Delete coupon
66. `stripe_list_coupons` -- List coupons with pagination

### Tier 14 -- Promotion Codes (4 tools)
67. `stripe_create_promotion_code` -- Create customer-facing code for a coupon
68. `stripe_get_promotion_code` -- Get promotion code by ID
69. `stripe_update_promotion_code` -- Update promotion code active status
70. `stripe_list_promotion_codes` -- List promotion codes with filters

### Tier 15 -- Events (2 tools)
71. `stripe_get_event` -- Get event by ID
72. `stripe_list_events` -- List events with type/date filters (30-day retention)

### Tier 16 -- Webhook Endpoints (5 tools)
73. `stripe_create_webhook_endpoint` -- Create webhook endpoint with event subscriptions
74. `stripe_get_webhook_endpoint` -- Get webhook endpoint by ID
75. `stripe_update_webhook_endpoint` -- Update webhook endpoint URL/events
76. `stripe_delete_webhook_endpoint` -- Delete webhook endpoint
77. `stripe_list_webhook_endpoints` -- List webhook endpoints

---

**Total: 77 tools** (revised from initial 72 estimate after accounting for all invoice sub-operations and webhook CRUD)

**Updated tool count target: 415** (current 338 + 77 new Stripe tools)
