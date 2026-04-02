# Task 07: Azure Key Vault Integration - Analysis & Requirements

## Objective
Add Azure Key Vault secret, key, and certificate management as a tool integration in mcp-toolbox, reusing the existing Azure app registration and msal auth.

---

## API Technical Details

### Azure Key Vault REST API v7.4
- **Base URL:** `https://{vault-name}.vault.azure.net/`
- **API Version:** `7.4` (appended as `?api-version=7.4`)
- **Auth:** OAuth2 Bearer token with scope `https://vault.azure.net/.default`
- **Note:** Base URL is vault-specific — different from Graph API (`graph.microsoft.com`)

### Authentication — Reuses Existing App Registration
Same `tenant_id`, `client_id`, `client_secret` as O365/Teams. Key difference: **different token scope**.

```python
# Graph API token (email/teams):
scopes=["https://graph.microsoft.com/.default"]

# Key Vault token:
scopes=["https://vault.azure.net/.default"]
```

The `msal.ConfidentialClientApplication` can acquire tokens for both — just call `acquire_token_for_client()` with the appropriate scope. Tokens are cached independently.

### RBAC Roles Required

Assign to the app's service principal on the Key Vault resource:

| Role | Grants |
|------|--------|
| `Key Vault Secrets Officer` | Full CRUD on secrets |
| `Key Vault Crypto Officer` | Full CRUD on keys + crypto operations |
| `Key Vault Certificates Officer` | Full CRUD on certificates |
| `Key Vault Administrator` | All of the above |

### Rate Limits

| Operation | Limit |
|-----------|-------|
| All transactions (standard tier) | 2,000 per 10 seconds per vault |
| HSM key operations | 1,000 per 10 seconds per vault |
| RSA 3072/4096-bit operations | 500 per 10 seconds |
| Per-subscription aggregate | ~6,000 per 10 seconds per region |

HTTP 429 with `Retry-After` header on throttle.

### Soft-Delete
- **Enabled by default** on all vaults (mandatory since Feb 2025)
- Retention period: 7-90 days (default 90)
- Purge protection: optional but recommended
- Deleted items can be recovered or purged

---

## Architecture Decisions

### A1: Direct HTTP with httpx + msal (no Azure SDK)
The Azure SDK (`azure-keyvault-secrets`, `azure-keyvault-keys`, `azure-keyvault-certificates`) uses `aiohttp` internally, which would add a competing async HTTP stack alongside our `httpx`. For consistency with O365/Teams tools, we use `httpx` directly with `msal` for token management — same pattern, different scope and base URL.

### A2: Vault URL as Config
Unlike Graph API (single base URL), Key Vault URLs are vault-specific. The vault URL is a required config variable.

```python
KEYVAULT_URL: str | None = os.getenv("KEYVAULT_URL")  # e.g., "https://myvault.vault.azure.net"
```

### A3: Token Scope & Own msal Instance
Key Vault tokens use scope `https://vault.azure.net/.default` (different from Graph API). The `keyvault_tool.py` module has its **own `_msal_app` singleton** — it cannot share the Graph API msal app from o365/teams tools because the scope is different.

`_get_token()` is synchronous (msal) and must be wrapped in `asyncio.to_thread()` in the `_request()` helper, same as O365/Teams.

### A4: Credential Config with Fallback
Follow the established pattern: Key Vault gets its own credential vars that fall back to O365 equivalents. This allows different app registrations per service when needed (e.g., Key Vault in a different tenant).

```python
KEYVAULT_TENANT_ID: str | None = os.getenv("KEYVAULT_TENANT_ID") or O365_TENANT_ID
KEYVAULT_CLIENT_ID: str | None = os.getenv("KEYVAULT_CLIENT_ID") or O365_CLIENT_ID
KEYVAULT_CLIENT_SECRET: str | None = os.getenv("KEYVAULT_CLIENT_SECRET") or O365_CLIENT_SECRET
```

### A5: API Version Parameter
All requests include `?api-version=7.4` as a query parameter. The `_request()` helper handles this automatically.

### A6: Pagination
Key Vault list endpoints return paginated results with a `nextLink` field. Tools return a single page of results. Callers can use `max_results` to control page size. No auto-pagination — consistent with the ClickUp/Teams pattern.

---

## Configuration Requirements

### Environment Variables
| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `KEYVAULT_URL` | Vault URL (e.g., `https://myvault.vault.azure.net`) | Yes (at invocation) | `None` |
| `KEYVAULT_TENANT_ID` | Entra ID tenant ID | No | Falls back to `O365_TENANT_ID` |
| `KEYVAULT_CLIENT_ID` | App client ID | No | Falls back to `O365_CLIENT_ID` |
| `KEYVAULT_CLIENT_SECRET` | App client secret | No | Falls back to `O365_CLIENT_SECRET` |

No new required credentials if O365 is already configured.

---

## Tool Specifications

### Secrets (11 tools)

#### `kv_set_secret`
Create or update a secret (creates new version if name exists).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Secret name |
| `value` | str | Yes | Secret value |
| `content_type` | str | No | Content type (e.g., `text/plain`, `application/json`) |
| `enabled` | bool | No | Whether secret is enabled (default true) |
| `tags` | dict | No | Key-value tags |

**Returns:** Secret identifier with version.
**Endpoint:** `PUT /secrets/{name}?api-version=7.4`

#### `kv_get_secret`
Get a secret's current value.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Secret name |
| `version` | str | No | Specific version (default: latest) |

**Returns:** Secret value and metadata.
**Endpoint:** `GET /secrets/{name}[/{version}]?api-version=7.4`

#### `kv_list_secrets`
List all secrets in the vault (names and metadata only, no values).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `max_results` | int | No | Max results (default 25) |

**Returns:** List of secret identifiers with attributes.
**Endpoint:** `GET /secrets?api-version=7.4`

#### `kv_list_secret_versions`
List all versions of a specific secret.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Secret name |
| `max_results` | int | No | Max results (default 25) |

**Returns:** List of versions with attributes (no values).
**Endpoint:** `GET /secrets/{name}/versions?api-version=7.4`

#### `kv_update_secret`
Update secret attributes (enabled, tags, content type, expiry).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Secret name |
| `version` | str | Yes | Secret version |
| `enabled` | bool | No | Enable/disable |
| `content_type` | str | No | Content type |
| `tags` | dict | No | Key-value tags |

**Returns:** Updated secret attributes.
**Endpoint:** `PATCH /secrets/{name}/{version}?api-version=7.4`

#### `kv_delete_secret`
Delete a secret (soft-delete — can be recovered).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Secret name |

**Returns:** Deleted secret details with recovery ID and purge date.
**Endpoint:** `DELETE /secrets/{name}?api-version=7.4`

#### `kv_recover_secret`
Recover a soft-deleted secret.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Secret name |

**Returns:** Recovered secret details.
**Endpoint:** `POST /deletedsecrets/{name}/recover?api-version=7.4`

#### `kv_purge_secret`
Permanently delete a soft-deleted secret (irreversible).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Secret name |

**Returns:** Confirmation.
**Endpoint:** `DELETE /deletedsecrets/{name}?api-version=7.4`

#### `kv_list_deleted_secrets`
List all soft-deleted secrets in the vault.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `max_results` | int | No | Max results (default 25) |

**Returns:** List of deleted secrets with recovery IDs and purge dates.
**Endpoint:** `GET /deletedsecrets?api-version=7.4`

---

### Keys (18 tools)

#### `kv_create_key`
Create a cryptographic key.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |
| `kty` | str | Yes | Key type: `RSA`, `EC`, `oct`, `RSA-HSM`, `EC-HSM` |
| `key_size` | int | No | Key size (2048, 3072, 4096 for RSA) |
| `crv` | str | No | Curve name for EC keys (`P-256`, `P-384`, `P-521`) |
| `key_ops` | list[str] | No | Allowed operations (encrypt, decrypt, sign, verify, wrapKey, unwrapKey) |

**Returns:** Key identifier with version.
**Endpoint:** `POST /keys/{name}/create?api-version=7.4`

#### `kv_get_key`
Get a key's public component.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |
| `version` | str | No | Specific version (default: latest) |

**Returns:** Key material (public) and metadata.
**Endpoint:** `GET /keys/{name}[/{version}]?api-version=7.4`

#### `kv_list_keys`
List all keys in the vault.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `max_results` | int | No | Max results (default 25) |

**Returns:** List of key identifiers with attributes.
**Endpoint:** `GET /keys?api-version=7.4`

#### `kv_update_key`
Update key attributes.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |
| `version` | str | Yes | Key version |
| `enabled` | bool | No | Enable/disable |
| `tags` | dict | No | Key-value tags |

**Returns:** Updated key.
**Endpoint:** `PATCH /keys/{name}/{version}?api-version=7.4`

#### `kv_delete_key`
Delete a key (soft-delete).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |

**Returns:** Deleted key details.
**Endpoint:** `DELETE /keys/{name}?api-version=7.4`

#### `kv_rotate_key`
Rotate a key (creates new version per rotation policy).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |

**Returns:** New key version.
**Endpoint:** `POST /keys/{name}/rotate?api-version=7.4`

#### `kv_encrypt`
Encrypt data using a key.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |
| `version` | str | Yes | Key version |
| `algorithm` | str | Yes | Algorithm (e.g., `RSA-OAEP`, `RSA-OAEP-256`) |
| `value` | str | Yes | Base64url-encoded plaintext |

**Returns:** Base64url-encoded ciphertext.
**Endpoint:** `POST /keys/{name}/{version}/encrypt?api-version=7.4`

#### `kv_decrypt`
Decrypt data using a key.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |
| `version` | str | Yes | Key version |
| `algorithm` | str | Yes | Algorithm |
| `value` | str | Yes | Base64url-encoded ciphertext |

**Returns:** Base64url-encoded plaintext.
**Endpoint:** `POST /keys/{name}/{version}/decrypt?api-version=7.4`

#### `kv_sign`
Sign a digest using a key.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |
| `version` | str | Yes | Key version |
| `algorithm` | str | Yes | Algorithm (e.g., `RS256`, `ES256`) |
| `value` | str | Yes | Base64url-encoded digest |

**Returns:** Base64url-encoded signature.
**Endpoint:** `POST /keys/{name}/{version}/sign?api-version=7.4`

#### `kv_verify`
Verify a signature using a key.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |
| `version` | str | Yes | Key version |
| `algorithm` | str | Yes | Algorithm |
| `digest` | str | Yes | Base64url-encoded digest |
| `signature` | str | Yes | Base64url-encoded signature |

**Returns:** Verification result (true/false).
**Endpoint:** `POST /keys/{name}/{version}/verify?api-version=7.4`

#### `kv_wrap_key`
Wrap (encrypt) a symmetric key using a Key Vault key.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |
| `version` | str | Yes | Key version |
| `algorithm` | str | Yes | Algorithm (e.g., `RSA-OAEP`) |
| `value` | str | Yes | Base64url-encoded key to wrap |

**Returns:** Base64url-encoded wrapped key.
**Endpoint:** `POST /keys/{name}/{version}/wrapkey?api-version=7.4`

#### `kv_unwrap_key`
Unwrap (decrypt) a wrapped symmetric key.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |
| `version` | str | Yes | Key version |
| `algorithm` | str | Yes | Algorithm |
| `value` | str | Yes | Base64url-encoded wrapped key |

**Returns:** Base64url-encoded unwrapped key.
**Endpoint:** `POST /keys/{name}/{version}/unwrapkey?api-version=7.4`

#### `kv_list_key_versions`
List all versions of a specific key.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |
| `max_results` | int | No | Max results (default 25) |

**Returns:** List of key versions with attributes.
**Endpoint:** `GET /keys/{name}/versions?api-version=7.4`

#### `kv_recover_key`
Recover a soft-deleted key.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |

**Returns:** Recovered key details.
**Endpoint:** `POST /deletedkeys/{name}/recover?api-version=7.4`

#### `kv_purge_key`
Permanently delete a soft-deleted key (irreversible).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |

**Returns:** Confirmation.
**Endpoint:** `DELETE /deletedkeys/{name}?api-version=7.4`

#### `kv_list_deleted_keys`
List all soft-deleted keys.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `max_results` | int | No | Max results (default 25) |

**Returns:** List of deleted keys with recovery IDs.
**Endpoint:** `GET /deletedkeys?api-version=7.4`

#### `kv_backup_secret`
Backup a secret (returns opaque blob).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Secret name |

**Returns:** Base64-encoded backup blob.
**Endpoint:** `POST /secrets/{name}/backup?api-version=7.4`

#### `kv_restore_secret`
Restore a secret from a backup blob.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `value` | str | Yes | Base64-encoded backup blob |

**Returns:** Restored secret details.
**Endpoint:** `POST /secrets/restore?api-version=7.4`

---

### Certificates (10 tools)

#### `kv_get_certificate`
Get a certificate.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Certificate name |
| `version` | str | No | Specific version (default: latest) |

**Returns:** Certificate with policy and metadata.
**Endpoint:** `GET /certificates/{name}[/{version}]?api-version=7.4`

#### `kv_list_certificates`
List all certificates in the vault.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `max_results` | int | No | Max results (default 25) |

**Returns:** List of certificate identifiers.
**Endpoint:** `GET /certificates?api-version=7.4`

#### `kv_create_certificate`
Create a self-signed certificate (async operation).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Certificate name |
| `subject` | str | Yes | Subject (e.g., `CN=example.com`) |
| `validity_months` | int | No | Validity in months (default 12) |

**Returns:** Certificate operation status.
**Endpoint:** `POST /certificates/{name}/create?api-version=7.4`

#### `kv_import_certificate`
Import a PFX/PEM certificate.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Certificate name |
| `value` | str | Yes | Base64-encoded certificate content |
| `password` | str | No | PFX password |

**Returns:** Imported certificate.
**Endpoint:** `POST /certificates/{name}/import?api-version=7.4`

#### `kv_delete_certificate`
Delete a certificate (soft-delete).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Certificate name |

**Returns:** Deleted certificate details.
**Endpoint:** `DELETE /certificates/{name}?api-version=7.4`

#### `kv_update_certificate`
Update certificate attributes.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Certificate name |
| `version` | str | Yes | Certificate version |
| `enabled` | bool | No | Enable/disable |
| `tags` | dict | No | Key-value tags |

**Returns:** Updated certificate.
**Endpoint:** `PATCH /certificates/{name}/{version}?api-version=7.4`

#### `kv_list_certificate_versions`
List all versions of a specific certificate.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Certificate name |
| `max_results` | int | No | Max results (default 25) |

**Returns:** List of certificate versions.
**Endpoint:** `GET /certificates/{name}/versions?api-version=7.4`

#### `kv_recover_certificate`
Recover a soft-deleted certificate.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Certificate name |

**Returns:** Recovered certificate details.
**Endpoint:** `POST /deletedcertificates/{name}/recover?api-version=7.4`

#### `kv_purge_certificate`
Permanently delete a soft-deleted certificate (irreversible).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Certificate name |

**Returns:** Confirmation.
**Endpoint:** `DELETE /deletedcertificates/{name}?api-version=7.4`

#### `kv_list_deleted_certificates`
List all soft-deleted certificates.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `max_results` | int | No | Max results (default 25) |

**Returns:** List of deleted certificates.
**Endpoint:** `GET /deletedcertificates?api-version=7.4`

#### `kv_backup_key`
Backup a key (returns opaque blob).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | Yes | Key name |

**Returns:** Base64-encoded backup blob.
**Endpoint:** `POST /keys/{name}/backup?api-version=7.4`

#### `kv_restore_key`
Restore a key from a backup blob.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `value` | str | Yes | Base64-encoded backup blob |

**Returns:** Restored key details.
**Endpoint:** `POST /keys/restore?api-version=7.4`

---

## Tool Summary (39 tools total)

### Secrets (11 tools)
1. `kv_set_secret` — Create/update secret
2. `kv_get_secret` — Get secret value
3. `kv_list_secrets` — List secrets (no values)
4. `kv_list_secret_versions` — List versions of a secret
5. `kv_update_secret` — Update secret attributes
6. `kv_delete_secret` — Soft-delete secret
7. `kv_recover_secret` — Recover deleted secret
8. `kv_purge_secret` — Permanently delete secret
9. `kv_list_deleted_secrets` — List soft-deleted secrets
10. `kv_backup_secret` — Backup secret
11. `kv_restore_secret` — Restore secret from backup

### Keys (18 tools)
12. `kv_create_key` — Create cryptographic key
13. `kv_get_key` — Get key
14. `kv_list_keys` — List keys
15. `kv_list_key_versions` — List key versions
16. `kv_update_key` — Update key attributes
17. `kv_delete_key` — Soft-delete key
18. `kv_recover_key` — Recover deleted key
19. `kv_purge_key` — Permanently delete key
20. `kv_list_deleted_keys` — List soft-deleted keys
21. `kv_rotate_key` — Rotate key
22. `kv_encrypt` — Encrypt with key
23. `kv_decrypt` — Decrypt with key
24. `kv_sign` — Sign digest
25. `kv_verify` — Verify signature
26. `kv_wrap_key` — Wrap symmetric key
27. `kv_unwrap_key` — Unwrap symmetric key
28. `kv_backup_key` — Backup key
29. `kv_restore_key` — Restore key from backup

### Certificates (10 tools)
30. `kv_get_certificate` — Get certificate
31. `kv_list_certificates` — List certificates
32. `kv_list_certificate_versions` — List cert versions
33. `kv_create_certificate` — Create self-signed cert
34. `kv_import_certificate` — Import PFX/PEM
35. `kv_update_certificate` — Update cert attributes
36. `kv_delete_certificate` — Soft-delete certificate
37. `kv_recover_certificate` — Recover deleted cert
38. `kv_purge_certificate` — Permanently delete cert
39. `kv_list_deleted_certificates` — List soft-deleted certs

---

## Dependencies

No new runtime dependencies — `msal` and `httpx` already installed. No new dev deps.

---

## File Changes Required

| File | Action | Description |
|------|--------|-------------|
| `src/mcp_toolbox/config.py` | Modify | Add `KEYVAULT_URL`, `KEYVAULT_TENANT_ID`, `KEYVAULT_CLIENT_ID`, `KEYVAULT_CLIENT_SECRET` |
| `.env.example` | Modify | Add Key Vault variables |
| `src/mcp_toolbox/tools/keyvault_tool.py` | **New** | All Key Vault tools |
| `src/mcp_toolbox/tools/__init__.py` | Modify | Register keyvault_tool |
| `tests/test_keyvault_tool.py` | **New** | Tests for all 39 tools |
| `tests/test_server.py` | Modify | Update tool count to 183 |
| `CLAUDE.md` | Modify | Document Key Vault integration |
| `pyproject.toml` | Modify | Add keyvault_tool.py to pyright exclude |

---

## Testing Strategy

Same as O365/Teams:
- `respx` for Key Vault REST API mocking (different base URL pattern)
- `unittest.mock.patch` for msal token mocking
- Mock vault URL in fixtures
- Happy path for every tool + auth/error tests

---

## Success Criteria

1. All 39 Key Vault tools register and are discoverable
2. Tools work with existing O365 credentials (via fallback) + vault URL config
3. Different token scope (`vault.azure.net`) handled correctly with own msal instance
4. New tests pass and full regression suite remains green
5. Total toolbox: 144 existing + 39 new = **183 tools**
