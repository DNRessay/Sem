from typing import Any, Callable


class ToolsRegistry:
    """
    Flat tool registry. Single source of truth for all tools.
    Each tool defines its own: input schema, permission level, execution logic.
    Zero shared mutable state between tools.
    CABLES MAN has zero direct API access — everything routes through here.
    """

    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(
        self,
        tool_name: str,
        handler: Callable,
        schema: dict,
        permission: str = "AUTO",
        description: str = "",
    ) -> None:
        """
        Register a tool.
        permission: BYPASS | ALLOW_EDITS | AUTO
        """
        self._tools[tool_name] = {
            "name": tool_name,
            "handler": handler,
            "schema": schema,
            "permission": permission,
            "description": description,
        }

    def get(self, tool_name: str) -> dict | None:
        return self._tools.get(tool_name)

    def list_all(self) -> list[str]:
        return list(self._tools.keys())

    def list_with_meta(self) -> list[dict]:
        return [
            {
                "name": t["name"],
                "permission": t["permission"],
                "description": t["description"],
                "schema": t["schema"],
            }
            for t in self._tools.values()
        ]

    async def execute(self, tool_name: str, args: dict, trust_mode: str = "AUTO") -> Any:
        """Execute a tool, respecting permission level vs trust_mode."""
        tool = self.get(tool_name)
        if not tool:
            return {"error": f"Tool '{tool_name}' not registered"}

        effective_perm = tool["permission"]
        if trust_mode == "BYPASS":
            effective_perm = "BYPASS"

        if effective_perm == "ALLOW_EDITS" and _is_write_op(args):
            return {
                "status": "confirmation_required",
                "tool": tool_name,
                "args": args,
                "message": "This tool performs a write operation. Confirm before proceeding.",
            }

        try:
            return await tool["handler"](**args)
        except TypeError:
            # Try calling without keyword expansion
            return await tool["handler"](args)
        except Exception as e:
            return {"error": str(e)}

    def load_mcp_tools(self, mcp_server_url: str) -> int:
        """
        Dynamically fetch and register tools from an MCP server at runtime.
        Returns count of tools registered.
        """
        import asyncio

        import httpx

        async def _fetch():
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(f"{mcp_server_url}/tools")
                    tools = r.json().get("tools", [])
                    for t in tools:
                        self.register(
                            tool_name=t["name"],
                            handler=self._make_mcp_handler(mcp_server_url, t["name"]),
                            schema=t.get("inputSchema", {}),
                            permission="AUTO",
                            description=t.get("description", ""),
                        )
                    return len(tools)
            except Exception:
                return 0

        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(_fetch())
        except Exception:
            return 0

    def _make_mcp_handler(self, base_url: str, tool_name: str) -> Callable:
        import httpx

        async def handler(**kwargs):
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{base_url}/tools/{tool_name}",
                    json={"arguments": kwargs}
                )
                return r.json()

        handler.__name__ = f"mcp_{tool_name}"
        return handler


def _is_write_op(args: dict) -> bool:
    """Heuristic: detect if tool call involves a write operation."""
    write_keys = {"write", "save", "delete", "create", "update", "insert", "post", "put", "patch"}
    return any(k in str(args).lower() for k in write_keys)


# ─── Singleton registry ──────────────────────────────────────────────────────

_registry: ToolsRegistry | None = None


def get_registry() -> ToolsRegistry:
    global _registry
    if _registry is None:
        _registry = ToolsRegistry()
        _bootstrap_registry(_registry)
    return _registry


def _register_configured_mcp_servers(mcp) -> None:
    """MCP_SERVERS (config.py) is an optional JSON object of name ->
    base_url — each gets registered with the shared MCPTool instance so
    the "mcp" tool actually has something to call. Left unset (the
    default), this is a no-op and "mcp" stays real-but-unconfigured, same
    as every other optional integration in this registry: a clear "not
    registered" error on every call rather than silently doing nothing.
    Any malformed config (bad JSON, wrong shape) is ignored rather than
    crashing registry bootstrap, which every tool call path depends on."""
    import json

    from config import settings

    raw = (settings.MCP_SERVERS or "").strip()
    if not raw:
        return
    try:
        servers = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(servers, dict):
        return
    for name, url in servers.items():
        if isinstance(name, str) and isinstance(url, str) and url:
            mcp.register_server(name, url)


def _bootstrap_registry(reg: ToolsRegistry):
    """Register all built-in tools at startup."""
    from tools.artifact_tool import ArtifactTool
    from tools.bash_tool import BashTool
    from tools.mcp_tool import MCPTool
    from tools.misc.calendar_tool import CalendarTool
    from tools.misc.whatsapp_tool import WhatsAppTool
    from tools.repo_tool import RepoTool
    from tools.repo_write_tool import RepoWriteTool
    from tools.web.fetch_tool import FetchTool
    from tools.web.news_tool import NewsTool
    from tools.web.serp_tool import SerpTool

    serp    = SerpTool()
    fetch   = FetchTool()
    news    = NewsTool()
    bash    = BashTool()
    mcp     = MCPTool()
    _register_configured_mcp_servers(mcp)
    artifact = ArtifactTool()
    calendar = CalendarTool()
    whatsapp = WhatsAppTool()
    repo    = RepoTool()
    repo_write = RepoWriteTool()

    reg.register("web_search",   serp.search,    {"query": "string", "num": "int"},       "AUTO",        "Google search via SerpAPI")
    reg.register("web_search_full", serp.search_full, {"query": "string", "num": "int"}, "AUTO",         "Google search + AI Overview (one call) via SerpAPI")
    reg.register("web_news",     serp.news,      {"query": "string"},                      "AUTO",        "News search via SerpAPI")
    reg.register("web_fetch",    fetch.fetch,    {"url": "string"},                        "AUTO",        "Fetch full page content from URL")
    reg.register("news_tool",    news.latest,    {"topic": "string", "count": "int"},      "AUTO",        "Real-time news headlines")
    reg.register("bash",         bash.execute,   {"command": "string"},                    "ALLOW_EDITS", "Shell execution with 23 security checks")
    reg.register("mcp",          mcp.call,       {"server": "string", "tool": "string", "args": "dict"}, "AUTO", "MCP bridge")
    reg.register("artifact",     artifact.render,{"type": "string", "content": "string"}, "AUTO",        "Render JSX/HTML/SVG/MD artifact")
    reg.register("calendar",     calendar.query, {"action": "string"},                    "ALLOW_EDITS", "Google Calendar read/write")
    reg.register("whatsapp",     whatsapp.send,  {"phone": "string", "message": "string"},"ALLOW_EDITS", "WhatsApp Business API outbound")
    reg.register("repo_clone",   repo.clone_or_pull, {"provider": "string", "repo": "string", "ref": "string"}, "AUTO", "Clone or pull a repo onto a persistent Modal-hosted clone")
    reg.register("repo_read",    repo.read_file, {"provider": "string", "repo": "string", "path": "string"}, "AUTO", "Read one file from a persistently cloned repo")
    reg.register("repo_grep",    repo.grep,      {"provider": "string", "repo": "string", "term": "string"}, "AUTO", "Search a persistently cloned repo for a term")
    reg.register(
        "propose_fix", repo_write.propose_fix,
        {
            "provider": "string", "repo": "string", "token": "string", "level": "string",
            "slug": "string", "files": "dict", "commit_message": "string",
            "pr_title": "string", "pr_body": "string", "base_branch": "string",
        },
        "AUTO",
        "Branch + commit (with a SemVer VERSION bump) + open a PR for a validated fix — never touches the default branch, a human reviews via the PR",
    )
