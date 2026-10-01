"""A small Model Context Protocol client over Streamable HTTP — enough to
list and call tools on any remote MCP server (one endpoint URL, JSON-RPC
over POST, replies as JSON or as an SSE stream)."""
import json
import time

import httpx

PROTOCOL_VERSION = "2025-06-18"
_TOOLS_TTL_SECONDS = 300
_tools_cache: dict[str, tuple[float, list[dict]]] = {}


class MCPError(Exception):
    pass


def _parse(response: httpx.Response, request_id: int) -> dict:
    if response.status_code >= 400:
        raise MCPError(f"HTTP {response.status_code}: {response.text[:300]}")
    ctype = response.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == request_id:
                    return msg
        raise MCPError("no reply in the event stream")
    try:
        msg = response.json()
    except ValueError:
        raise MCPError(f"not JSON: {response.text[:200]}")
    if isinstance(msg, list):
        msg = next((m for m in msg if m.get("id") == request_id), {})
    return msg


class MCPClient:
    def __init__(self, url: str, auth_header: str = "", timeout: float = 120):
        self.url = url
        self.headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if auth_header:
            self.headers["Authorization"] = auth_header if " " in auth_header else f"Bearer {auth_header}"
        self.timeout = timeout
        self._next_id = 0

    async def _request(self, client: httpx.AsyncClient, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        body = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}}
        msg = _parse(await client.post(self.url, json=body, headers=self.headers), self._next_id)
        if "error" in msg:
            raise MCPError(str(msg["error"].get("message") or msg["error"])[:300])
        return msg.get("result") or {}

    async def _open(self, client: httpx.AsyncClient) -> dict:
        r = await client.post(self.url, headers=self.headers, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": "semblance", "version": "1.0"}},
        })
        init = _parse(r, 0)
        if "error" in init:
            raise MCPError(str(init["error"].get("message") or init["error"])[:300])
        if r.headers.get("mcp-session-id"):
            self.headers["Mcp-Session-Id"] = r.headers["mcp-session-id"]
        self.headers["MCP-Protocol-Version"] = (init.get("result") or {}).get("protocolVersion", PROTOCOL_VERSION)
        await client.post(self.url, headers=self.headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        return init.get("result") or {}

    async def list_tools(self, use_cache: bool = True) -> list[dict]:
        cached = _tools_cache.get(self.url)
        if use_cache and cached and time.monotonic() - cached[0] < _TOOLS_TTL_SECONDS:
            return cached[1]
        tools, cursor = [], None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await self._open(client)
            while True:
                result = await self._request(client, "tools/list", {"cursor": cursor} if cursor else {})
                tools.extend(result.get("tools") or [])
                cursor = result.get("nextCursor")
                if not cursor:
                    break
        _tools_cache[self.url] = (time.monotonic(), tools)
        return tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """{"ok", "text", "images": [{"mime", "base64"}]} — content flattened
        to text for the model, images kept separately for the UI."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await self._open(client)
            result = await self._request(client, "tools/call", {"name": name, "arguments": arguments or {}})
        texts, images = [], []
        for part in result.get("content") or []:
            if part.get("type") == "text":
                texts.append(part.get("text", ""))
            elif part.get("type") == "image":
                images.append({"mime": part.get("mimeType", "image/png"), "base64": part.get("data", "")})
            elif part.get("type") == "resource":
                texts.append(json.dumps(part.get("resource"), default=str)[:4000])
        if result.get("structuredContent") and not texts:
            texts.append(json.dumps(result["structuredContent"], default=str))
        return {"ok": not result.get("isError"), "text": "\n".join(texts), "images": images}
