import json

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from agents.cowork_agent import CoworkAgent
from gateway.auth import require_account
from main import app
from pipeline.mcp_tools import MCPToolset, tool_id
from tests.test_mcp_tool import fake_mcp_server
from tools import mcp_client

GROQ = "https://api.groq.com/openai/v1/chat/completions"


class Store:
    def __init__(self):
        self.servers = {}

    async def list_mcp_servers(self, account_id):
        return [{"name": n, **v} for n, v in sorted(self.servers.items())]

    async def upsert_mcp_server(self, account_id, name, url, auth, require_approval):
        self.servers[name] = {"url": url, "auth": auth, "require_approval": require_approval}

    async def delete_mcp_server(self, account_id, name):
        return self.servers.pop(name, None) is not None


@pytest.fixture
def store(monkeypatch):
    s = Store()

    async def fake_get_store():
        return s

    for target in ("gateway.mcp_router.get_store", "pipeline.mcp_tools.get_store"):
        monkeypatch.setattr(target, fake_get_store)
    mcp_client._tools_cache.clear()
    return s


@pytest.fixture
def client(store):
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app)
    app.dependency_overrides.pop(require_account, None)


def _rpc(client, method, params=None, mid=1):
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}).json()


def test_initialize_negotiates_version_and_lists_tools(client):
    init = _rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t"}})
    assert init["result"]["protocolVersion"] == "2025-03-26"
    assert init["result"]["serverInfo"]["name"] == "semblance"
    assert _rpc(client, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-06-18"
    names = {t["name"] for t in _rpc(client, "tools/list")["result"]["tools"]}
    assert {"ask", "research", "cowork", "code", "code_open_pr", "generate_image", "write_ads"} <= names


def test_notifications_get_202_and_unknown_methods_error(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202
    assert _rpc(client, "resources/list")["error"]["code"] == -32601
    assert client.get("/mcp").status_code == 405


def test_tools_call_runs_the_tool(client, monkeypatch):
    async def fake_complete(model, messages, **kw):
        return {"content": f"answer via {model}"}

    monkeypatch.setattr("gateway.mcp_server.llm_providers.complete", fake_complete)
    r = _rpc(client, "tools/call", {"name": "ask", "arguments": {"message": "hi", "model": "gemini"}})
    assert r["result"] == {"content": [{"type": "text", "text": "answer via gemini"}], "isError": False}
    assert _rpc(client, "tools/call", {"name": "nope"})["error"]["code"] == -32602


def test_batch_requests_get_batch_replies(client):
    r = client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                  {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                  {"jsonrpc": "2.0", "id": 2, "method": "ping"}]).json()
    assert [m["id"] for m in r] == [1, 2]


def test_mcp_requires_auth():
    r = TestClient(app).post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401


def test_mcp_key_is_long_lived_and_has_setup_commands(client):
    from gateway.auth import _decode_token
    d = client.post("/mcp/key").json()
    import time
    assert _decode_token(d["key"])["exp"] > time.time() + 300 * 86400
    assert "claude mcp add --transport http semblance" in d["claude_code"]


def test_adding_a_server_checks_it_and_hides_the_credential(client, store):
    with respx.mock:
        respx.post("https://tools.example/mcp").mock(side_effect=fake_mcp_server())
        r = client.post("/mcp/servers", json={"name": "notion", "url": "https://tools.example/mcp", "auth": "secret"})
    assert r.json() == {"ok": True, "name": "notion", "tools": ["echo"]}
    listed = client.get("/mcp/servers").json()["servers"]
    assert listed == [{"name": "notion", "url": "https://tools.example/mcp", "auth": True, "require_approval": False}]
    assert client.post("/mcp/servers", json={"name": "bad name!", "url": "https://x"}).status_code == 400
    assert client.delete("/mcp/servers/notion").json() == {"ok": True}


def test_unreachable_server_is_rejected(client):
    with respx.mock:
        respx.post("https://down.example/mcp").mock(return_value=Response(500, text="boom"))
        r = client.post("/mcp/servers", json={"name": "down", "url": "https://down.example/mcp"})
    assert r.status_code == 400 and "Couldn't connect" in r.json()["detail"]


def _call(cid, name, args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _reply(content="", calls=None):
    return Response(200, json={"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": calls}}]})


@pytest.mark.asyncio
@pytest.mark.parametrize("require_approval", [False, True])
async def test_cowork_uses_mcp_tools(store, monkeypatch, require_approval):
    from config import settings
    monkeypatch.setattr(settings, "LOCAL_LLM_URL", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    await store.upsert_mcp_server("owner", "notes", "https://tools.example/mcp", "", require_approval)
    name = tool_id("notes", "echo")
    with respx.mock:
        server = respx.post("https://tools.example/mcp").mock(side_effect=fake_mcp_server())
        mcp = await MCPToolset.for_account("owner")
        llm = respx.post(GROQ).mock(side_effect=[_reply("", [_call("c1", name, {"x": 1})]), _reply("done")])
        events = [e async for e in CoworkAgent("owner", mcp=mcp).run("use notes")]
    offered = {t["function"]["name"] for t in json.loads(llm.calls[0].request.content)["tools"]}
    assert name in offered
    called = [json.loads(c.request.content).get("method") for c in server.calls]
    if require_approval:
        assert "tools/call" not in called
        assert any(e["type"] == "approval" and e["name"] == name for e in events)
    else:
        assert "tools/call" in called
        assert any(e["type"] == "image" for e in events)  # the fake server returns an image part


def test_settings_status_reports_features_without_secret_values(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "super-secret-value")
    r = client.get("/settings/status").json()
    gemini = next(f for f in r["features"] if f["name"] == "Gemini (free tier)")
    assert gemini["on"] is True and gemini["enable"] == "GEMINI_API_KEY"
    assert "super-secret-value" not in str(r)
    assert r["limits"]["code_max_steps"] == settings.CODE_MAX_STEPS
