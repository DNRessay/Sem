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


def test_bootstrap_registry_wires_configured_servers_into_the_mcp_tool(monkeypatch):
    """End-to-end: a fresh registry (not the module singleton) built with
    MCP_SERVERS set should let the registered "mcp" tool actually reach a
    configured server, not return the default "not registered" error."""
    monkeypatch.setattr("config.settings.MCP_SERVERS", json.dumps({"testserver": "https://mcp.example.com"}))
    reg = ToolsRegistry()
    _bootstrap_registry(reg)

    import asyncio

    with respx.mock:
        respx.post("https://mcp.example.com/tools/echo").mock(
            return_value=Response(200, json={"ok": True}),
        )
        result = asyncio.run(reg.execute("mcp", {"server": "testserver", "tool": "echo", "args": {}}))

    assert result == {"ok": True}


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
async def test_mcp_tool_call_posts_to_the_registered_server():
    mcp = MCPTool()
    mcp.register_server("myserver", "https://mcp.example.com")
    with respx.mock:
        route = respx.post("https://mcp.example.com/tools/do_thing").mock(
            return_value=Response(200, json={"result": 42}),
        )
        result = await mcp.call("myserver", "do_thing", {"x": 1})

    assert result == {"result": 42}
    assert json.loads(route.calls[0].request.content) == {"arguments": {"x": 1}}


@pytest.mark.asyncio
async def test_mcp_tool_auto_route_uses_the_server_from_discover():
    mcp = MCPTool()
    mcp.register_server("myserver", "https://mcp.example.com")
    with respx.mock:
        respx.get("https://mcp.example.com/tools").mock(
            return_value=Response(200, json={"tools": [{"name": "do_thing"}]}),
        )
        await mcp.discover("myserver")

        respx.post("https://mcp.example.com/tools/do_thing").mock(
            return_value=Response(200, json={"result": "ok"}),
        )
        result = await mcp.auto_route("do_thing", {})

    assert result == {"result": "ok"}


@pytest.mark.asyncio
async def test_mcp_tool_auto_route_unknown_tool_returns_a_clear_error():
    mcp = MCPTool()
    result = await mcp.auto_route("never_discovered", {})
    assert "not found in any registered MCP server" in result["error"]
