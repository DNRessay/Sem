import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from gateway.auth import require_account
from main import app
from pipeline import bots


class FakeStore:
    def __init__(self):
        self.kv, self.connectors = {}, {}

    async def get_state(self, key):
        return self.kv.get(key)

    async def set_state(self, key, value):
        self.kv[key] = value

    async def upsert_connector(self, account_id, provider, token, refresh_token=None, expires_at=None):
        self.connectors[(account_id, provider)] = {"token": token, "refresh_token": refresh_token}

    async def get_connector(self, account_id, provider):
        return self.connectors.get((account_id, provider))

    async def delete_connector(self, account_id, provider):
        self.connectors.pop((account_id, provider), None)


@pytest.fixture
def store(monkeypatch):
    s = FakeStore()

    async def get_store():
        return s

    monkeypatch.setattr("pipeline.bots.get_store", get_store)
    return s


@pytest.fixture
def client(store):
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app)
    app.dependency_overrides.pop(require_account, None)


def test_whatsapp_never_gets_private_or_approval_tools_for_strangers():
    bot = bots.clean_bot({"name": "Helper", "tools": ["web_search", "gmail_search", "gmail_send", "generate_image", "nope"]})
    assert bot["tools"] == ["web_search", "gmail_search", "gmail_send", "generate_image"]
    assert bots.tools_for(bot, "app", False) == bot["tools"]
    assert bots.tools_for(bot, "whatsapp", False) == ["web_search"]
    assert bots.tools_for(bot, "whatsapp", True) == ["web_search", "gmail_search"]  # trusted: no gmail_send


def test_create_update_and_list_bots_without_leaking_secrets(client, store):
    b = client.post("/bots", json={"name": "Bakery helper", "instructions": "Answer about bread", "tools": ["web_search"]}).json()
    assert b["name"] == "Bakery helper" and b["whatsapp"]["webhook_url"].endswith(f"/webhook/bots/{b['id']}")
    assert store.kv[f"bot_owner:{b['id']}"] == "owner"
    upd = client.put(f"/bots/{b['id']}", json={"greeting": "Hi! Fresh bread today."}).json()
    assert upd["greeting"] == "Hi! Fresh bread today." and upd["instructions"] == "Answer about bread"
    listed = client.get("/bots").json()
    assert [x["id"] for x in listed["bots"]] == [b["id"]] and "access_token" not in json.dumps(listed["bots"])
    assert client.delete(f"/bots/{b['id']}").json() == {"ok": True}
    assert client.get("/bots").json()["bots"] == []


def test_botfather_draft(client, monkeypatch):
    async def fake_complete(model, messages, **kw):
        return {"content": '```json\n{"name": "Rosie", "emoji": "🍞", "about": "Bakery bot", "greeting": "Hi!",'
                           ' "instructions": "You help customers of Vicinic Bakes.", "tools": ["web_search"],}\n```'}

    monkeypatch.setattr(bots.llm_providers, "complete", fake_complete)
    d = client.post("/bots/draft", json={"description": "a bot for my bakery's WhatsApp"}).json()
    assert d["bot"]["name"] == "Rosie" and d["bot"]["tools"] == ["web_search"]
    assert client.post("/bots/draft", json={"description": ""}).status_code == 400


def _signed(secret, payload):
    raw = json.dumps(payload).encode()
    return raw, "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def test_whatsapp_bot_connects_verifies_and_answers_once(client, store, monkeypatch):
    graph = []

    async def fake_graph(method, path, token, **kw):
        graph.append((method, path, kw.get("json")))
        return {"display_phone_number": "+27 60 000 0000"} if method == "GET" else {"messages": [{"id": "x"}]}

    seen_tools = {}

    class FakeAgent:
        def __init__(self, account_id, bot, channel, trusted=False, deadline_seconds=None, mcp=None):
            seen_tools["tools"] = bots.tools_for(bot, channel, trusted)

        async def run(self, text, history):
            seen_tools["history"] = history
            yield {"type": "text", "text": f"You said: {text}"}

    monkeypatch.setattr("gateway.bots_router._graph", fake_graph)
    monkeypatch.setattr("gateway.bots_router.bots.BotAgent", FakeAgent)
    b = client.post("/bots", json={"name": "Rosie", "tools": ["web_search", "gmail_search"]}).json()
    assert client.post(f"/bots/{b['id']}/whatsapp", json={"phone_number_id": "123"}).status_code == 400  # no token
    c = client.post(f"/bots/{b['id']}/whatsapp", json={"phone_number_id": "123", "token": "EAAT", "app_secret": "shh"}).json()
    assert c["whatsapp"]["connected"] and c["whatsapp"]["display_number"] == "+27 60 000 0000"
    assert "EAAT" not in json.dumps(client.get("/bots").json()) and "shh" not in json.dumps(c)  # secrets stay server-side
    vt = c["whatsapp"]["verify_token"]
    ok = client.get(f"/webhook/bots/{b['id']}", params={"hub.mode": "subscribe", "hub.verify_token": vt, "hub.challenge": "42"})
    assert ok.text == "42"
    assert client.get(f"/webhook/bots/{b['id']}", params={"hub.mode": "subscribe", "hub.verify_token": "bad"}).status_code == 403

    payload = {"entry": [{"changes": [{"value": {"messages": [{"id": "wamid.1", "from": "27821234567", "type": "text",
                                                               "text": {"body": "Do you have rye?"}}]}}]}]}
    raw, sig = _signed("shh", payload)
    assert client.post(f"/webhook/bots/{b['id']}", content=raw, headers={"x-hub-signature-256": "sha256=bad"}).status_code == 401
    r = client.post(f"/webhook/bots/{b['id']}", content=raw, headers={"x-hub-signature-256": sig}).json()
    assert r["answered"] == 1 and seen_tools["tools"] == ["web_search"]  # a stranger: no Gmail
    assert graph[-1] == ("POST", "123/messages", {"messaging_product": "whatsapp", "to": "27821234567", "type": "text",
                                                  "text": {"body": "You said: Do you have rye?"}})
    again = client.post(f"/webhook/bots/{b['id']}", content=raw, headers={"x-hub-signature-256": sig}).json()
    assert again["answered"] == 0  # Meta's retry isn't answered twice
    hist = json.loads(store.kv[f"botchat:{b['id']}:27821234567"])
    assert [h["role"] for h in hist] == ["user", "assistant"]
