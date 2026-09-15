from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

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


@webhook_router.get("/whatsapp")
async def whatsapp_verify(request: Request):
    """Meta's one-time webhook handshake — required before it will start
    POSTing inbound messages. Register this exact URL in the Meta App
    Dashboard's WhatsApp > Configuration > Webhook settings, with a
    verify token matching WHATSAPP_VERIFY_TOKEN."""
    params = request.query_params
    token_set = bool(settings.WHATSAPP_VERIFY_TOKEN)
    if (
        token_set
        and params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.WHATSAPP_VERIFY_TOKEN
    ):
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(403, "Verification failed")


@webhook_router.post("/whatsapp")
async def whatsapp_inbound(request: Request):
    """WhatsApp Cloud API posts inbound messages here directly — no
    OpenClaw/gateway process needed, just this app's own Meta Graph API
    credentials (WHATSAPP_TOKEN/WHATSAPP_PHONE_ID, the same ones
    tools.misc.whatsapp_tool.WhatsAppTool already uses for outbound
    sends). Session is keyed "whatsapp:<phone>" so a WhatsApp
    conversation and any web-chat session for the same person never
    collide. Only plain text messages are handled for now — media/
    location/interactive message types are silently skipped rather than
    erroring, since WhatsApp retries the whole delivery on anything but
    a 200. Always returns 200 for that reason."""
    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue
                phone = msg.get("from", "")
                text = (msg.get("text") or {}).get("body", "")
                if not phone or not text:
                    continue

                session_id = f"whatsapp:{phone}"
                tau_ctx = await _tau.observe_and_inject(session_id, text, [])
                bootstrap = Bootstrap(tau_context=tau_ctx)

                reply_chunks = []
                async for chunk in bootstrap.run(text, session_id, []):
                    reply_chunks.append(chunk)
                reply = "".join(reply_chunks)

                if reply:
                    from tools.misc.whatsapp_tool import WhatsAppTool
                    await WhatsAppTool().send(phone, reply)

    return {"status": "ok"}


@webhook_router.post("/github")
async def github_webhook(request: Request):
    """GitHub webhook - PR/issue events forwarded from OpenClaw."""
    await request.json()  # not yet acted on — placeholder receiver
    event = request.headers.get("x-github-event", "unknown")
    return {"event": event, "status": "received"}
