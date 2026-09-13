from fastapi import APIRouter, HTTPException, Request

from config import settings
from pipeline.bootstrap import Bootstrap
from tau.tau_engine import TAUEngine
from tools.openclaw_bridge import OpenClawBridge

webhook_router = APIRouter(prefix="/webhook")
_bridge = OpenClawBridge()
_tau = TAUEngine()


@webhook_router.post("/openclaw")
async def openclaw_inbound(request: Request):
    """
    Optional integration: OpenClaw posts inbound messages here when a user
    messages via WhatsApp, Telegram, Slack etc. Requires a self-hosted OpenClaw
    gateway (OPENCLAW_URL) — not part of the core deploy, disabled unless set.
    """
    if not settings.OPENCLAW_URL:
        raise HTTPException(503, "OpenClaw integration not configured (OPENCLAW_URL unset)")
    payload = await request.json()
    ctx = await _bridge.webhook_receive(payload)

    session_id = ctx["session_id"]
    message = ctx["message"]
    channel = ctx["channel"]

    tau_ctx = await _tau.observe_and_inject(session_id, message, [])
    bootstrap = Bootstrap(tau_context=tau_ctx)

    response_chunks = []
    async for chunk in bootstrap.run(message, session_id, []):
        response_chunks.append(chunk)

    response = "".join(response_chunks)
    await _bridge.send_message(channel, response, session_id)

    return {"status": "ok"}


@webhook_router.post("/github")
async def github_webhook(request: Request):
    """GitHub webhook - PR/issue events forwarded from OpenClaw."""
    await request.json()  # not yet acted on — placeholder receiver
    event = request.headers.get("x-github-event", "unknown")
    return {"event": event, "status": "received"}
