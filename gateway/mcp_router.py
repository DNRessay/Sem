import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from config import settings
from gateway import mcp_server
from gateway.auth import current_version, issue_token, require_account
from storage.neon_store import get_store
from tools.mcp_client import MCPClient

router = APIRouter(prefix="/mcp")
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$")
MCP_KEY_TTL_SECONDS = 365 * 24 * 60 * 60


# --- SEMBLANCE as an MCP server ----------------------------------------------

@router.post("")
async def mcp_endpoint(request: Request, account: dict = Depends(require_account)):
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, 400)
    messages = payload if isinstance(payload, list) else [payload]
    replies = [r for r in [await mcp_server.handle(m, account["account_id"]) for m in messages] if r is not None]
    if not replies:
        return Response(status_code=202)
    return JSONResponse(replies if isinstance(payload, list) else replies[0])


@router.get("")
async def mcp_no_stream():
    # Stateless server: no server-initiated event stream to open.
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/key")
async def mcp_key(account: dict = Depends(require_account)):
    """A long-lived key for MCP clients (login tokens expire after 30 days).
    Changing the passphrase (or rotating SECRET_KEY) revokes every key at once."""
    version = await current_version(account["account_id"]) or 0
    key = issue_token(account["account_id"], account["role"], ttl_seconds=MCP_KEY_TTL_SECONDS, version=version)
    url = (settings.PUBLIC_API_URL or "<your API URL>").rstrip("/") + "/mcp"
    return {
        "key": key, "url": url, "expires_in_days": 365,
        "claude_code": f'claude mcp add --transport http semblance {url} --header "Authorization: Bearer {key}"',
        "json_config": {"mcpServers": {"semblance": {"type": "http", "url": url,
                                                     "headers": {"Authorization": f"Bearer {key}"}}}},
    }


# --- MCP servers SEMBLANCE uses ----------------------------------------------

@router.get("/servers")
async def list_servers(account: dict = Depends(require_account)):
    db = await get_store()
    servers = await db.list_mcp_servers(account["account_id"])
    # Never send stored credentials back to the browser.
    return {"servers": [{**s, "auth": bool(s["auth"])} for s in servers]}


@router.get("/servers/check")
async def check_servers(account: dict = Depends(require_account)):
    """Asks every saved server for its tools, in parallel — the live status column in Settings → Connectors."""
    db = await get_store()
    servers = await db.list_mcp_servers(account["account_id"])

    async def one(s):
        try:
            tools = await MCPClient(s["url"], s["auth"], timeout=15).list_tools(use_cache=False)
            return {"name": s["name"], "ok": True, "tools": len(tools)}
        except Exception as e:
            return {"name": s["name"], "ok": False, "error": str(e)[:200]}

    return {"servers": await asyncio.gather(*(one(s) for s in servers))}


@router.post("/servers")
async def add_server(request: Request, account: dict = Depends(require_account)):
    body = await request.json()
    name, url = (body.get("name") or "").strip(), (body.get("url") or "").strip()
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(400, "name: letters, digits, - and _ only (max 32)")
    if not url.startswith("https://") and not url.startswith("http://localhost"):
        raise HTTPException(400, "url must be https://")
    auth = (body.get("auth") or "").strip()
    try:
        tools = await MCPClient(url, auth, timeout=30).list_tools(use_cache=False)
    except Exception as e:
        raise HTTPException(400, f"Couldn't connect: {str(e)[:300]}")
    db = await get_store()
    await db.upsert_mcp_server(account["account_id"], name, url, auth, bool(body.get("require_approval")))
    return {"ok": True, "name": name, "tools": [t.get("name") for t in tools]}


@router.delete("/servers/{name}")
async def remove_server(name: str, account: dict = Depends(require_account)):
    db = await get_store()
    if not await db.delete_mcp_server(account["account_id"], name):
        raise HTTPException(404, "server not found")
    return {"ok": True}
