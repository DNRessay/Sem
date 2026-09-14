import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from config import settings
from gateway.auth import require_account
from gateway.connectors import _make_state, _verify_state
from main import app


class FakeStore:
    def __init__(self):
        self.connectors = {}  # (account_id, provider) -> dict

    async def list_connectors(self, account_id):
        return sorted(p for (a, p) in self.connectors if a == account_id)

    async def upsert_connector(self, account_id, provider, token, refresh_token=None, expires_at=None):
        self.connectors[(account_id, provider)] = {
            "token": token, "refresh_token": refresh_token, "expires_at": expires_at,
        }

    async def delete_connector(self, account_id, provider):
        self.connectors.pop((account_id, provider), None)

    async def get_connector(self, account_id, provider):
        c = self.connectors.get((account_id, provider))
        return {"provider": provider, **c} if c else None


@pytest.fixture
def client(monkeypatch):
    store = FakeStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.connectors.get_store", fake_get_store)
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app), store
    app.dependency_overrides.pop(require_account, None)


def test_save_and_list_connector(client):
    c, store = client
    resp = c.post("/connectors/github", json={"token": "ghp_test123"})
    assert resp.status_code == 200
    assert resp.json() == {"provider": "github", "connected": True}

    resp = c.get("/connectors")
    assert resp.json() == {"connectors": ["github"]}
    assert store.connectors[("owner", "github")]["token"] == "ghp_test123"


def test_save_connector_rejects_unknown_provider(client):
    c, _ = client
    resp = c.post("/connectors/bitbucket", json={"token": "x"})
    assert resp.status_code == 400


def test_save_connector_rejects_empty_token(client):
    c, _ = client
    resp = c.post("/connectors/github", json={"token": "  "})
    assert resp.status_code == 400


def test_delete_connector(client):
    c, store = client
    c.post("/connectors/gitlab", json={"token": "glpat_test"})
    resp = c.delete("/connectors/gitlab")
    assert resp.status_code == 200
    assert ("owner", "gitlab") not in store.connectors


def test_connectors_are_isolated_per_account(client):
    c, store = client
    c.post("/connectors/github", json={"token": "owner-token"})

    app.dependency_overrides[require_account] = lambda: {"account_id": "guest1", "role": "guest"}
    resp = c.get("/connectors")
    assert resp.json() == {"connectors": []}  # guest sees none of the owner's

    c.post("/connectors/github", json={"token": "guest-token"})
    assert store.connectors[("owner", "github")]["token"] == "owner-token"  # unchanged
    assert store.connectors[("guest1", "github")]["token"] == "guest-token"


def test_fetch_without_configured_connector_errors(client):
    c, _ = client
    resp = c.post("/connectors/github/fetch", json={"repo": "octocat/hello", "path": "README.md"})
    assert resp.status_code == 400
    assert "no github connector" in resp.json()["detail"].lower()


def test_fetch_requires_repo_and_path(client):
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    resp = c.post("/connectors/github/fetch", json={"repo": "", "path": ""})
    assert resp.status_code == 400


def test_authorize_errors_when_oauth_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "")
    c, _ = client
    resp = c.get("/connectors/github/authorize")
    assert resp.status_code == 400
    assert "isn't configured" in resp.json()["detail"].lower()


def test_authorize_returns_provider_consent_url(client, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "abc123")
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.example.com")
    c, _ = client
    resp = c.get("/connectors/github/authorize")
    assert resp.status_code == 200
    url = resp.json()["url"]
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=abc123" in url
    assert "redirect_uri=" in url
    assert "state=" in url


def test_state_round_trips_and_rejects_tampering():
    state = _make_state("github", "owner")
    assert _verify_state(state, "github") == "owner"
    assert _verify_state(state, "gitlab") is None  # wrong provider
    assert _verify_state(state + "x", "github") is None  # tampered


def test_state_carries_the_authorizing_account_not_just_owner():
    state = _make_state("github", "guest7")
    assert _verify_state(state, "github") == "guest7"


def test_callback_rejects_missing_or_invalid_state(client):
    c, _ = client
    resp = c.get("/connectors/github/callback", params={"code": "somecode", "state": "bogus"})
    assert resp.status_code == 200  # renders an HTML error page, not a raw error
    assert "failed" in resp.text.lower()


def test_callback_exchanges_code_and_stores_token_for_the_authorizing_account(client, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "abc123")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "shh")
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.example.com")
    c, store = client

    # A guest's own /authorize call would mint a state carrying their id —
    # the callback (no auth header available) must honor that, not silently
    # attribute the connection to whichever account is "current" server-side.
    state = _make_state("github", "guest3")
    with respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=Response(200, json={"access_token": "gho_realtoken", "token_type": "bearer"})
        )
        resp = c.get("/connectors/github/callback", params={"code": "realcode", "state": state})

    assert resp.status_code == 200
    assert "connected" in resp.text.lower()
    assert store.connectors[("guest3", "github")]["token"] == "gho_realtoken"
    assert ("owner", "github") not in store.connectors
