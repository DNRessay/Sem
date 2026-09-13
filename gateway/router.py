import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from config import settings
from pipeline.bootstrap import Bootstrap
from tau.tau_engine import TAUEngine

router = APIRouter()
_tau = TAUEngine()


def _get_trust(request: Request) -> str:
    key = request.headers.get("x-api-key", "")
    if key == settings.SECRET_KEY:
        return "BYPASS"
    return settings.TRUST_MODE


@router.post("/chat")
async def chat(request: Request, trust: str = Depends(_get_trust)):
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
async def status(session_id: str):
    return {"session_id": session_id, "status": "active"}


@router.get("/health")
async def health():
    return {"status": "ok", "version": "semblance-v9"}
