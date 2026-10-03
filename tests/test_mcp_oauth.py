import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from gateway import mcp_oauth
from gateway.passphrase import hash_passphrase
from main import app

CALLBACK = "https://claude.ai/api/mcp/auth_callback"


class Store:
    async def get_account(self, account_id):
        return {"id": "owner", "role": "owner", "passphrase_hash": hash_passphrase("open sesame"), "token_version": 0}

    async def get_token_version(self, account_id):
        return 0


@pytest.fixture
def client(monkeypatch):
    async def store():
        return Store()

    monkeypatch.setattr("gateway.oauth_router.get_store", store)
    monkeypatch.setattr("storage.neon_store.get_store", store)
    from gateway import ratelimit
    monkeypatch.setattr(ratelimit, "blocked", lambda *a: False)
    monkeypatch.setattr(ratelimit, "record", lambda *a: None)
    monkeypatch.setattr(ratelimit, "clear", lambda *a: None)
    return TestClient(app)


def _pkce():
    verifier = "v" * 64
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _sign_in(client, client_id, challenge, passphrase="open sesame"):
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": CALLBACK, "state": "xyz",
              "code_challenge": challenge, "code_challenge_method": "S256"}
    assert "Connect" in client.get("/oauth/authorize", params=params).text
    return client.post("/oauth/authorize", data={**params, "passphrase": passphrase}, follow_redirects=False)


def test_claude_connects_with_dynamic_registration(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401 and "resource_metadata=" in r.headers["www-authenticate"]
    meta = client.get("/.well-known/oauth-protected-resource").json()
    server = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["resource"].endswith("/mcp") and server["code_challenge_methods_supported"] == ["S256"]

    reg = client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [CALLBACK]}).json()
    verifier, challenge = _pkce()
    assert _sign_in(client, reg["client_id"], challenge, "wrong").status_code == 401
    back = _sign_in(client, reg["client_id"], challenge)
    assert back.status_code == 302 and back.headers["location"].startswith(CALLBACK)
    q = parse_qs(urlparse(back.headers["location"]).query)
    assert q["state"] == ["xyz"]

    form = {"grant_type": "authorization_code", "code": q["code"][0], "client_id": reg["client_id"], "redirect_uri": CALLBACK}
    assert client.post("/oauth/token", data={**form, "code_verifier": "x" * 64}).json()["error"] == "invalid_grant"
    tok = client.post("/oauth/token", data={**form, "code_verifier": verifier}).json()
    assert tok["token_type"] == "Bearer"
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Authorization": f"Bearer {tok['access_token']}"})
    assert r.status_code == 200 and r.json()["result"]["tools"]


def test_own_client_id_and_secret(client):
    page = client.post("/oauth/client", data={"passphrase": "open sesame"}).text
    creds = mcp_oauth.own_client("semblance", "test-secret")
    assert creds["client_id"] in page and creds["client_secret"] in page
    assert "Incorrect passphrase" in client.post("/oauth/client", data={"passphrase": "nope"}).text
    verifier, challenge = _pkce()
    q = parse_qs(urlparse(_sign_in(client, creds["client_id"], challenge).headers["location"]).query)
    form = {"grant_type": "authorization_code", "code": q["code"][0], "client_id": creds["client_id"],
            "redirect_uri": CALLBACK, "code_verifier": verifier}
    assert client.post("/oauth/token", data={**form, "client_secret": "bad"}).json()["error"] == "invalid_client"
    basic = base64.b64encode(f"{creds['client_id']}:{creds['client_secret']}".encode()).decode()
    assert client.post("/oauth/token", data=form, headers={"Authorization": f"Basic {basic}"}).json()["access_token"]


def test_bad_requests_never_redirect(client):
    r = client.get("/oauth/authorize", params={"response_type": "code", "client_id": "forged.sig",
                                                "redirect_uri": "https://evil.example/cb", "code_challenge": "c"})
    assert r.status_code == 400 and "Can't connect" in r.text
    reg = client.post("/oauth/register", json={"redirect_uris": [CALLBACK]}).json()
    r = client.get("/oauth/authorize", params={"response_type": "code", "client_id": reg["client_id"],
                                                "redirect_uri": "https://evil.example/cb", "code_challenge": "c"})
    assert r.status_code == 400
    assert client.post("/oauth/register", json={"redirect_uris": ["http://evil.example/cb"]}).status_code == 400
    tampered = mcp_oauth.sign("code", {"u": "owner"}, "other-secret")
    assert mcp_oauth.unsign("code", tampered, "test-secret") is None
