import pytest
from fastapi.testclient import TestClient

from gateway.auth import require_account
from main import app


class Store:
    def __init__(self):
        self.model = {"name": "Miguel", "ocean": {"O": 0.7}}
        self.mems = [{"id": 1, "session_id": "s", "content": "ams is abel motshoane", "salience": 0.5, "created_at": 1}]
        self.rems = [{"id": 5, "message": "call bank", "due_at": 2}]

    async def get_user_model(self, sid):
        return self.model

    async def save_user_model(self, sid, model):
        self.model = model

    async def search_memories(self, q, limit=50):
        return [m for m in self.mems if q.lower() in m["content"]]

    async def count_memories(self):
        return len(self.mems)

    async def delete_memory(self, mid):
        before = len(self.mems)
        self.mems = [m for m in self.mems if m["id"] != mid]
        return len(self.mems) < before

    async def list_reminders(self, account_id):
        return self.rems

    async def delete_reminder(self, account_id, rid):
        return rid == 5

    async def count_sessions_since(self, ts):
        return 3

    async def list_code_automations(self, account_id):
        return []

    async def list_mcp_servers(self, account_id):
        return []


@pytest.fixture
def client(monkeypatch):
    store = Store()

    async def fake():
        return store

    monkeypatch.setattr("gateway.settings_router.get_store", fake)
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app), store
    app.dependency_overrides.pop(require_account, None)


def test_profile_round_trip_keeps_other_fields(client):
    c, store = client
    r = c.put("/settings/profile", json={"call_me": "Sir Le Roy", "work": "Engineering", "evil": "x"})
    assert r.json()["call_me"] == "Sir Le Roy" and "evil" not in store.model
    assert store.model["ocean"] == {"O": 0.7} and store.model["name"] == "Miguel"
    assert c.get("/settings/profile").json()["work"] == "Engineering"


def test_memory_search_and_forget(client):
    c, _ = client
    assert c.get("/settings/memory", params={"q": "ams"}).json()["total"] == 1
    assert c.delete("/settings/memory/1").json() == {"ok": True}
    assert c.delete("/settings/memory/1").status_code == 404


def test_reminders_and_usage(client):
    c, _ = client
    assert c.get("/settings/reminders").json()["reminders"][0]["message"] == "call bank"
    assert c.delete("/settings/reminders/9").status_code == 404
    u = c.get("/settings/usage").json()
    assert u["chats_30d"] == 3 and u["memories"] == 1 and u["reminders"] == 1
