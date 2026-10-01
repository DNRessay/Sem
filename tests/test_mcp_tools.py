import pytest

from pipeline import mcp_tools


@pytest.mark.asyncio
async def test_cloudflare_write_tools_always_need_approval(monkeypatch):
    class FakeClient:
        def __init__(self, url, auth="", timeout=120):
            self.url = url

        async def list_tools(self, use_cache=True):
            return [{"name": "search", "annotations": {"readOnlyHint": True}}, {"name": "execute"}]

    monkeypatch.setattr(mcp_tools, "MCPClient", FakeClient)
    toolset = mcp_tools.MCPToolset([
        {"name": "cloudflare", "url": "https://mcp.cloudflare.com/mcp", "auth": "t", "require_approval": False},
        {"name": "notes", "url": "https://notes.example.com/mcp", "auth": "", "require_approval": False},
    ])
    await toolset.load()
    assert not toolset.needs_approval("mcp__cloudflare__search")
    assert toolset.needs_approval("mcp__cloudflare__execute")
    assert not toolset.needs_approval("mcp__notes__execute")
    assert "mcp__cloudflare__execute" not in [t["function"]["name"] for t in toolset.tools(include_approval=False)]
