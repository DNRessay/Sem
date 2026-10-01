import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from agents.code_agent import APPROVAL_ACTIONS, CodeAgent
from cache import ddb_backend
from gateway.auth import require_account
from pipeline.code_tasks import EVERY_SECONDS, connector_token, open_pr, run_code_action, valid_target
from pipeline.mcp_tools import MCPToolset
from storage.neon_store import get_store
from tau.tau_engine import TAUEngine
from tools.code_workspace import CodeWorkspace

router = APIRouter(prefix="/code")
_APPROVALS = "code_approval"


async def _target(request: Request) -> tuple[dict, CodeWorkspace]:
    body = await request.json()
    provider, repo = body.get("provider", "github"), (body.get("repo") or "").strip()
    if not valid_target(provider, repo):
        raise HTTPException(400, "provider must be github/gitlab and repo like owner/name")
    return body, CodeWorkspace(provider, repo)


def _branch(body: dict) -> str:
    branch = (body.get("branch") or "").strip()
    return branch if re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", branch) and ".." not in branch else ""


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
    agent = CodeAgent(ws, mode=body.get("mode") or "act", provider=body.get("model") or "auto", mcp=mcp, pr_token=token,
                      branch=_branch(body))
    agent.user_context = await TAUEngine().owner_context()

    async def stream():
        try:
            async for event in agent.run(message, body.get("history") or []):
                if event["type"] == "approval" and event["id"] in agent.pending:
                    # Kept server-side (an hour): Approve can only run exactly what was shown, and a secret's
                    # value never goes back to the browser.
                    ddb_backend.set(_APPROVALS, f"{account['account_id']}:{event['id']}",
                                    json.dumps({**agent.pending[event["id"]], "provider": ws.provider, "repo": ws.repo}),
                                    ttl=3600)
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:  # surface it in the UI instead of a silently dead stream
            yield f"data: {json.dumps({'type': 'error', 'text': f'Code agent crashed: {str(e)[:300]}'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/execute")
async def execute(request: Request, account: dict = Depends(require_account)):
    """Runs one approved action (merge, push, workflow run, re-run, secret)."""
    body = await request.json()
    key = f"{account['account_id']}:{body.get('id', '')}"
    saved = ddb_backend.get(_APPROVALS, key)
    if not saved:
        raise HTTPException(404, "This approval expired — ask Sem Code again")
    action = json.loads(saved)
    if action["name"] not in APPROVAL_ACTIONS:
        raise HTTPException(400, "not an approvable action")
    ws = CodeWorkspace(action["provider"], action["repo"])
    token = await connector_token(account["account_id"], ws.provider)
    if not token and action["name"] != "aws_action":
        raise HTTPException(400, f"Connect {ws.provider} first")
    ddb_backend.delete(_APPROVALS, key)  # one approval, one run
    result = await run_code_action(ws, token, action["name"], action["args"])
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or result.get("message") or "action failed")
    return result


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
    result = await open_pr(ws, token, body.get("title") or "", body.get("body") or "", _branch(body))
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
