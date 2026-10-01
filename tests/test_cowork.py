import json

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from agents.cowork_agent import CoworkAgent
from gateway.auth import require_account
from main import app

GROQ = "https://api.groq.com/openai/v1/chat/completions"


@pytest.fixture(autouse=True)
def groq_only(monkeypatch):
    from config import settings
    for name in ("LOCAL_LLM_URL", "GEMINI_API_KEY"):
        monkeypatch.setattr(settings, name, "")


def _call(cid, name, args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _reply(content="", calls=None):
    return Response(200, json={"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": calls}}]})


@pytest.mark.asyncio
async def test_email_is_queued_for_approval_not_sent(monkeypatch):
    sent = []

    async def fake_query(self, action, **kw):
        sent.append(action)
        return {}

    monkeypatch.setattr("agents.cowork_agent.GmailTool.query", fake_query)
    with respx.mock:
        respx.post(GROQ).mock(side_effect=[
            _reply("", [_call("c1", "gmail_send", {"to": "a@b.co", "subject": "Hi", "body": "Hello"})]),
            _reply("Drafted — waiting for your approval."),
        ])
        events = [e async for e in CoworkAgent("owner").run("email a@b.co")]

    assert sent == []
    approval = next(e for e in events if e["type"] == "approval")
    assert approval["name"] == "gmail_send" and approval["args"]["to"] == "a@b.co"
    assert "a@b.co" in approval["summary"]


@pytest.mark.asyncio
async def test_generated_image_goes_to_the_ui_but_not_back_to_the_model(monkeypatch):
    async def fake_image(prompt, aspect_ratio="1:1"):
        return {"ok": True, "mime": "image/png", "base64": "QUJD" * 1000}

    monkeypatch.setattr("agents.cowork_agent.gemini_media.generate_image", fake_image)
    with respx.mock:
        route = respx.post(GROQ).mock(side_effect=[
            _reply("", [_call("c1", "generate_image", {"prompt": "a flyer", "aspect_ratio": "4:5"})]),
            _reply("Here's your flyer."),
        ])
        events = [e async for e in CoworkAgent("owner").run("make a flyer")]

    image = next(e for e in events if e["type"] == "image")
    assert image["base64"].startswith("QUJD") and image["prompt"] == "a flyer"
    tool_msg = [m for m in json.loads(route.calls[1].request.content)["messages"] if m["role"] == "tool"][0]
    assert "QUJD" not in tool_msg["content"]
    result = next(e for e in events if e["type"] == "result")
    assert "QUJD" not in result["output"]


@pytest.mark.asyncio
async def test_web_search_tool_uses_searxng_when_configured(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "SEARXNG_URL", "https://search.example")
    with respx.mock:
        respx.get("https://search.example/search").mock(return_value=Response(200, json={
            "results": [{"title": "T", "url": "https://x.co", "content": "snippet"}]}))
        result = await CoworkAgent("owner").dispatch("web_search", {"query": "seo tips"})
    assert result == {"ok": True, "engine": "searxng", "results": [{"title": "T", "url": "https://x.co", "snippet": "snippet"}]}


@pytest.fixture
def client():
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app)
    app.dependency_overrides.pop(require_account, None)


def test_execute_only_runs_approvable_actions(client, monkeypatch):
    calls = []

    async def fake_run(name, args, account_id):
        calls.append((name, args, account_id))
        return {"id": "m1"}

    monkeypatch.setattr("gateway.cowork_router.run_approved", fake_run)
    assert client.post("/cowork/execute", json={"name": "drive_read", "args": {}}).status_code == 400
    r = client.post("/cowork/execute", json={"name": "gmail_send", "args": {"to": "a@b.co", "subject": "s", "body": "b"}})
    assert r.status_code == 200 and calls == [("gmail_send", {"to": "a@b.co", "subject": "s", "body": "b"}, "owner")]
