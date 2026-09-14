import pytest
from fastapi.testclient import TestClient

from gateway.auth import require_account
from main import app


class FakeStore:
    def __init__(self):
        self.connectors = {}

    async def list_connectors(self):
        return sorted(self.connectors.keys())

    async def upsert_connector(self, provider, token):
        self.connectors[provider] = token

    async def delete_connector(self, provider):
        self.connectors.pop(provider, None)

    async def get_connector(self, provider):
        token = self.connectors.get(provider)
        return {"provider": provider, "token": token} if token else None


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
    assert store.connectors["github"] == "ghp_test123"


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
    assert "gitlab" not in store.connectors


def test_fetch_without_configured_connector_errors(client):
    c, _ = client
    resp = c.post("/connectors/github/fetch", json={"repo": "octocat/hello", "path": "README.md"})
    assert resp.status_code == 400
    assert "no github connector" in resp.json()["detail"].lower()


def test_fetch_requires_repo_and_path(client):
    c, store = client
    store.connectors["github"] = "ghp_test"
    resp = c.post("/connectors/github/fetch", json={"repo": "", "path": ""})
    assert resp.status_code == 400
