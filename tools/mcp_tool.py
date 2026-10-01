from tools.mcp_client import MCPClient, MCPError


class MCPTool:
    """The registry's "mcp" tool: calls a tool on a named MCP server from
    MCP_SERVERS (config.py) over the real MCP protocol (tools/mcp_client.py).
    Per-account servers added in the app are used by the Code/Co-work agents
    through pipeline/mcp_tools.py instead."""

    def __init__(self):
        self._servers: dict[str, dict] = {}

    def register_server(self, name: str, url: str, auth: str = ""):
        self._servers[name] = {"url": url, "auth": auth}

    async def discover(self, server_name: str) -> list[dict]:
        server = self._servers.get(server_name)
        if not server:
            return []
        try:
            return await MCPClient(server["url"], server["auth"]).list_tools()
        except Exception as e:
            return [{"error": str(e)}]

    async def call(self, server: str, tool: str, args: dict = None) -> dict:
        cfg = self._servers.get(server)
        if not cfg:
            return {"error": f"MCP server '{server}' not registered"}
        try:
            return await MCPClient(cfg["url"], cfg["auth"]).call_tool(tool, args or {})
        except (MCPError, Exception) as e:
            return {"error": str(e), "server": server, "tool": tool}

    def list_servers(self) -> list[str]:
        return list(self._servers.keys())
