import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from config import settings
from gateway.auth import issue_token, require_account, verify_passphrase
from pipeline.bootstrap import Bootstrap
from storage.neon_store import get_store
from tau.tau_engine import TAUEngine

router = APIRouter()
_tau = TAUEngine()


def _get_trust(request: Request) -> str:
    key = request.headers.get("x-api-key", "")
    if key == settings.SECRET_KEY:
        return "BYPASS"
    return settings.TRUST_MODE


@router.post("/auth/login")
async def login(request: Request):
    body = await request.json()
    passphrase = body.get("passphrase", "")
    if not passphrase:
        raise HTTPException(400, "passphrase required")

    db = await get_store()
    account = await db.get_account("owner")
    if not account or not verify_passphrase(passphrase, account["passphrase_hash"]):
        raise HTTPException(401, "Incorrect passphrase")

    return {"token": issue_token(account["id"], account["role"])}


@router.post("/chat")
async def chat(request: Request, trust: str = Depends(_get_trust), _account: dict = Depends(require_account)):
    body = await request.json()
    user_msg = body.get("message", "")
    session_id = body.get("session_id", "default")
    history = body.get("history", [])

    if not user_msg:
        raise HTTPException(400, "message required")

    tau_ctx = await _tau.observe_and_inject(session_id, user_msg, history)
    bootstrap = Bootstrap(trust_mode=trust, tau_context=tau_ctx)

    async def stream_gen():
        async for chunk in bootstrap.run(user_msg, session_id, history):
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream_gen(), media_type="text/event-stream")


@router.get("/status/{session_id}")
async def status(session_id: str, _account: dict = Depends(require_account)):
    return {"session_id": session_id, "status": "active"}


@router.get("/sessions")
async def sessions(_account: dict = Depends(require_account)):
    db = await get_store()
    return {"sessions": await db.list_sessions()}


@router.get("/history/{session_id}")
async def history(session_id: str, _account: dict = Depends(require_account)):
    db = await get_store()
    return {"session_id": session_id, "turns": await db.get_conversation(session_id)}


@router.get("/health")
async def health():
    return {"status": "ok", "version": "semblance-v9"}
