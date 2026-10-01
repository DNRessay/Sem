import json

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from gateway.auth import require_account
from main import app
from tests.test_mcp_server import Store
from tests.test_mcp_tool import fake_mcp_server
from tools import mcp_client

CLAB = "https://clab.example/mcp"
GROQ = "https://api.groq.com/openai/v1/chat/completions"
CLAB_TOOLS = [{"name": "overview", "description": "Money overview", "inputSchema": {"type": "object"}}]


@pytest.fixture
def client(monkeypatch):
    store = Store()

    async def fake_get_store():
        return store

    for target in ("gateway.finance_router.get_store", "pipeline.mcp_tools.get_store"):
        monkeypatch.setattr(target, fake_get_store)
    from config import settings
    monkeypatch.setattr(settings, "LOCAL_LLM_URL", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    mcp_client._tools_cache.clear()
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app), store
    app.dependency_overrides.pop(require_account, None)


def test_connect_checks_clab_and_saves_it(client):
    c, store = client
    assert c.post("/finance/connect", json={"url": "http://insecure", "key": "k"}).status_code == 400
    with respx.mock:
        respx.post(CLAB).mock(side_effect=fake_mcp_server(tools=CLAB_TOOLS))
        r = c.post("/finance/connect", json={"url": "https://clab.example/", "key": "clab_abc"})
        assert r.json() == {"connected": True, "tools": ["overview"]}
        assert store.servers["clab"] == {"url": CLAB, "auth": "clab_abc", "require_approval": False}
        assert c.get("/finance/status").json()["connected"] is True


def test_status_when_not_connected(client):
    c, _ = client
    assert c.get("/finance/status").json() == {"connected": False}
    assert c.post("/finance/run", json={"message": "net worth?"}).status_code == 400


def test_run_uses_clab_tools(client):
    c, store = client
    store.servers["clab"] = {"url": CLAB, "auth": "clab_abc", "require_approval": False}
    store.servers["other"] = {"url": "https://other.example/mcp", "auth": "", "require_approval": False}
    call = {"id": "c1", "type": "function", "function": {"name": "mcp__clab__overview", "arguments": "{}"}}
    with respx.mock:
        server = respx.post(CLAB).mock(side_effect=fake_mcp_server(tools=CLAB_TOOLS))
        llm = respx.post(GROQ).mock(side_effect=[
            Response(200, json={"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call]}}]}),
            Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Net worth R 1.2m."}}]}),
        ])
        r = c.post("/finance/run", json={"message": "what's my net worth?"})
    events = [json.loads(line[6:]) for line in r.text.split("\n") if line.startswith("data: {")]
    assert events[-2] == {"type": "text", "text": "Net worth R 1.2m."}
    offered = {t["function"]["name"] for t in json.loads(llm.calls[0].request.content)["tools"]}
    assert offered == {"web_search", "fetch_url", "mcp__clab__overview"}  # only C-Lab's MCP tools, not "other"
    assert any(json.loads(c.request.content).get("method") == "tools/call" for c in server.calls)
