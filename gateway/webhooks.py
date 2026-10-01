import hashlib
import hmac
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from config import settings
from pipeline import activity
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


GITHUB_LOG = "github"


def _github_signed(body: bytes, header: str) -> bool:
    if not settings.GITHUB_WEBHOOK_SECRET:
        return True
    want = "sha256=" + hmac.new(settings.GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header or "")


def _github_alert(event: str, p: dict) -> tuple[str, str] | None:
    repo = (p.get("repository") or {}).get("full_name", "")
    if event == "workflow_run" and p.get("action") == "completed":
        run = p.get("workflow_run") or {}
        if run.get("conclusion") in ("failure", "timed_out"):
            commit = ((run.get("head_commit") or {}).get("message") or "").split("\n")[0]
            return (f"CI failed: {repo}",
                    f"{run.get('name', 'Workflow')} failed on {run.get('head_branch', '?')}"
                    f"{f' ({commit})' if commit else ''}.\n{run.get('html_url', '')}")
    if event == "issues" and p.get("action") == "opened":
        issue = p.get("issue") or {}
        return (f"New issue: {repo}",
                f"#{issue.get('number')} {issue.get('title', '')} by {(issue.get('user') or {}).get('login', '?')}\n"
                f"{issue.get('html_url', '')}")
    return None


def _github_line(event: str, p: dict) -> str:
    repo = (p.get("repository") or {}).get("full_name", "")
    action = p.get("action", "")
    if event == "pull_request":
        pr = p.get("pull_request") or {}
        merged = " (merged)" if action == "closed" and pr.get("merged") else ""
        return f"{repo} PR #{pr.get('number')} {action}{merged}: {pr.get('title', '')}"
    if event == "push":
        return f"{repo} push to {p.get('ref', '').removeprefix('refs/heads/')}: {len(p.get('commits') or [])} commit(s)"
    return f"{repo} {event} {action}".strip()


@webhook_router.post("/github")
async def github_webhook(request: Request):
    """Add this URL as a repo webhook (content type JSON; events: workflow
    runs, issues, pull requests, pushes). Failed CI runs and new issues are
    delivered like reminders (app chat + WhatsApp when set); every event is
    written to the "github" activity log. Set GITHUB_WEBHOOK_SECRET to the
    webhook's secret and unsigned calls are refused."""
    body = await request.body()
    if not _github_signed(body, request.headers.get("x-hub-signature-256", "")):
        raise HTTPException(401, "Bad signature")
    event = request.headers.get("x-github-event", "unknown")
    if event == "ping":
        return {"event": event, "status": "ok"}
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Body must be JSON")
    await activity.log(GITHUB_LOG, "github", _github_line(event, payload))
    alert = _github_alert(event, payload)
    sent = []
    if alert:
        from agents.kairos import deliver
        sent = await deliver(settings.OWNER_ACCOUNT_ID, *alert)
    return {"event": event, "status": "received", "delivered": sent}
