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


# --- Auth & Error ---


@pytest.mark.asyncio
async def test_missing_vault_url():
    mcp = FastMCP("test")
    mock_msal = MagicMock()
    mock_msal.acquire_token_for_client.return_value = {"access_token": "kv-token"}
    with patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_URL", None), \
         patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_TENANT_ID", "t"), \
         patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_CLIENT_ID", "c"), \
         patch("mcp_toolbox.tools.keyvault_tool.KEYVAULT_CLIENT_SECRET", "s"), \
         patch("mcp_toolbox.tools.keyvault_tool._msal_app", mock_msal), \
         patch("mcp_toolbox.tools.keyvault_tool._http_client", None):
        register_tools(mcp)
        with pytest.raises(Exception, match="KEYVAULT_URL"):
            await mcp.call_tool("kv_list_secrets", {})


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


@pytest.mark.asyncio
@respx.mock
async def test_api_error_429(server):
    respx.get(f"{VAULT_BASE}/secrets").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "5"})
    )
    with pytest.raises(Exception, match="rate limit.*5 seconds"):
        await server.call_tool("kv_list_secrets", {})


# --- Secrets ---


@pytest.mark.asyncio
@respx.mock
async def test_set_secret(server):
    route = respx.put(f"{VAULT_BASE}/secrets/my-secret").mock(
        return_value=httpx.Response(200, json={"id": "...", "value": "val"})
    )
    result = await server.call_tool("kv_set_secret", {"name": "my-secret", "value": "val"})
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["value"] == "val"
    assert body["attributes"]["enabled"] is True


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


@pytest.mark.asyncio
@respx.mock
async def test_list_secret_versions(server):
    respx.get(f"{VAULT_BASE}/secrets/my-secret/versions").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "v1"}]})
    )
    result = await server.call_tool("kv_list_secret_versions", {"name": "my-secret"})
    assert _get_result_data(result)["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_update_secret(server):
    route = respx.patch(f"{VAULT_BASE}/secrets/my-secret/v1").mock(
        return_value=httpx.Response(200, json={"id": "..."})
    )
    result = await server.call_tool("kv_update_secret", {
        "name": "my-secret", "version": "v1", "enabled": False,
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["attributes"]["enabled"] is False


@pytest.mark.asyncio
@respx.mock
async def test_delete_secret(server):
    respx.delete(f"{VAULT_BASE}/secrets/my-secret").mock(
        return_value=httpx.Response(200, json={"recoveryId": "..."})
    )
    result = await server.call_tool("kv_delete_secret", {"name": "my-secret"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_recover_secret(server):
    respx.post(f"{VAULT_BASE}/deletedsecrets/my-secret/recover").mock(
        return_value=httpx.Response(200, json={"id": "..."})
    )
    result = await server.call_tool("kv_recover_secret", {"name": "my-secret"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_purge_secret(server):
    respx.delete(f"{VAULT_BASE}/deletedsecrets/my-secret").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("kv_purge_secret", {"name": "my-secret"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_deleted_secrets(server):
    respx.get(f"{VAULT_BASE}/deletedsecrets").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    result = await server.call_tool("kv_list_deleted_secrets", {})
    assert _get_result_data(result)["count"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_backup_secret(server):
    respx.post(f"{VAULT_BASE}/secrets/my-secret/backup").mock(
        return_value=httpx.Response(200, json={"value": "backup-blob"})
    )
    result = await server.call_tool("kv_backup_secret", {"name": "my-secret"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_restore_secret(server):
    route = respx.post(f"{VAULT_BASE}/secrets/restore").mock(
        return_value=httpx.Response(200, json={"id": "..."})
    )
    result = await server.call_tool("kv_restore_secret", {"value": "backup-blob"})
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["value"] == "backup-blob"


# --- Keys ---


@pytest.mark.asyncio
@respx.mock
async def test_create_key(server):
    route = respx.post(f"{VAULT_BASE}/keys/my-key/create").mock(
        return_value=httpx.Response(200, json={"key": {"kid": "..."}})
    )
    result = await server.call_tool("kv_create_key", {"name": "my-key", "kty": "RSA"})
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["kty"] == "RSA"


@pytest.mark.asyncio
@respx.mock
async def test_get_key(server):
    respx.get(f"{VAULT_BASE}/keys/my-key").mock(
        return_value=httpx.Response(200, json={"key": {"kid": "..."}})
    )
    result = await server.call_tool("kv_get_key", {"name": "my-key"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_keys(server):
    respx.get(f"{VAULT_BASE}/keys").mock(
        return_value=httpx.Response(200, json={"value": [{"kid": "k1"}]})
    )
    result = await server.call_tool("kv_list_keys", {})
    assert _get_result_data(result)["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_key_versions(server):
    respx.get(f"{VAULT_BASE}/keys/my-key/versions").mock(
        return_value=httpx.Response(200, json={"value": [{"kid": "v1"}]})
    )
    result = await server.call_tool("kv_list_key_versions", {"name": "my-key"})
    assert _get_result_data(result)["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_update_key(server):
    route = respx.patch(f"{VAULT_BASE}/keys/my-key/v1").mock(
        return_value=httpx.Response(200, json={"key": {"kid": "..."}})
    )
    result = await server.call_tool("kv_update_key", {
        "name": "my-key", "version": "v1", "enabled": False,
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["attributes"]["enabled"] is False


@pytest.mark.asyncio
@respx.mock
async def test_delete_key(server):
    respx.delete(f"{VAULT_BASE}/keys/my-key").mock(
        return_value=httpx.Response(200, json={"recoveryId": "..."})
    )
    result = await server.call_tool("kv_delete_key", {"name": "my-key"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_recover_key(server):
    respx.post(f"{VAULT_BASE}/deletedkeys/my-key/recover").mock(
        return_value=httpx.Response(200, json={"key": {"kid": "..."}})
    )
    result = await server.call_tool("kv_recover_key", {"name": "my-key"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_purge_key(server):
    respx.delete(f"{VAULT_BASE}/deletedkeys/my-key").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("kv_purge_key", {"name": "my-key"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_deleted_keys(server):
    respx.get(f"{VAULT_BASE}/deletedkeys").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    result = await server.call_tool("kv_list_deleted_keys", {})
    assert _get_result_data(result)["count"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_rotate_key(server):
    respx.post(f"{VAULT_BASE}/keys/my-key/rotate").mock(
        return_value=httpx.Response(200, json={"key": {"kid": "..."}})
    )
    result = await server.call_tool("kv_rotate_key", {"name": "my-key"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_encrypt(server):
    route = respx.post(f"{VAULT_BASE}/keys/my-key/v1/encrypt").mock(
        return_value=httpx.Response(200, json={"value": "encrypted"})
    )
    result = await server.call_tool("kv_encrypt", {
        "name": "my-key", "version": "v1", "algorithm": "RSA-OAEP", "value": "cGxhaW4=",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["alg"] == "RSA-OAEP"
    assert body["value"] == "cGxhaW4="


@pytest.mark.asyncio
@respx.mock
async def test_decrypt(server):
    route = respx.post(f"{VAULT_BASE}/keys/my-key/v1/decrypt").mock(
        return_value=httpx.Response(200, json={"value": "decrypted"})
    )
    result = await server.call_tool("kv_decrypt", {
        "name": "my-key", "version": "v1", "algorithm": "RSA-OAEP", "value": "enc=",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["alg"] == "RSA-OAEP"
    assert body["value"] == "enc="


@pytest.mark.asyncio
@respx.mock
async def test_sign(server):
    route = respx.post(f"{VAULT_BASE}/keys/my-key/v1/sign").mock(
        return_value=httpx.Response(200, json={"value": "sig"})
    )
    result = await server.call_tool("kv_sign", {
        "name": "my-key", "version": "v1", "algorithm": "RS256", "value": "digest",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["alg"] == "RS256"
    assert body["value"] == "digest"


@pytest.mark.asyncio
@respx.mock
async def test_verify(server):
    route = respx.post(f"{VAULT_BASE}/keys/my-key/v1/verify").mock(
        return_value=httpx.Response(200, json={"value": True})
    )
    result = await server.call_tool("kv_verify", {
        "name": "my-key", "version": "v1", "algorithm": "RS256",
        "digest": "dig", "signature": "sig",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["alg"] == "RS256"
    assert body["digest"] == "dig"
    assert body["value"] == "sig"


@pytest.mark.asyncio
@respx.mock
async def test_wrap_key(server):
    route = respx.post(f"{VAULT_BASE}/keys/my-key/v1/wrapkey").mock(
        return_value=httpx.Response(200, json={"value": "wrapped"})
    )
    result = await server.call_tool("kv_wrap_key", {
        "name": "my-key", "version": "v1", "algorithm": "RSA-OAEP", "value": "key=",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["alg"] == "RSA-OAEP"
    assert body["value"] == "key="


@pytest.mark.asyncio
@respx.mock
async def test_unwrap_key(server):
    route = respx.post(f"{VAULT_BASE}/keys/my-key/v1/unwrapkey").mock(
        return_value=httpx.Response(200, json={"value": "unwrapped"})
    )
    result = await server.call_tool("kv_unwrap_key", {
        "name": "my-key", "version": "v1", "algorithm": "RSA-OAEP", "value": "wrapped=",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["alg"] == "RSA-OAEP"
    assert body["value"] == "wrapped="


@pytest.mark.asyncio
@respx.mock
async def test_backup_key(server):
    respx.post(f"{VAULT_BASE}/keys/my-key/backup").mock(
        return_value=httpx.Response(200, json={"value": "backup-blob"})
    )
    result = await server.call_tool("kv_backup_key", {"name": "my-key"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_restore_key(server):
    route = respx.post(f"{VAULT_BASE}/keys/restore").mock(
        return_value=httpx.Response(200, json={"key": {"kid": "..."}})
    )
    result = await server.call_tool("kv_restore_key", {"value": "backup-blob"})
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["value"] == "backup-blob"


# --- Certificates ---


@pytest.mark.asyncio
@respx.mock
async def test_get_certificate(server):
    respx.get(f"{VAULT_BASE}/certificates/my-cert").mock(
        return_value=httpx.Response(200, json={"id": "..."})
    )
    result = await server.call_tool("kv_get_certificate", {"name": "my-cert"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_certificates(server):
    respx.get(f"{VAULT_BASE}/certificates").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "c1"}]})
    )
    result = await server.call_tool("kv_list_certificates", {})
    assert _get_result_data(result)["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_list_certificate_versions(server):
    respx.get(f"{VAULT_BASE}/certificates/my-cert/versions").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "v1"}]})
    )
    result = await server.call_tool("kv_list_certificate_versions", {"name": "my-cert"})
    assert _get_result_data(result)["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_create_certificate(server):
    route = respx.post(f"{VAULT_BASE}/certificates/my-cert/create").mock(
        return_value=httpx.Response(202, json={"id": "..."})
    )
    result = await server.call_tool("kv_create_certificate", {
        "name": "my-cert", "subject": "CN=example.com",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["policy"]["x509_props"]["subject"] == "CN=example.com"
    assert body["policy"]["x509_props"]["validity_months"] == 12
    assert body["policy"]["key_props"]["kty"] == "RSA"
    assert body["policy"]["issuer"]["name"] == "Self"


@pytest.mark.asyncio
@respx.mock
async def test_import_certificate(server):
    route = respx.post(f"{VAULT_BASE}/certificates/my-cert/import").mock(
        return_value=httpx.Response(200, json={"id": "..."})
    )
    result = await server.call_tool("kv_import_certificate", {
        "name": "my-cert", "value": "base64-cert-content",
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["value"] == "base64-cert-content"


@pytest.mark.asyncio
@respx.mock
async def test_update_certificate(server):
    route = respx.patch(f"{VAULT_BASE}/certificates/my-cert/v1").mock(
        return_value=httpx.Response(200, json={"id": "..."})
    )
    result = await server.call_tool("kv_update_certificate", {
        "name": "my-cert", "version": "v1", "enabled": False,
    })
    assert _get_result_data(result)["status"] == "success"
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["attributes"]["enabled"] is False


@pytest.mark.asyncio
@respx.mock
async def test_delete_certificate(server):
    respx.delete(f"{VAULT_BASE}/certificates/my-cert").mock(
        return_value=httpx.Response(200, json={"recoveryId": "..."})
    )
    result = await server.call_tool("kv_delete_certificate", {"name": "my-cert"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_recover_certificate(server):
    respx.post(f"{VAULT_BASE}/deletedcertificates/my-cert/recover").mock(
        return_value=httpx.Response(200, json={"id": "..."})
    )
    result = await server.call_tool("kv_recover_certificate", {"name": "my-cert"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_purge_certificate(server):
    respx.delete(f"{VAULT_BASE}/deletedcertificates/my-cert").mock(
        return_value=httpx.Response(204)
    )
    result = await server.call_tool("kv_purge_certificate", {"name": "my-cert"})
    assert _get_result_data(result)["status"] == "success"


@pytest.mark.asyncio
@respx.mock
async def test_list_deleted_certificates(server):
    respx.get(f"{VAULT_BASE}/deletedcertificates").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    result = await server.call_tool("kv_list_deleted_certificates", {})
    assert _get_result_data(result)["count"] == 0
