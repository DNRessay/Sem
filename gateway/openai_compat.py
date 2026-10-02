"""An OpenAI-style /v1/chat/completions endpoint so OpenAI-compatible clients
can talk to SEMBLANCE itself (its memory, tools and free model chain) — e.g.
AvaTa's avatar bridge: AI_BASE_URL=<Sem>/v1, AI_API_KEY=<a Sem MCP key>.
The client's system prompt (AvaTa's avatar tags) rides along as reply-style
guidance; the conversation is saved like any other Sem chat."""
import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from gateway.auth import require_account
from pipeline.bootstrap import Bootstrap
from tau.tau_engine import TAUEngine

router = APIRouter(prefix="/v1")
_tau = TAUEngine()
_VOICE = ("[This is a spoken conversation through a talking avatar: answer briefly and naturally, no markdown, "
          "no lists or code blocks.]")


def _split(messages: list[dict]) -> tuple[str, str, list[dict]]:
    system = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
    turns = [m for m in messages if m.get("role") in ("user", "assistant") and m.get("content")]
    if not turns or turns[-1]["role"] != "user":
        raise HTTPException(400, "the last message must be from the user")
    history = [{"role": m["role"], "content": str(m["content"])} for m in turns[:-1]][-20:]
    return system, str(turns[-1]["content"]), history


def _chunk(cid: str, delta: dict, finish: str | None = None) -> str:
    return "data: " + json.dumps({"id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": "semblance", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"


@router.get("/models")
async def models(_account: dict = Depends(require_account)):
    return {"object": "list", "data": [{"id": "semblance", "object": "model", "owned_by": "semblance"}]}


@router.post("/chat/completions")
async def chat_completions(request: Request, account: dict = Depends(require_account)):
    body = await request.json()
    system, text, history = _split(body.get("messages") or [])
    session_id = f"avatar:{account['account_id']}"
    query = f"{text}\n\n{_VOICE}" + (f"\n[Reply style from the client:]\n{system[:3000]}" if system else "")
    tau_ctx = await _tau.observe_and_inject(session_id, text, history)
    bootstrap = Bootstrap(tau_context=tau_ctx)

    async def pieces():
        async for piece in bootstrap.run(query, session_id, history, display_query=text, use_tools=True):
            if isinstance(piece, str) and piece:
                yield piece

    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    if not body.get("stream"):
        reply = "".join([p async for p in pieces()])
        return JSONResponse({"id": cid, "object": "chat.completion", "created": int(time.time()), "model": "semblance",
                             "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}]})

    async def stream():
        yield _chunk(cid, {"role": "assistant"})
        try:
            async for piece in pieces():
                yield _chunk(cid, {"content": piece})
        except Exception as e:  # say it rather than going silent on the avatar
            yield _chunk(cid, {"content": f"Sorry, I hit a problem: {str(e)[:200]}"})
        yield _chunk(cid, {}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
