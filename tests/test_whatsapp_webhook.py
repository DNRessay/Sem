import pytest
from fastapi.testclient import TestClient

from main import app


class FakeBootstrap:
    def __init__(self, trust_mode="AUTO", tau_context=""):
        pass

    async def run(self, query, session_id, history, images=None, display_query=None, assistant_prefix=""):
        yield f"reply to: {query}"


@pytest.fixture
def client(monkeypatch):
    async def fake_observe_and_inject(session_id, query, history):
        return ""

    monkeypatch.setattr("gateway.webhooks._tau.observe_and_inject", fake_observe_and_inject)
    monkeypatch.setattr("gateway.webhooks.Bootstrap", FakeBootstrap)
    monkeypatch.setattr("config.settings.WHATSAPP_VERIFY_TOKEN", "my-verify-token")
    return TestClient(app)


def _message_payload(phone: str, text: str, msg_type: str = "text") -> dict:
    body = {"from": phone, "type": msg_type}
    if msg_type == "text":
        body["text"] = {"body": text}
    return {
        "entry": [{"changes": [{"value": {"messages": [body]}}]}],
    }


def test_verify_succeeds_with_matching_token(client):
    resp = client.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "my-verify-token", "hub.challenge": "12345",
    })
    assert resp.status_code == 200
    assert resp.text == "12345"


def test_verify_fails_with_wrong_token(client):
    resp = client.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345",
    })
    assert resp.status_code == 403


def test_verify_fails_when_token_unset(client, monkeypatch):
    monkeypatch.setattr("config.settings.WHATSAPP_VERIFY_TOKEN", "")
    resp = client.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "12345",
    })
    assert resp.status_code == 403


def test_inbound_text_message_routes_through_bootstrap_and_sends_a_reply(client, monkeypatch):
    calls = []

    class FakeWhatsAppTool:
        async def send(self, phone, message):
            calls.append((phone, message))
            return {"status": "sent"}

    monkeypatch.setattr("tools.misc.whatsapp_tool.WhatsAppTool", FakeWhatsAppTool)

    resp = client.post("/webhook/whatsapp", json=_message_payload("27821234567", "hello there"))
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert calls == [("27821234567", "reply to: hello there")]


def test_inbound_session_id_is_scoped_to_whatsapp_and_phone(client, monkeypatch):
    seen_sessions = []

    class RecordingBootstrap(FakeBootstrap):
        async def run(self, query, session_id, history, images=None, display_query=None, assistant_prefix=""):
            seen_sessions.append(session_id)
            yield "ok"

    class FakeWhatsAppTool:
        async def send(self, phone, message):
            return {"status": "sent"}

    monkeypatch.setattr("gateway.webhooks.Bootstrap", RecordingBootstrap)
    monkeypatch.setattr("tools.misc.whatsapp_tool.WhatsAppTool", FakeWhatsAppTool)

    client.post("/webhook/whatsapp", json=_message_payload("27821234567", "hi"))
    assert seen_sessions == ["whatsapp:27821234567"]


def test_non_text_messages_are_skipped(client, monkeypatch):
    calls = []

    class FakeWhatsAppTool:
        async def send(self, phone, message):
            calls.append((phone, message))
            return {"status": "sent"}

    monkeypatch.setattr("tools.misc.whatsapp_tool.WhatsAppTool", FakeWhatsAppTool)

    resp = client.post("/webhook/whatsapp", json=_message_payload("27821234567", "", msg_type="image"))
    assert resp.status_code == 200
    assert calls == []


def test_status_update_payload_with_no_messages_is_a_no_op(client):
    resp = client.post("/webhook/whatsapp", json={"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
