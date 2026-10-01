import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from agents.code_agent import CodeAgent
from gateway.auth import require_account
from pipeline.code_tasks import EVERY_SECONDS, connector_token, open_pr, valid_target
from pipeline.mcp_tools import MCPToolset
from storage.neon_store import get_store
from tau.tau_engine import TAUEngine
from tools.code_workspace import CodeWorkspace

router = APIRouter(prefix="/code")


async def _target(request: Request) -> tuple[dict, CodeWorkspace]:
    body = await request.json()
    provider, repo = body.get("provider", "github"), (body.get("repo") or "").strip()
    if not valid_target(provider, repo):
        raise HTTPException(400, "provider must be github/gitlab and repo like owner/name")
    return body, CodeWorkspace(provider, repo)


@router.post("/open")
async def open_repo(request: Request, account: dict = Depends(require_account)):
    body, ws = await _target(request)
    token = await connector_token(account["account_id"], ws.provider)
    result = await ws.open(token, body.get("ref") or "")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "clone failed")
    listing = await ws.list_dir("")
    return {**result, "entries": listing.get("entries", []), "can_open_pr": bool(token)}


@router.post("/run")
async def run(request: Request, account: dict = Depends(require_account)):
    body, ws = await _target(request)
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message required")
    mcp = await MCPToolset.for_account(account["account_id"])
    token = await connector_token(account["account_id"], ws.provider)
    agent = CodeAgent(ws, mode=body.get("mode") or "act", provider=body.get("model") or "auto", mcp=mcp, pr_token=token)
    agent.user_context = await TAUEngine().owner_context()

    async def stream():
        try:
            async for event in agent.run(message, body.get("history") or []):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:  # surface it in the UI instead of a silently dead stream
            yield f"data: {json.dumps({'type': 'error', 'text': f'Code agent crashed: {str(e)[:300]}'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/changes")
async def changes(request: Request, _account: dict = Depends(require_account)):
    _, ws = await _target(request)
    result = await ws.changes()
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "couldn't read changes")
    return {"files": sorted(result.get("files") or {}), "deleted": result.get("deleted", []), "stat": result.get("stat", "")}


@router.post("/discard")
async def discard(request: Request, _account: dict = Depends(require_account)):
    _, ws = await _target(request)
    return await ws.discard()


@router.post("/pr")
async def pull_request(request: Request, account: dict = Depends(require_account)):
    body, ws = await _target(request)
    token = await connector_token(account["account_id"], ws.provider)
    if not token:
        raise HTTPException(400, f"Connect {ws.provider} first — opening a PR needs its token")
    result = await open_pr(ws, token, body.get("title") or "", body.get("body") or "")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "PR failed")
    return result


@router.get("/automations")
async def list_automations(account: dict = Depends(require_account)):
    db = await get_store()
    return {"automations": await db.list_code_automations(account["account_id"])}


@router.post("/automations")
async def create_automation(request: Request, account: dict = Depends(require_account)):
    body, ws = await _target(request)
    prompt = (body.get("prompt") or "").strip()
    every = body.get("every", "daily")
    if not prompt or every not in EVERY_SECONDS:
        raise HTTPException(400, f"prompt required; every must be one of {', '.join(EVERY_SECONDS)}")
    db = await get_store()
    row = await db.create_code_automation(
        account["account_id"], ws.provider, ws.repo, prompt, EVERY_SECONDS[every], bool(body.get("open_pr", True)),
    )
    return {"automation": row}


@router.patch("/automations/{automation_id}")
async def toggle_automation(automation_id: int, request: Request, account: dict = Depends(require_account)):
    body = await request.json()
    db = await get_store()
    if not await db.set_code_automation_enabled(account["account_id"], automation_id, bool(body.get("enabled"))):
        raise HTTPException(404, "automation not found")
    return {"ok": True}


@router.delete("/automations/{automation_id}")
async def delete_automation(automation_id: int, account: dict = Depends(require_account)):
    db = await get_store()
    if not await db.delete_code_automation(account["account_id"], automation_id):
        raise HTTPException(404, "automation not found")
    return {"ok": True}
