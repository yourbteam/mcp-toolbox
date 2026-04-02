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
        data = await _request(
            "GET", "/secrets", params={"maxresults": str(max_results)}
        )
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
            "GET", f"/keys/{name}/versions",
            params={"maxresults": str(max_results)},
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
