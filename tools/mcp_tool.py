import httpx


class MCPTool:
    """
    Model Context Protocol bridge.
    Connects Semblance to any MCP-compatible server.
    Gmail, Google Calendar, Slack, Asana, custom tools.
    Tool definitions loaded dynamically at runtime.
    """

    def __init__(self):
        self._servers: dict[str, str] = {}       # name → base_url
        self._tool_index: dict[str, str] = {}    # tool_name → server_name

    def register_server(self, name: str, base_url: str, api_key: str = ""):
        """Register an MCP server endpoint."""
        self._servers[name] = base_url

    async def discover(self, server_name: str) -> list[dict]:
        """Fetch available tools from an MCP server."""
        base_url = self._servers.get(server_name)
        if not base_url:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{base_url}/tools")
                tools = r.json().get("tools", [])
                for t in tools:
                    self._tool_index[t["name"]] = server_name
                return tools
        except Exception as e:
            return [{"error": str(e)}]

    async def call(self, server: str, tool: str, args: dict = None) -> dict:
        """Call a specific tool on an MCP server."""
        base_url = self._servers.get(server)
        if not base_url:
            return {"error": f"MCP server '{server}' not registered"}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{base_url}/tools/{tool}",
                    json={"arguments": args or {}},
                    headers={"Content-Type": "application/json"},
                )
                return r.json()
        except Exception as e:
            return {"error": str(e), "server": server, "tool": tool}

    async def auto_route(self, tool_name: str, args: dict) -> dict:
        """Automatically route a tool call to the right server."""
        server = self._tool_index.get(tool_name)
        if not server:
            return {"error": f"Tool '{tool_name}' not found in any registered MCP server"}
        return await self.call(server, tool_name, args)

    def list_servers(self) -> list[str]:
        return list(self._servers.keys())

    def list_tools(self) -> dict[str, str]:
        return dict(self._tool_index)
