import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from agents.finance_agent import FINANCE_SERVER, FinanceAgent
from gateway.auth import require_account
from pipeline.mcp_tools import MCPToolset
from storage.neon_store import get_store
from tools.mcp_client import MCPClient

router = APIRouter(prefix="/finance")


async def _clab_toolset(account_id: str) -> MCPToolset | None:
    db = await get_store()
    server = next((s for s in await db.list_mcp_servers(account_id) if s["name"] == FINANCE_SERVER), None)
    if not server:
        return None
    toolset = MCPToolset([server])
    await toolset.load()
    return toolset


@router.get("/status")
async def status(account: dict = Depends(require_account)):
    toolset = await _clab_toolset(account["account_id"])
    if not toolset:
        return {"connected": False}
    return {"connected": not toolset.errors, "tools": len(toolset.tools()),
            "error": toolset.errors.get(FINANCE_SERVER, "")}


@router.post("/connect")
async def connect(request: Request, account: dict = Depends(require_account)):
    """Saves C-Lab as the MCP server named "clab" (also usable from Co-work)."""
    body = await request.json()
    url, key = (body.get("url") or "").strip().rstrip("/"), (body.get("key") or "").strip()
    if not url.startswith("https://") or not key:
        raise HTTPException(400, "Paste C-Lab's https:// API address and an MCP key from C-Lab → Profile → Connect apps")
    if not url.endswith("/mcp"):
        url += "/mcp"
    try:
        tools = await MCPClient(url, key, timeout=30).list_tools(use_cache=False)
    except Exception as e:
        raise HTTPException(400, f"Couldn't connect to C-Lab: {str(e)[:300]}")
    db = await get_store()
    await db.upsert_mcp_server(account["account_id"], FINANCE_SERVER, url, key, False)
    return {"connected": True, "tools": [t.get("name") for t in tools]}


@router.post("/run")
async def run(request: Request, account: dict = Depends(require_account)):
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message required")
    toolset = await _clab_toolset(account["account_id"])
    if not toolset:
        raise HTTPException(400, "Connect C-Lab first")
    agent = FinanceAgent(provider=body.get("model") or "auto", mcp=toolset)

    async def stream():
        if toolset.errors:
            yield f"data: {json.dumps({'type': 'error', 'text': f'C-Lab unreachable: {toolset.errors[FINANCE_SERVER]}'})}\n\n"
        try:
            async for event in agent.run(message, body.get("history") or []):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': f'Finance agent crashed: {str(e)[:300]}'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
