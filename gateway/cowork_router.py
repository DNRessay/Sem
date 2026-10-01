import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from agents.cowork_agent import NEEDS_APPROVAL, CoworkAgent, run_approved
from gateway.auth import require_account
from pipeline.mcp_tools import MCPToolset
from tau.tau_engine import TAUEngine

router = APIRouter(prefix="/cowork")


@router.post("/run")
async def run(request: Request, account: dict = Depends(require_account)):
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message required")
    mcp = await MCPToolset.for_account(account["account_id"])
    agent = CoworkAgent(account["account_id"], provider=body.get("model") or "auto", mcp=mcp)
    agent.user_context = await TAUEngine().owner_context()

    async def stream():
        try:
            async for event in agent.run(message, body.get("history") or []):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:  # surface it in the UI instead of a silently dead stream
            yield f"data: {json.dumps({'type': 'error', 'text': f'Co-work agent crashed: {str(e)[:300]}'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/execute")
async def execute(request: Request, account: dict = Depends(require_account)):
    """Runs one action the agent queued, after the user tapped Approve."""
    body = await request.json()
    name, args = body.get("name"), body.get("args") or {}
    if not isinstance(args, dict):
        raise HTTPException(400, "not an approvable action")
    if name in NEEDS_APPROVAL:
        result = await run_approved(name, args, account["account_id"])
    elif isinstance(name, str) and name.startswith("mcp__"):
        mcp = await MCPToolset.for_account(account["account_id"])
        if not (mcp.owns(name) and mcp.needs_approval(name)):
            raise HTTPException(400, "not an approvable action")
        result = await mcp.call(name, args)
        if result.get("ok") is False:
            result = {"error": result.get("error") or result.get("text") or "MCP tool failed"}
    else:
        raise HTTPException(400, "not an approvable action")
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return {"ok": True, "result": result}
