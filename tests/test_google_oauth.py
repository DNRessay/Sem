import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from config import settings
from gateway.auth import require_account
from gateway.connectors import _make_state
from main import app


class FakeStore:
    def __init__(self):
        self.connectors = {}

    async def upsert_connector(self, account_id, provider, token, refresh_token=None, expires_at=None):
        self.connectors[(account_id, provider)] = {
            "token": token, "refresh_token": refresh_token, "expires_at": expires_at,
        }

    async def get_connector(self, account_id, provider):
        c = self.connectors.get((account_id, provider))
        return {"provider": provider, **c} if c else None

    async def list_connectors(self, account_id):
        return sorted(p for (a, p) in self.connectors if a == account_id)


@pytest.fixture
def client(monkeypatch):
    store = FakeStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.google_oauth.get_store", fake_get_store)
    monkeypatch.setattr("gateway.connectors.get_store", fake_get_store)
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app), store
    app.dependency_overrides.pop(require_account, None)


def test_authorize_errors_when_oauth_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    c, _ = client
    resp = c.get("/connectors/google/authorize")
    assert resp.status_code == 400
    assert "isn't configured" in resp.json()["detail"].lower()


def test_authorize_returns_a_consent_url_with_offline_access_and_all_scopes(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "abc123")
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.example.com")
    c, _ = client
    resp = c.get("/connectors/google/authorize")
    assert resp.status_code == 200
    url = resp.json()["url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=abc123" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=" in url
    # every scope from every Google tool this app has, not just calendar
    assert "calendar" in url
    assert "gmail.readonly" in url
    assert "gmail.send" in url
    assert "drive.file" in url
    assert "contacts.readonly" in url


def test_callback_rejects_missing_or_invalid_state(client):
    c, _ = client
    resp = c.get("/connectors/google/callback", params={"code": "somecode", "state": "bogus"})
    assert resp.status_code == 200  # renders an HTML error page, not a raw error
    assert "failed" in resp.text.lower()


def test_callback_exchanges_code_and_stores_token_with_refresh_token(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "abc123")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "shh")
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.example.com")
    c, store = client

    state = _make_state("google", "owner")
    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=Response(200, json={
                "access_token": "ya29.realtoken", "refresh_token": "1//real-refresh",
                "expires_in": 3599, "token_type": "Bearer",
            })
        )
        resp = c.get("/connectors/google/callback", params={"code": "realcode", "state": state})

    assert resp.status_code == 200
    assert "connected" in resp.text.lower()
    stored = store.connectors[("owner", "google")]
    assert stored["token"] == "ya29.realtoken"
    assert stored["refresh_token"] == "1//real-refresh"
    assert stored["expires_at"] is not None


def test_callback_surfaces_a_google_error_param(client):
    c, _ = client
    resp = c.get("/connectors/google/callback", params={"error": "access_denied", "error_description": "User denied access"})
    assert resp.status_code == 200
    assert "failed" in resp.text.lower()


def test_callback_handles_a_response_with_no_access_token(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "abc123")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "shh")
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.example.com")
    c, _ = client

    state = _make_state("google", "owner")
    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=Response(200, json={"error": "invalid_grant"})
        )
        resp = c.get("/connectors/google/callback", params={"code": "badcode", "state": state})

    assert resp.status_code == 200
    assert "failed" in resp.text.lower()
