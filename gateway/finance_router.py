import json

from fastapi import APIRouter, Depends, HTTPException, Request

from agents.finance_agent import SERVERS, FinanceAgent
from gateway.auth import require_account
from pipeline.activity import RunLog, session_for
from pipeline.mcp_tools import MCPToolset
from pipeline.runs import durable
from storage.neon_store import get_store
from tau.tau_engine import TAUEngine
from tools.mcp_client import MCPClient

router = APIRouter(prefix="/finance")

# personal = C-Lab (your own money), biz = Colunimbus (the companies' books)
LABELS = {"personal": "C-Lab", "biz": "Colunimbus"}
HINTS = {
    "personal": "Paste C-Lab's https:// API address and an MCP key from C-Lab → Profile → Connect apps",
    "biz": "Paste Colunimbus's https:// API address and an MCP key from Colunimbus → Settings → Connect apps",
}


def _mode(value) -> str:
    return value if value in SERVERS else "personal"


async def _toolset(account_id: str, mode: str) -> MCPToolset | None:
    db = await get_store()
    server = next((s for s in await db.list_mcp_servers(account_id) if s["name"] == SERVERS[mode]), None)
    if not server:
        return None
    toolset = MCPToolset([server])
    await toolset.load()
    return toolset


@router.get("/status")
async def status(mode: str = "personal", account: dict = Depends(require_account)):
    mode = _mode(mode)
    toolset = await _toolset(account["account_id"], mode)
    if not toolset:
        return {"connected": False, "mode": mode}
    return {"connected": not toolset.errors, "mode": mode, "tools": len(toolset.tools()),
            "error": toolset.errors.get(SERVERS[mode], "")}


@router.post("/connect")
async def connect(request: Request, account: dict = Depends(require_account)):
    """Saves C-Lab as the MCP server "clab" or Colunimbus as "colunimbus" (both also usable from Co-work)."""
    body = await request.json()
    mode = _mode(body.get("mode"))
    url, key = (body.get("url") or "").strip().rstrip("/"), (body.get("key") or "").strip()
    if not url.startswith("https://") or not key:
        raise HTTPException(400, HINTS[mode])
    if not url.endswith("/mcp"):
        url += "/mcp"
    try:
        tools = await MCPClient(url, key, timeout=30).list_tools(use_cache=False)
    except Exception as e:
        raise HTTPException(400, f"Couldn't connect to {LABELS[mode]}: {str(e)[:300]}")
    db = await get_store()
    await db.upsert_mcp_server(account["account_id"], SERVERS[mode], url, key, False)
    return {"connected": True, "mode": mode, "tools": [t.get("name") for t in tools]}


@router.post("/run")
async def run(request: Request, account: dict = Depends(require_account)):
    body = await request.json()
    mode = _mode(body.get("mode"))
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message required")
    toolset = await _toolset(account["account_id"], mode)
    if not toolset:
        raise HTTPException(400, f"Connect {LABELS[mode]} first")
    agent = FinanceAgent(provider=body.get("model") or "auto", mcp=toolset, mode=mode)
    agent.user_context = await TAUEngine().owner_context()

    runlog = RunLog(session_for("finance", body), "finance")

    async def stream():
        await runlog.start(message, body.get("model") or "auto")
        if toolset.errors:
            text = f"{LABELS[mode]} unreachable: {toolset.errors[SERVERS[mode]]}"
            yield f"data: {json.dumps({'type': 'error', 'text': text})}\n\n"
        try:
            async for event in agent.run(message, body.get("history") or []):
                await runlog.record(event)
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': f'Finance agent crashed: {str(e)[:300]}'})}\n\n"
            await runlog.record({'type': 'error', 'text': f'Finance agent crashed: {str(e)[:300]}'})
        yield "data: [DONE]\n\n"

    return durable(stream(), account["account_id"], body, "finance")
