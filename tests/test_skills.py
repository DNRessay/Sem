import pytest
from fastapi.testclient import TestClient

from gateway.auth import require_account
from main import app


class FakeStore:
    def __init__(self):
        self.skills = {}

    async def list_skills(self, enabled_only: bool = False):
        rows = list(self.skills.values())
        if enabled_only:
            rows = [s for s in rows if s["enabled"]]
        return rows

    async def upsert_skill(self, skill_id, name, triggers, content, enabled=True):
        self.skills[skill_id] = {
            "id": skill_id, "name": name, "triggers": triggers,
            "content": content, "enabled": enabled,
        }

    async def delete_skill(self, skill_id):
        self.skills.pop(skill_id, None)


@pytest.fixture
def client(monkeypatch):
    store = FakeStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.skills.get_store", fake_get_store)
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app), store
    app.dependency_overrides.pop(require_account, None)


def test_create_skill_lowercases_triggers_and_generates_id(client):
    c, store = client
    resp = c.post("/skills", json={
        "name": "Deploy checklist",
        "triggers": "Deploy, Release, Ship It",
        "content": "Always run tests before deploying.",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Deploy checklist"
    assert body["triggers"] == ["deploy", "release", "ship it"]
    assert body["id"] in store.skills


def test_create_skill_requires_name_and_content(client):
    c, _ = client
    resp = c.post("/skills", json={"name": "", "content": ""})
    assert resp.status_code == 400


def test_list_skills(client):
    c, store = client
    c.post("/skills", json={"name": "A", "content": "content a", "triggers": ["a"]})
    resp = c.get("/skills")
    assert resp.status_code == 200
    assert len(resp.json()["skills"]) == 1


def test_delete_skill(client):
    c, store = client
    created = c.post("/skills", json={"name": "A", "content": "content a", "triggers": ["a"]}).json()
    resp = c.delete(f"/skills/{created['id']}")
    assert resp.status_code == 200
    assert created["id"] not in store.skills
