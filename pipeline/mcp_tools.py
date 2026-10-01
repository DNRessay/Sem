"""Per-account MCP servers as agent tools. Each remote tool is exposed to the
model as mcp__<server>__<tool>; calls go over the real protocol
(tools/mcp_client.py). A server marked require_approval has its calls queued
as approval cards in Co-work instead of running directly."""
import asyncio
import re
from urllib.parse import urlparse

from agents.tool_loop import fn_tool
from storage.neon_store import get_store
from tools.mcp_client import MCPClient

_SAFE = re.compile(r"[^a-zA-Z0-9_-]")


def _guarded(url: str) -> bool:
    """Servers that can change real infrastructure (AWS, Cloudflare): any tool
    not marked read-only waits for the user's approval, whatever the setting."""
    host = urlparse(url).hostname or ""
    return host.endswith(".api.aws") or host == "mcp.cloudflare.com" or host.endswith(".mcp.cloudflare.com")


def tool_id(server: str, tool: str) -> str:
    return f"mcp__{_SAFE.sub('_', server)}__{_SAFE.sub('_', tool)}"[:64]


class MCPToolset:
    def __init__(self, servers: list[dict] | None = None):
        self.servers = {s["name"]: s for s in servers or []}
        self._defs: list[dict] = []
        self._routes: dict[str, tuple[str, str]] = {}
        self._writes: set[str] = set()
        self.errors: dict[str, str] = {}

    @classmethod
    async def for_account(cls, account_id: str) -> "MCPToolset":
        db = await get_store()
        toolset = cls(await db.list_mcp_servers(account_id))
        await toolset.load()
        return toolset

    async def load(self):
        async def one(server):
            try:
                return server, await MCPClient(server["url"], server.get("auth", "")).list_tools()
            except Exception as e:
                self.errors[server["name"]] = str(e)[:200]
                return server, []

        for server, tools in await asyncio.gather(*[one(s) for s in self.servers.values()]):
            for t in tools:
                name = tool_id(server["name"], t["name"])
                self._routes[name] = (server["name"], t["name"])
                if _guarded(server["url"]) and not (t.get("annotations") or {}).get("readOnlyHint"):
                    self._writes.add(name)
                schema = t.get("inputSchema") or {"type": "object", "properties": {}}
                desc = f"[{server['name']} via MCP] {t.get('description', '')}"[:1000]
                self._defs.append(fn_tool(name, desc, schema.get("properties") or {}, schema.get("required") or []))

    def tools(self, include_approval: bool = True) -> list[dict]:
        return [d for d in self._defs if include_approval or not self.needs_approval(d["function"]["name"])]

    def owns(self, name: str) -> bool:
        return name in self._routes

    def needs_approval(self, name: str) -> bool:
        server, _ = self._routes.get(name, ("", ""))
        return name in self._writes or bool(self.servers.get(server, {}).get("require_approval"))

    def describe(self, name: str, args: dict) -> str:
        server, tool = self._routes[name]
        return f"Run {tool} on {server} with {args}"[:300]

    async def call(self, name: str, args: dict) -> dict:
        server, tool = self._routes[name]
        cfg = self.servers[server]
        try:
            return await MCPClient(cfg["url"], cfg.get("auth", "")).call_tool(tool, args)
        except Exception as e:
            return {"ok": False, "error": f"{server}: {str(e)[:300]}"}
