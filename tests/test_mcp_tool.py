import json

import pytest
import respx
from httpx import Response

from tools.mcp_tool import MCPTool
from tools.registry import ToolsRegistry, _bootstrap_registry, _register_configured_mcp_servers


def test_register_configured_mcp_servers_parses_json_and_registers(monkeypatch):
    monkeypatch.setattr("config.settings.MCP_SERVERS", json.dumps({"slack": "https://x.example.com"}))
    mcp = MCPTool()
    _register_configured_mcp_servers(mcp)
    assert mcp.list_servers() == ["slack"]


def test_register_configured_mcp_servers_handles_multiple_servers(monkeypatch):
    monkeypatch.setattr(
        "config.settings.MCP_SERVERS",
        json.dumps({"slack": "https://slack.example.com", "discord": "https://discord.example.com"}),
    )
    mcp = MCPTool()
    _register_configured_mcp_servers(mcp)
    assert sorted(mcp.list_servers()) == ["discord", "slack"]


def test_register_configured_mcp_servers_is_a_noop_when_unset(monkeypatch):
    monkeypatch.setattr("config.settings.MCP_SERVERS", "")
    mcp = MCPTool()
    _register_configured_mcp_servers(mcp)
    assert mcp.list_servers() == []


def test_register_configured_mcp_servers_ignores_malformed_json(monkeypatch):
    monkeypatch.setattr("config.settings.MCP_SERVERS", "{not valid json")
    mcp = MCPTool()
    _register_configured_mcp_servers(mcp)
    assert mcp.list_servers() == []


def test_register_configured_mcp_servers_ignores_non_dict_json(monkeypatch):
    monkeypatch.setattr("config.settings.MCP_SERVERS", json.dumps(["not", "a", "dict"]))
    mcp = MCPTool()
    _register_configured_mcp_servers(mcp)
    assert mcp.list_servers() == []


def test_register_configured_mcp_servers_skips_non_string_entries(monkeypatch):
    monkeypatch.setattr("config.settings.MCP_SERVERS", json.dumps({"slack": 123, "ok": "https://x.example.com"}))
    mcp = MCPTool()
    _register_configured_mcp_servers(mcp)
    assert mcp.list_servers() == ["ok"]


def fake_mcp_server(sse=False, session="sess-1", tools=None, calls=None):
    """A respx side_effect that speaks MCP's Streamable HTTP JSON-RPC."""
    tools = tools or [{"name": "echo", "description": "Echo back", "inputSchema": {"type": "object"}}]

    def handler(request):
        msg = json.loads(request.content)
        if calls is not None:
            calls.append((msg.get("method"), dict(request.headers)))
        if "id" not in msg:
            return Response(202)
        method = msg["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
        elif method == "tools/list":
            result = {"tools": tools}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": f"echo:{json.dumps(msg['params']['arguments'])}"},
                                  {"type": "image", "data": "QUJD", "mimeType": "image/png"}]}
        else:
            return Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "nope"}})
        body = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        headers = {"mcp-session-id": session} if method == "initialize" else {}
        if sse:
            return Response(200, text=f"event: message\ndata: {json.dumps(body)}\n\n",
                            headers={**headers, "content-type": "text/event-stream"})
        return Response(200, json=body, headers=headers)

    return handler


def test_bootstrap_registry_wires_configured_servers_into_the_mcp_tool(monkeypatch):
    monkeypatch.setattr("config.settings.MCP_SERVERS", json.dumps({"testserver": {"url": "https://mcp.example.com/mcp", "auth": "tok"}}))
    reg = ToolsRegistry()
    _bootstrap_registry(reg)

    import asyncio

    calls = []
    with respx.mock:
        respx.post("https://mcp.example.com/mcp").mock(side_effect=fake_mcp_server(calls=calls))
        result = asyncio.run(reg.execute("mcp", {"server": "testserver", "tool": "echo", "args": {"x": 1}}))

    assert result["ok"] and result["text"] == 'echo:{"x": 1}'
    assert [c[0] for c in calls] == ["initialize", "notifications/initialized", "tools/call"]
    assert calls[-1][1]["authorization"] == "Bearer tok"
    assert calls[-1][1]["mcp-session-id"] == "sess-1"


def test_bootstrap_registry_leaves_mcp_unconfigured_by_default(monkeypatch):
    monkeypatch.setattr("config.settings.MCP_SERVERS", "")
    reg = ToolsRegistry()
    _bootstrap_registry(reg)

    import asyncio
    result = asyncio.run(reg.execute("mcp", {"server": "anything", "tool": "echo", "args": {}}))
    assert "not registered" in result["error"]


@pytest.mark.asyncio
async def test_mcp_tool_call_against_an_unregistered_server_returns_a_clear_error():
    mcp = MCPTool()
    result = await mcp.call("nope", "some_tool", {})
    assert result == {"error": "MCP server 'nope' not registered"}


@pytest.mark.asyncio
@pytest.mark.parametrize("sse", [False, True])
async def test_client_lists_and_calls_tools_over_json_and_sse(sse):
    from tools import mcp_client
    mcp_client._tools_cache.clear()
    client = mcp_client.MCPClient("https://srv.example/mcp")
    with respx.mock:
        respx.post("https://srv.example/mcp").mock(side_effect=fake_mcp_server(sse=sse))
        tools = await client.list_tools()
        result = await client.call_tool("echo", {"a": 2})
    assert tools[0]["name"] == "echo"
    assert result == {"ok": True, "text": 'echo:{"a": 2}', "images": [{"mime": "image/png", "base64": "QUJD"}]}


@pytest.mark.asyncio
async def test_client_raises_on_a_json_rpc_error():
    from tools import mcp_client

    def handler(request):
        msg = json.loads(request.content)
        if msg.get("method") == "initialize":
            return Response(200, json={"jsonrpc": "2.0", "id": 0, "error": {"code": 1, "message": "bad token"}})
        return Response(202)

    with respx.mock:
        respx.post("https://srv.example/mcp").mock(side_effect=handler)
        with pytest.raises(mcp_client.MCPError, match="bad token"):
            await mcp_client.MCPClient("https://srv.example/mcp").call_tool("echo", {})
