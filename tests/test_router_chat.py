import pytest
from fastapi.testclient import TestClient

from gateway.auth import require_account
from main import app


class FakeBootstrap:
    def __init__(self, trust_mode="AUTO", tau_context=""):
        pass

    async def run(self, query, session_id, history, images=None, display_query=None, assistant_prefix=""):
        yield "ok"


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}

    async def fake_observe_and_inject(session_id, query, history):
        return ""

    monkeypatch.setattr("gateway.router._tau.observe_and_inject", fake_observe_and_inject)
    monkeypatch.setattr("gateway.router.Bootstrap", FakeBootstrap)
    yield TestClient(app)
    app.dependency_overrides.pop(require_account, None)


def test_url_shaped_text_inside_an_attachment_does_not_trigger_a_fetch(client, monkeypatch):
    """A regex literal like https://[a-zA-Z0-9.-]*\\.on\\.aws sitting inside an
    attached file (a workflow script, a README example, anything) used to get
    scanned by detect_web_intent along with the rest of the augmented message
    and treated as "fetch this URL" — hijacking the user's real question and
    hanging on a garbage host until the fetch tool's own timeout. Web-intent
    detection must only look at what the user actually typed."""
    calls = []

    async def fake_run_web_intent(kind, target, session_id=None):
        calls.append((kind, target))
        return ""

    monkeypatch.setattr("gateway.router.run_web_intent", fake_run_web_intent)

    resp = client.post("/chat", json={
        "message": "What's in here",
        "session_id": "sess1",
        "attachments": [
            {
                "name": "cloudflare-pages.yml",
                "content": "found=$(grep -o 'https://[a-zA-Z0-9.-]*\\.on\\.aws' dist/assets/*.js || true)",
            },
        ],
    })
    assert resp.status_code == 200
    assert calls == []


def test_a_url_the_user_actually_typed_still_triggers_a_fetch(client, monkeypatch):
    calls = []

    async def fake_run_web_intent(kind, target, session_id=None):
        calls.append((kind, target))
        return ""

    monkeypatch.setattr("gateway.router.run_web_intent", fake_run_web_intent)

    resp = client.post("/chat", json={
        "message": "check out https://example.com/page",
        "session_id": "sess1",
    })
    assert resp.status_code == 200
    assert calls == [("fetch", "https://example.com/page")]


def test_repo_intent_takes_priority_over_web_intent(client, monkeypatch):
    """'search the repo for X' contains the bare word 'search', which alone
    would trigger a web search — but repo phrasing is more specific and must
    win, so this calls run_repo_intent and never run_web_intent."""
    web_calls = []
    repo_calls = []

    async def fake_run_web_intent(kind, target, session_id=None):
        web_calls.append((kind, target))
        return ""

    async def fake_run_repo_intent(kind, target, session_id):
        repo_calls.append((kind, target, session_id))
        return ""

    monkeypatch.setattr("gateway.router.run_web_intent", fake_run_web_intent)
    monkeypatch.setattr("gateway.router.run_repo_intent", fake_run_repo_intent)

    resp = client.post("/chat", json={
        "message": "search the repo for save_turn",
        "session_id": "sess1",
    })
    assert resp.status_code == 200
    assert web_calls == []
    assert repo_calls == [("grep", "save_turn", "sess1")]


def test_readme_question_triggers_repo_intent_and_streams_the_result(client, monkeypatch):
    calls = []

    async def fake_run_repo_intent(kind, target, session_id):
        calls.append((kind, target, session_id))
        return '<repo_file repo="octocat/hello" path="README.md">hello world</repo_file>'

    monkeypatch.setattr("gateway.router.run_repo_intent", fake_run_repo_intent)

    resp = client.post("/chat", json={"message": "what's in the readme", "session_id": "sess1"})
    assert resp.status_code == 200
    assert calls == [("read", "README.md", "sess1")]
    assert "hello world" in resp.text  # the repo block rides through as a tool SSE event
