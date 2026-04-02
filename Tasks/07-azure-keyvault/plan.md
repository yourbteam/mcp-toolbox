# Task 07: Azure Key Vault Integration - Implementation Plan

## Overview
Implement 39 Key Vault tools (secrets, keys, certificates) using httpx + msal with vault-specific base URL and `vault.azure.net` token scope.

**Final state:** 183 tools total (144 existing + 39 new).

---

## Step 1: Configuration

### 1a. Add Key Vault config to `config.py`
Append after Teams variables:
```python
# Azure Key Vault
KEYVAULT_URL: str | None = os.getenv("KEYVAULT_URL")
KEYVAULT_TENANT_ID: str | None = os.getenv("KEYVAULT_TENANT_ID") or O365_TENANT_ID
KEYVAULT_CLIENT_ID: str | None = os.getenv("KEYVAULT_CLIENT_ID") or O365_CLIENT_ID
KEYVAULT_CLIENT_SECRET: str | None = os.getenv("KEYVAULT_CLIENT_SECRET") or O365_CLIENT_SECRET
```

### 1b. Update `.env.example`
```env
# Azure Key Vault Integration (credentials fall back to O365)
KEYVAULT_URL=https://myvault.vault.azure.net
# KEYVAULT_TENANT_ID=your-tenant-id
# KEYVAULT_CLIENT_ID=your-client-id
# KEYVAULT_CLIENT_SECRET=your-client-secret
```

### 1c. Add pyright exclusion
```toml
exclude = ["src/mcp_toolbox/tools/sendgrid_tool.py", "src/mcp_toolbox/tools/o365_tool.py", "src/mcp_toolbox/tools/teams_tool.py", "src/mcp_toolbox/tools/keyvault_tool.py"]
```

---

## Step 2: Tool Module Foundation

Create `src/mcp_toolbox/tools/keyvault_tool.py`:

```python
"""Azure Key Vault integration — secrets, keys, certificates management."""

import asyncio
import json
import logging

import httpx
import msal
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_toolbox.config import (
    KEYVAULT_CLIENT_ID,
    KEYVAULT_CLIENT_SECRET,
    KEYVAULT_TENANT_ID,
    KEYVAULT_URL,
)

logger = logging.getLogger(__name__)

API_VERSION = "7.4"

_msal_app: msal.ConfidentialClientApplication | None = None
_http_client: httpx.AsyncClient | None = None


def _get_token() -> str:
    """Acquire Key Vault token. Sync — call via asyncio.to_thread."""
    global _msal_app
    if not KEYVAULT_TENANT_ID or not KEYVAULT_CLIENT_ID or not KEYVAULT_CLIENT_SECRET:
        raise ToolError(
            "Key Vault credentials not configured. Set KEYVAULT_TENANT_ID, "
            "KEYVAULT_CLIENT_ID, KEYVAULT_CLIENT_SECRET (or O365 equivalents)."
        )
    if _msal_app is None:
        _msal_app = msal.ConfidentialClientApplication(
            client_id=KEYVAULT_CLIENT_ID,
            client_credential=KEYVAULT_CLIENT_SECRET,
            authority=f"https://login.microsoftonline.com/{KEYVAULT_TENANT_ID}",
        )
    result = _msal_app.acquire_token_for_client(
        scopes=["https://vault.azure.net/.default"]
    )
    if "access_token" not in result:
        raise ToolError(
            f"Failed to acquire Key Vault token: "
            f"{result.get('error_description', result.get('error', 'unknown'))}"
        )
    return result["access_token"]


def _get_vault_url() -> str:
    """Get the configured vault URL."""
    if not KEYVAULT_URL:
        raise ToolError(
            "KEYVAULT_URL not configured. Set it to your vault URL "
            "(e.g., https://myvault.vault.azure.net)."
        )
    return KEYVAULT_URL.rstrip("/")


def _get_http_client() -> httpx.AsyncClient:
    """Get or create the singleton httpx client for Key Vault."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url=_get_vault_url(),
            timeout=30.0,
        )
    return _http_client


def _success(status_code: int, **kwargs) -> str:
    return json.dumps({"status": "success", "status_code": status_code, **kwargs})


async def _request(method: str, path: str, **kwargs) -> dict | list:
    """Make an authenticated Key Vault API request."""
    token = await asyncio.to_thread(_get_token)
    client = _get_http_client()

    # Auto-append api-version
    params = kwargs.pop("params", {})
    params["api-version"] = API_VERSION

    try:
        response = await client.request(
            method, path,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            **kwargs,
        )
    except httpx.HTTPError as e:
        raise ToolError(f"Key Vault request failed: {e}") from e

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        raise ToolError(
            f"Key Vault rate limit exceeded. Retry after {retry_after} seconds."
        )

    if response.status_code >= 400:
        try:
            error_body = response.json()
            error_info = error_body.get("error", {})
            error_msg = error_info.get("message", response.text)
            error_code = error_info.get("code", "")
        except Exception:
            error_msg = response.text
            error_code = ""
        raise ToolError(
            f"Key Vault error ({response.status_code}"
            f"{f' {error_code}' if error_code else ''}): {error_msg}"
        )

    if response.status_code == 204:
        return {}

    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def register_tools(mcp: FastMCP) -> None:
    """Register all Key Vault tools."""

    if not KEYVAULT_URL:
        logger.warning(
            "KEYVAULT_URL not set — Key Vault tools will be registered "
            "but will fail at invocation until configured."
        )

    # --- Secrets (Step 3) ---
    # --- Keys (Step 4) ---
    # --- Certificates (Step 5) ---
```

Key differences from O365/Teams:
- **`_get_vault_url()`** — validates and returns the vault URL (vault-specific, not a fixed base URL)
- **`_get_http_client()`** — creates singleton with `base_url=_get_vault_url()` (called lazily, so vault URL can be unconfigured at import time)
- **`_request()` auto-appends `api-version=7.4`** to all requests via params
- **Own `_msal_app`** — uses `vault.azure.net` scope, separate from Graph API instances

---

## Step 3: Secrets (11 tools)

```python
    # --- Secrets ---

    @mcp.tool()
    async def kv_set_secret(
        name: str,
        value: str,
        content_type: str | None = None,
        enabled: bool = True,
        tags: dict | None = None,
    ) -> str:
        """Create or update a Key Vault secret.

        Args:
            name: Secret name
            value: Secret value
            content_type: Content type (e.g., text/plain)
            enabled: Whether secret is enabled
            tags: Key-value tags
        """
        body: dict = {"value": value, "attributes": {"enabled": enabled}}
        if content_type:
            body["contentType"] = content_type
        if tags:
            body["tags"] = tags
        data = await _request("PUT", f"/secrets/{name}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def kv_get_secret(name: str, version: str | None = None) -> str:
        """Get a Key Vault secret value.

        Args:
            name: Secret name
            version: Specific version (default: latest)
        """
        path = f"/secrets/{name}/{version}" if version else f"/secrets/{name}"
        data = await _request("GET", path)
        return _success(200, data=data)

    @mcp.tool()
    async def kv_list_secrets(max_results: int = 25) -> str:
        """List secrets in the vault (names only, no values).

        Args:
            max_results: Max results (default 25)
        """
        data = await _request("GET", "/secrets", params={"maxresults": str(max_results)})
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def kv_list_secret_versions(name: str, max_results: int = 25) -> str:
        """List all versions of a secret (no values).

        Args:
            name: Secret name
            max_results: Max results (default 25)
        """
        data = await _request(
            "GET", f"/secrets/{name}/versions",
            params={"maxresults": str(max_results)},
        )
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def kv_update_secret(
        name: str,
        version: str,
        enabled: bool | None = None,
        content_type: str | None = None,
        tags: dict | None = None,
    ) -> str:
        """Update secret attributes.

        Args:
            name: Secret name
            version: Secret version
            enabled: Enable/disable
            content_type: Content type
            tags: Key-value tags
        """
        body: dict = {}
        if enabled is not None:
            body.setdefault("attributes", {})["enabled"] = enabled
        if content_type is not None:
            body["contentType"] = content_type
        if tags is not None:
            body["tags"] = tags
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _request("PATCH", f"/secrets/{name}/{version}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def kv_delete_secret(name: str) -> str:
        """Delete a secret (soft-delete).

        Args:
            name: Secret name
        """
        data = await _request("DELETE", f"/secrets/{name}")
        return _success(200, data=data)

    @mcp.tool()
    async def kv_recover_secret(name: str) -> str:
        """Recover a soft-deleted secret.

        Args:
            name: Secret name
        """
        data = await _request("POST", f"/deletedsecrets/{name}/recover")
        return _success(200, data=data)

    @mcp.tool()
    async def kv_purge_secret(name: str) -> str:
        """Permanently delete a soft-deleted secret (irreversible).

        Args:
            name: Secret name
        """
        await _request("DELETE", f"/deletedsecrets/{name}")
        return _success(204, message="Secret purged")

    @mcp.tool()
    async def kv_list_deleted_secrets(max_results: int = 25) -> str:
        """List soft-deleted secrets.

        Args:
            max_results: Max results (default 25)
        """
        data = await _request(
            "GET", "/deletedsecrets", params={"maxresults": str(max_results)}
        )
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def kv_backup_secret(name: str) -> str:
        """Backup a secret (returns opaque blob).

        Args:
            name: Secret name
        """
        data = await _request("POST", f"/secrets/{name}/backup")
        return _success(200, data=data)

    @mcp.tool()
    async def kv_restore_secret(value: str) -> str:
        """Restore a secret from a backup blob.

        Args:
            value: Base64-encoded backup blob
        """
        data = await _request("POST", "/secrets/restore", json={"value": value})
        return _success(200, data=data)
```

---

## Step 4: Keys (18 tools)

```python
    # --- Keys ---

    @mcp.tool()
    async def kv_create_key(
        name: str,
        kty: str,
        key_size: int | None = None,
        crv: str | None = None,
        key_ops: list[str] | None = None,
    ) -> str:
        """Create a cryptographic key.

        Args:
            name: Key name
            kty: Key type (RSA, EC, oct, RSA-HSM, EC-HSM)
            key_size: Key size (2048, 3072, 4096 for RSA)
            crv: Curve (P-256, P-384, P-521 for EC)
            key_ops: Allowed operations (encrypt, decrypt, sign, verify, wrapKey, unwrapKey)
        """
        body: dict = {"kty": kty}
        if key_size is not None:
            body["key_size"] = key_size
        if crv is not None:
            body["crv"] = crv
        if key_ops is not None:
            body["key_ops"] = key_ops
        data = await _request("POST", f"/keys/{name}/create", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def kv_get_key(name: str, version: str | None = None) -> str:
        """Get a key's public component.

        Args:
            name: Key name
            version: Specific version (default: latest)
        """
        path = f"/keys/{name}/{version}" if version else f"/keys/{name}"
        data = await _request("GET", path)
        return _success(200, data=data)

    @mcp.tool()
    async def kv_list_keys(max_results: int = 25) -> str:
        """List keys in the vault.

        Args:
            max_results: Max results (default 25)
        """
        data = await _request("GET", "/keys", params={"maxresults": str(max_results)})
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def kv_list_key_versions(name: str, max_results: int = 25) -> str:
        """List all versions of a key.

        Args:
            name: Key name
            max_results: Max results (default 25)
        """
        data = await _request(
            "GET", f"/keys/{name}/versions", params={"maxresults": str(max_results)}
        )
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def kv_update_key(
        name: str,
        version: str,
        enabled: bool | None = None,
        tags: dict | None = None,
    ) -> str:
        """Update key attributes.

        Args:
            name: Key name
            version: Key version
            enabled: Enable/disable
            tags: Key-value tags
        """
        body: dict = {}
        if enabled is not None:
            body.setdefault("attributes", {})["enabled"] = enabled
        if tags is not None:
            body["tags"] = tags
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _request("PATCH", f"/keys/{name}/{version}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def kv_delete_key(name: str) -> str:
        """Delete a key (soft-delete).

        Args:
            name: Key name
        """
        data = await _request("DELETE", f"/keys/{name}")
        return _success(200, data=data)

    @mcp.tool()
    async def kv_recover_key(name: str) -> str:
        """Recover a soft-deleted key.

        Args:
            name: Key name
        """
        data = await _request("POST", f"/deletedkeys/{name}/recover")
        return _success(200, data=data)

    @mcp.tool()
    async def kv_purge_key(name: str) -> str:
        """Permanently delete a soft-deleted key (irreversible).

        Args:
            name: Key name
        """
        await _request("DELETE", f"/deletedkeys/{name}")
        return _success(204, message="Key purged")

    @mcp.tool()
    async def kv_list_deleted_keys(max_results: int = 25) -> str:
        """List soft-deleted keys.

        Args:
            max_results: Max results (default 25)
        """
        data = await _request(
            "GET", "/deletedkeys", params={"maxresults": str(max_results)}
        )
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def kv_rotate_key(name: str) -> str:
        """Rotate a key (creates new version per rotation policy).

        Args:
            name: Key name
        """
        data = await _request("POST", f"/keys/{name}/rotate")
        return _success(200, data=data)

    @mcp.tool()
    async def kv_encrypt(
        name: str, version: str, algorithm: str, value: str,
    ) -> str:
        """Encrypt data using a Key Vault key.

        Args:
            name: Key name
            version: Key version
            algorithm: Algorithm (e.g., RSA-OAEP, RSA-OAEP-256)
            value: Base64url-encoded plaintext
        """
        data = await _request(
            "POST", f"/keys/{name}/{version}/encrypt",
            json={"alg": algorithm, "value": value},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def kv_decrypt(
        name: str, version: str, algorithm: str, value: str,
    ) -> str:
        """Decrypt data using a Key Vault key.

        Args:
            name: Key name
            version: Key version
            algorithm: Algorithm
            value: Base64url-encoded ciphertext
        """
        data = await _request(
            "POST", f"/keys/{name}/{version}/decrypt",
            json={"alg": algorithm, "value": value},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def kv_sign(
        name: str, version: str, algorithm: str, value: str,
    ) -> str:
        """Sign a digest using a Key Vault key.

        Args:
            name: Key name
            version: Key version
            algorithm: Algorithm (e.g., RS256, ES256)
            value: Base64url-encoded digest
        """
        data = await _request(
            "POST", f"/keys/{name}/{version}/sign",
            json={"alg": algorithm, "value": value},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def kv_verify(
        name: str, version: str, algorithm: str, digest: str, signature: str,
    ) -> str:
        """Verify a signature using a Key Vault key.

        Args:
            name: Key name
            version: Key version
            algorithm: Algorithm
            digest: Base64url-encoded digest
            signature: Base64url-encoded signature
        """
        data = await _request(
            "POST", f"/keys/{name}/{version}/verify",
            json={"alg": algorithm, "digest": digest, "value": signature},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def kv_wrap_key(
        name: str, version: str, algorithm: str, value: str,
    ) -> str:
        """Wrap a symmetric key using a Key Vault key.

        Args:
            name: Key name
            version: Key version
            algorithm: Algorithm (e.g., RSA-OAEP)
            value: Base64url-encoded key to wrap
        """
        data = await _request(
            "POST", f"/keys/{name}/{version}/wrapkey",
            json={"alg": algorithm, "value": value},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def kv_unwrap_key(
        name: str, version: str, algorithm: str, value: str,
    ) -> str:
        """Unwrap a wrapped symmetric key.

        Args:
            name: Key name
            version: Key version
            algorithm: Algorithm
            value: Base64url-encoded wrapped key
        """
        data = await _request(
            "POST", f"/keys/{name}/{version}/unwrapkey",
            json={"alg": algorithm, "value": value},
        )
        return _success(200, data=data)

    @mcp.tool()
    async def kv_backup_key(name: str) -> str:
        """Backup a key (returns opaque blob).

        Args:
            name: Key name
        """
        data = await _request("POST", f"/keys/{name}/backup")
        return _success(200, data=data)

    @mcp.tool()
    async def kv_restore_key(value: str) -> str:
        """Restore a key from a backup blob.

        Args:
            value: Base64-encoded backup blob
        """
        data = await _request("POST", "/keys/restore", json={"value": value})
        return _success(200, data=data)
```

---

## Step 5: Certificates (10 tools)

```python
    # --- Certificates ---

    @mcp.tool()
    async def kv_get_certificate(name: str, version: str | None = None) -> str:
        """Get a certificate.

        Args:
            name: Certificate name
            version: Specific version (default: latest)
        """
        path = f"/certificates/{name}/{version}" if version else f"/certificates/{name}"
        data = await _request("GET", path)
        return _success(200, data=data)

    @mcp.tool()
    async def kv_list_certificates(max_results: int = 25) -> str:
        """List certificates in the vault.

        Args:
            max_results: Max results (default 25)
        """
        data = await _request(
            "GET", "/certificates", params={"maxresults": str(max_results)}
        )
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def kv_list_certificate_versions(name: str, max_results: int = 25) -> str:
        """List all versions of a certificate.

        Args:
            name: Certificate name
            max_results: Max results (default 25)
        """
        data = await _request(
            "GET", f"/certificates/{name}/versions",
            params={"maxresults": str(max_results)},
        )
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))

    @mcp.tool()
    async def kv_create_certificate(
        name: str,
        subject: str,
        validity_months: int = 12,
    ) -> str:
        """Create a self-signed certificate (async operation).

        Args:
            name: Certificate name
            subject: Subject (e.g., CN=example.com)
            validity_months: Validity in months (default 12)
        """
        body = {
            "policy": {
                "key_props": {"exportable": True, "kty": "RSA", "key_size": 2048},
                "secret_props": {"contentType": "application/x-pkcs12"},
                "x509_props": {
                    "subject": subject,
                    "validity_months": validity_months,
                },
                "issuer": {"name": "Self"},
            }
        }
        data = await _request("POST", f"/certificates/{name}/create", json=body)
        return _success(202, data=data)

    @mcp.tool()
    async def kv_import_certificate(
        name: str,
        value: str,
        password: str | None = None,
    ) -> str:
        """Import a PFX/PEM certificate.

        Args:
            name: Certificate name
            value: Base64-encoded certificate content
            password: PFX password
        """
        body: dict = {"value": value}
        if password is not None:
            body["pwd"] = password
        data = await _request("POST", f"/certificates/{name}/import", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def kv_update_certificate(
        name: str,
        version: str,
        enabled: bool | None = None,
        tags: dict | None = None,
    ) -> str:
        """Update certificate attributes.

        Args:
            name: Certificate name
            version: Certificate version
            enabled: Enable/disable
            tags: Key-value tags
        """
        body: dict = {}
        if enabled is not None:
            body.setdefault("attributes", {})["enabled"] = enabled
        if tags is not None:
            body["tags"] = tags
        if not body:
            raise ToolError("At least one field to update must be provided.")
        data = await _request("PATCH", f"/certificates/{name}/{version}", json=body)
        return _success(200, data=data)

    @mcp.tool()
    async def kv_delete_certificate(name: str) -> str:
        """Delete a certificate (soft-delete).

        Args:
            name: Certificate name
        """
        data = await _request("DELETE", f"/certificates/{name}")
        return _success(200, data=data)

    @mcp.tool()
    async def kv_recover_certificate(name: str) -> str:
        """Recover a soft-deleted certificate.

        Args:
            name: Certificate name
        """
        data = await _request("POST", f"/deletedcertificates/{name}/recover")
        return _success(200, data=data)

    @mcp.tool()
    async def kv_purge_certificate(name: str) -> str:
        """Permanently delete a soft-deleted certificate (irreversible).

        Args:
            name: Certificate name
        """
        await _request("DELETE", f"/deletedcertificates/{name}")
        return _success(204, message="Certificate purged")

    @mcp.tool()
    async def kv_list_deleted_certificates(max_results: int = 25) -> str:
        """List soft-deleted certificates.

        Args:
            max_results: Max results (default 25)
        """
        data = await _request(
            "GET", "/deletedcertificates", params={"maxresults": str(max_results)}
        )
        items = data.get("value", []) if isinstance(data, dict) else data
        return _success(200, data=items, count=len(items))
```

---

## Step 6: Registration

```python
from mcp_toolbox.tools import clickup_tool, example_tool, keyvault_tool, o365_tool, sendgrid_tool, teams_tool


def register_all_tools(mcp: FastMCP) -> None:
    example_tool.register_tools(mcp)
    sendgrid_tool.register_tools(mcp)
    clickup_tool.register_tools(mcp)
    o365_tool.register_tools(mcp)
    teams_tool.register_tools(mcp)
    keyvault_tool.register_tools(mcp)
```

---

## Step 7: Tests

Create `tests/test_keyvault_tool.py`. Uses respx with vault-specific base URL.

### Fixture
```python
"""Tests for Azure Key Vault tool integration."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from mcp_toolbox.tools.keyvault_tool import register_tools

VAULT_BASE = "https://testvault.vault.azure.net"


def _get_result_data(result) -> dict:
    return json.loads(result[0][0].text)


@pytest.fixture
def server():
    mcp = FastMCP("test")
    mock_msal = MagicMock()
    mock_msal.acquire_token_for_client.return_value = {"access_token": "kv-token"}
    with patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_TENANT_ID", "t"), \
         patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_CLIENT_ID", "c"), \
         patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_CLIENT_SECRET", "s"), \
         patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_URL", VAULT_BASE), \
         patch("mcp_toolbox.tools.keyvault_tool._msal_app", mock_msal), \
         patch("mcp_toolbox.tools.keyvault_tool._http_client", None):
        register_tools(mcp)
        yield mcp
```

### Test pattern (one per tool — 39 tests + auth/error tests)

All tests follow the same pattern. Representative samples:

```python
# --- Auth ---
@pytest.mark.asyncio
async def test_missing_vault_url():
    mcp = FastMCP("test")
    with patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_URL", None), \
         patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_TENANT_ID", "t"), \
         patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_CLIENT_ID", "c"), \
         patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_CLIENT_SECRET", "s"), \
         patch("mcp_toolbox.tools.keyvault_tool._msal_app", None), \
         patch("mcp_toolbox.tools.keyvault_tool._http_client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="KEYVAULT_URL"):
            await mcp.call_tool("kv_list_secrets", {})

# --- Secrets ---
@pytest.mark.asyncio
@respx.mock
async def test_set_secret(server):
    respx.put(f"{VAULT_BASE}/secrets/my-secret").mock(
        return_value=httpx.Response(200, json={"id": "...", "value": "val"})
    )
    result = await server.call_tool("kv_set_secret", {"name": "my-secret", "value": "val"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_get_secret(server):
    respx.get(f"{VAULT_BASE}/secrets/my-secret").mock(
        return_value=httpx.Response(200, json={"value": "secret-val"})
    )
    result = await server.call_tool("kv_get_secret", {"name": "my-secret"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_list_secrets(server):
    respx.get(f"{VAULT_BASE}/secrets").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "s1"}]})
    )
    result = await server.call_tool("kv_list_secrets", {})
    assert _get_result_data(result)["count"] == 1

# --- Keys ---
@pytest.mark.asyncio
@respx.mock
async def test_create_key(server):
    respx.post(f"{VAULT_BASE}/keys/my-key/create").mock(
        return_value=httpx.Response(200, json={"key": {"kid": "..."}})
    )
    result = await server.call_tool("kv_create_key", {"name": "my-key", "kty": "RSA"})
    assert _get_result_data(result)["status"] == "success"

@pytest.mark.asyncio
@respx.mock
async def test_encrypt(server):
    respx.post(f"{VAULT_BASE}/keys/my-key/v1/encrypt").mock(
        return_value=httpx.Response(200, json={"value": "encrypted"})
    )
    result = await server.call_tool("kv_encrypt", {
        "name": "my-key", "version": "v1", "algorithm": "RSA-OAEP", "value": "cGxhaW4=",
    })
    assert _get_result_data(result)["status"] == "success"

# --- Certificates ---
@pytest.mark.asyncio
@respx.mock
async def test_create_certificate(server):
    respx.post(f"{VAULT_BASE}/certificates/my-cert/create").mock(
        return_value=httpx.Response(202, json={"id": "..."})
    )
    result = await server.call_tool("kv_create_certificate", {
        "name": "my-cert", "subject": "CN=example.com",
    })
    assert _get_result_data(result)["status"] == "success"

# --- API Errors ---
@pytest.mark.asyncio
@respx.mock
async def test_api_error_403(server):
    respx.get(f"{VAULT_BASE}/secrets").mock(
        return_value=httpx.Response(403, json={
            "error": {"code": "Forbidden", "message": "Access denied"}
        })
    )
    with pytest.raises(Exception, match="Key Vault error.*403.*Access denied"):
        await server.call_tool("kv_list_secrets", {})
```

**Every one of the 39 tools must have at least one test.** The full test file follows the same respx mock + `_get_result_data` pattern shown above.

---

## Step 8: Update test_server.py

Add all 39 KV tool names and update count to 183:

```python
        # Key Vault tools (39)
        "kv_set_secret", "kv_get_secret", "kv_list_secrets",
        "kv_list_secret_versions", "kv_update_secret",
        "kv_delete_secret", "kv_recover_secret", "kv_purge_secret",
        "kv_list_deleted_secrets", "kv_backup_secret", "kv_restore_secret",
        "kv_create_key", "kv_get_key", "kv_list_keys", "kv_list_key_versions",
        "kv_update_key", "kv_delete_key", "kv_recover_key", "kv_purge_key",
        "kv_list_deleted_keys", "kv_rotate_key",
        "kv_encrypt", "kv_decrypt", "kv_sign", "kv_verify",
        "kv_wrap_key", "kv_unwrap_key", "kv_backup_key", "kv_restore_key",
        "kv_get_certificate", "kv_list_certificates",
        "kv_list_certificate_versions", "kv_create_certificate",
        "kv_import_certificate", "kv_update_certificate",
        "kv_delete_certificate", "kv_recover_certificate",
        "kv_purge_certificate", "kv_list_deleted_certificates",
```

Total assertion: `assert len(tools) == 183`

---

## Step 9: Documentation & Validation

### 9a. Update CLAUDE.md

### 9b. Run validation
```bash
uv run pytest -v
uv run ruff check src/ tests/
uv run pyright src/
```

---

## Execution Order

| Order | Step | Tools | Depends On |
|-------|------|-------|------------|
| 1 | Config | — | — |
| 2 | Foundation | helpers | Step 1 |
| 3 | Secrets | 11 | Step 2 |
| 4 | Keys | 18 | Step 2 |
| 5 | Certificates | 10 | Step 2 |
| 6 | Registration | — | Steps 3-5 |
| 7 | Tests | 41+ | Steps 3-6 |
| 8 | test_server.py | — | Steps 3-6 |
| 9 | Docs & validation | — | Steps 1-8 |

Steps 3-5 are independent.

---

## Risk Notes

- **Vault URL in httpx client:** `_get_http_client()` creates the singleton with `base_url=KEYVAULT_URL`. If KEYVAULT_URL changes at runtime (unlikely), the client won't update. Acceptable for MCP server lifecycle.
- **api-version auto-append:** `_request()` injects `api-version=7.4` into params. If a caller also passes `api-version` in params, it would be overwritten. Not a concern since no tool does this.
- **Purge operations return 204:** `kv_purge_secret`, `kv_purge_key`, `kv_purge_certificate` return empty body. The `_request()` helper returns `{}` for 204.
- **Certificate creation is async:** `kv_create_certificate` returns 202 with an operation status. The tool returns this directly — the caller would need to poll for completion. No polling tool is included (follow-up if needed).
- **`_get_vault_url()` called lazily:** The httpx client is created on first tool call, not at import. This means the vault URL can be unconfigured at startup without crashing.
