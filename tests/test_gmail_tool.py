import pytest
import respx
from httpx import Response

from tools.google.gmail_tool import GmailTool

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


@pytest.mark.asyncio
async def test_query_returns_error_when_not_connected(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return {"error": "No Google connector configured for this account — connect Google first (Gmail needs it)."}

    monkeypatch.setattr("tools.google.gmail_tool.get_google_token", fake_get_token)
    result = await GmailTool().query("list_messages")
    assert "connect Google first" in result["error"]


@pytest.mark.asyncio
async def test_list_messages_fetches_metadata_for_each_id(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.gmail_tool.get_google_token", fake_get_token)
    with respx.mock:
        respx.get(f"{BASE}/messages").mock(return_value=Response(200, json={"messages": [{"id": "m1"}, {"id": "m2"}]}))
        respx.get(f"{BASE}/messages/m1").mock(return_value=Response(200, json={
            "id": "m1", "snippet": "hello there",
            "payload": {"headers": [{"name": "From", "value": "a@x.com"}, {"name": "Subject", "value": "Hi"}]},
        }))
        respx.get(f"{BASE}/messages/m2").mock(return_value=Response(200, json={
            "id": "m2", "snippet": "second one",
            "payload": {"headers": [{"name": "From", "value": "b@x.com"}, {"name": "Subject", "value": "Yo"}]},
        }))
        result = await GmailTool().query("list_messages")

    assert result == {"messages": [
        {"id": "m1", "from": "a@x.com", "subject": "Hi", "date": None, "snippet": "hello there"},
        {"id": "m2", "from": "b@x.com", "subject": "Yo", "date": None, "snippet": "second one"},
    ]}


@pytest.mark.asyncio
async def test_read_message_requires_message_id(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.gmail_tool.get_google_token", fake_get_token)
    result = await GmailTool().query("read_message")
    assert result == {"error": "message_id required"}


@pytest.mark.asyncio
async def test_read_message_extracts_plain_text_body(monkeypatch):
    import base64
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.gmail_tool.get_google_token", fake_get_token)
    encoded = base64.urlsafe_b64encode(b"the actual body text").decode()
    with respx.mock:
        respx.get(f"{BASE}/messages/m1").mock(return_value=Response(200, json={
            "id": "m1", "snippet": "...",
            "payload": {
                "headers": [{"name": "From", "value": "a@x.com"}, {"name": "Subject", "value": "Hi"}],
                "mimeType": "text/plain",
                "body": {"data": encoded},
            },
        }))
        result = await GmailTool().query("read_message", message_id="m1")

    assert result["body"] == "the actual body text"


@pytest.mark.asyncio
async def test_read_message_extracts_body_from_multipart(monkeypatch):
    import base64
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.gmail_tool.get_google_token", fake_get_token)
    encoded = base64.urlsafe_b64encode(b"multipart body").decode()
    with respx.mock:
        respx.get(f"{BASE}/messages/m1").mock(return_value=Response(200, json={
            "id": "m1", "snippet": "...",
            "payload": {
                "headers": [],
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/html", "body": {"data": "aGVsbG8="}},
                    {"mimeType": "text/plain", "body": {"data": encoded}},
                ],
            },
        }))
        result = await GmailTool().query("read_message", message_id="m1")

    assert result["body"] == "multipart body"


@pytest.mark.asyncio
async def test_send_message_requires_to(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.gmail_tool.get_google_token", fake_get_token)
    result = await GmailTool().query("send_message", subject="hi", body="hello")
    assert result == {"error": "to required"}


@pytest.mark.asyncio
async def test_send_message_posts_base64_encoded_mime(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.gmail_tool.get_google_token", fake_get_token)
    with respx.mock:
        route = respx.post(f"{BASE}/messages/send").mock(return_value=Response(200, json={"id": "sent1"}))
        result = await GmailTool().query("send_message", to="dest@x.com", subject="Hello", body="hi there")

    assert result == {"id": "sent1", "sent_to": "dest@x.com", "subject": "Hello"}
    import json
    body = json.loads(route.calls[0].request.content)
    assert "raw" in body


@pytest.mark.asyncio
async def test_unknown_action_returns_a_clear_error(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.gmail_tool.get_google_token", fake_get_token)
    result = await GmailTool().query("delete_everything")
    assert "Unknown gmail action" in result["error"]
