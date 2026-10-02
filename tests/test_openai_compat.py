import json

import pytest
from fastapi.testclient import TestClient

from gateway.auth import issue_token
from main import app


class FakeBootstrap:
    seen = {}

    def __init__(self, trust_mode="AUTO", tau_context=""):
        pass

    async def run(self, query, session_id, history, images=None, display_query=None, assistant_prefix="",
                  provider="auto", use_tools=False):
        FakeBootstrap.seen = {"query": query, "session": session_id, "history": history, "display": display_query}
        yield {"usage": 10}
        yield "Hello "
        yield "there."


@pytest.fixture
def client(monkeypatch):
    async def no_tau(session_id, query, history):
        return ""
    monkeypatch.setattr("gateway.openai_compat._tau.observe_and_inject", no_tau)
    monkeypatch.setattr("gateway.openai_compat.Bootstrap", FakeBootstrap)
    return TestClient(app)


def _auth():
    return {"Authorization": f"Bearer {issue_token('owner', 'owner')}"}


def _msgs():
    return [{"role": "system", "content": "Use [gesture:x] tags"}, {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hey"}, {"role": "user", "content": "who am I"}]


def test_requires_auth(client):
    assert client.post("/v1/chat/completions", json={"messages": _msgs()}).status_code == 401


def test_non_stream_reply_and_context(client):
    r = client.post("/v1/chat/completions", json={"messages": _msgs()}, headers=_auth())
    assert r.json()["choices"][0]["message"]["content"] == "Hello there."
    s = FakeBootstrap.seen
    assert s["display"] == "who am I" and "[gesture:x]" in s["query"] and s["session"] == "avatar:owner"
    assert s["history"] == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hey"}]


def test_stream_is_openai_shaped(client):
    r = client.post("/v1/chat/completions", json={"messages": _msgs(), "stream": True}, headers=_auth())
    lines = [ln[6:] for ln in r.text.split("\n") if ln.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    text = "".join(json.loads(ln)["choices"][0]["delta"].get("content", "") for ln in lines[:-1])
    assert text == "Hello there."
