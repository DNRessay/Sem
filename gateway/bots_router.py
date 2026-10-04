import hashlib
import hmac
import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from config import settings
from gateway.auth import require_account
from pipeline import bots
from pipeline.activity import log
from pipeline.mcp_tools import MCPToolset
from pipeline.runs import durable

router = APIRouter(prefix="/bots")
public = APIRouter(prefix="/webhook/bots")
GRAPH = "https://graph.facebook.com/v21.0"
WHATSAPP_LIMIT = 4000


def _view(bot: dict, connected: bool) -> dict:
    """A bot for the app: the webhook details to paste into Meta, never the secrets."""
    wa = bot["whatsapp"]
    return {**bot, "whatsapp": {**wa, "connected": connected,
                                "webhook_url": f"{settings.PUBLIC_API_URL.rstrip('/')}/webhook/bots/{bot['id']}"}}


@router.get("")
async def list_bots(account: dict = Depends(require_account)):
    acct = account["account_id"]
    out = []
    for b in await bots.list_bots(acct):
        token, _ = await bots.whatsapp_secrets(acct, b["id"])
        out.append(_view(b, bool(token)))
    return {"bots": out, "tools": {"public": bots.PUBLIC_TOOLS, "private": bots.PRIVATE_TOOLS, "app_only": bots.APP_ONLY_TOOLS}}


@router.post("/draft")
async def draft(request: Request, _account: dict = Depends(require_account)):
    body = await request.json()
    if not (body.get("description") or "").strip():
        raise HTTPException(400, "Describe the bot first")
    result = await bots.draft_bot(body["description"], body.get("model") or "auto")
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result


@router.post("")
async def create(request: Request, account: dict = Depends(require_account)):
    acct = account["account_id"]
    existing = await bots.list_bots(acct)
    if len(existing) >= bots.MAX_BOTS:
        raise HTTPException(400, f"You can have up to {bots.MAX_BOTS} bots")
    bot = bots.clean_bot(await request.json())
    await bots.save_bots(acct, [bot, *existing])
    await bots.remember_owner(acct, bot["id"])
    return _view(bot, False)


@router.put("/{bot_id}")
async def update(bot_id: str, request: Request, account: dict = Depends(require_account)):
    acct = account["account_id"]
    all_bots = await bots.list_bots(acct)
    old = next((b for b in all_bots if b["id"] == bot_id), None)
    if not old:
        raise HTTPException(404, "No such bot")
    bot = bots.clean_bot(await request.json(), old)
    await bots.save_bots(acct, [bot if b["id"] == bot_id else b for b in all_bots])
    token, _ = await bots.whatsapp_secrets(acct, bot_id)
    return _view(bot, bool(token))


@router.delete("/{bot_id}")
async def delete(bot_id: str, account: dict = Depends(require_account)):
    acct = account["account_id"]
    all_bots = await bots.list_bots(acct)
    if not any(b["id"] == bot_id for b in all_bots):
        raise HTTPException(404, "No such bot")
    await bots.save_bots(acct, [b for b in all_bots if b["id"] != bot_id])
    await bots.forget_whatsapp(acct, bot_id)
    return {"ok": True}


@router.post("/{bot_id}/chat")
async def chat(bot_id: str, request: Request, account: dict = Depends(require_account)):
    """Talk to a bot in the app (with every tool you gave it; email/events wait for Approve, as in Co-work)."""
    acct = account["account_id"]
    bot = await bots.get_bot(acct, bot_id)
    if not bot:
        raise HTTPException(404, "No such bot")
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message required")
    agent = bots.BotAgent(acct, bot, "app", mcp=await MCPToolset.for_account(acct))

    async def stream():
        try:
            async for event in agent.run(message, body.get("history") or []):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            failed = {"type": "error", "text": f"{bot['name']} crashed: {str(e)[:300]}"}
            yield f"data: {json.dumps(failed)}\n\n"
        yield "data: [DONE]\n\n"

    return durable(stream(), acct, body, "bots")


async def _graph(method: str, path: str, token: str, **kw) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.request(method, f"{GRAPH}/{path}", headers={"Authorization": f"Bearer {token}"}, **kw)
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"error": {"message": f"WhatsApp unreachable: {type(e).__name__}"}}
    return data


@router.post("/{bot_id}/whatsapp")
async def connect_whatsapp(bot_id: str, request: Request, account: dict = Depends(require_account)):
    """Puts the bot on a WhatsApp Cloud API number: checks the token against the phone number id, keeps the
    token and app secret server-side, and returns the webhook URL + verify token to paste into Meta."""
    acct = account["account_id"]
    all_bots = await bots.list_bots(acct)
    old = next((b for b in all_bots if b["id"] == bot_id), None)
    if not old:
        raise HTTPException(404, "No such bot")
    body = await request.json()
    phone_id = "".join(ch for ch in str(body.get("phone_number_id") or old["whatsapp"]["phone_number_id"]) if ch.isdigit())
    token, app_secret = (body.get("token") or "").strip(), (body.get("app_secret") or "").strip()
    saved_token, saved_secret = await bots.whatsapp_secrets(acct, bot_id)
    token, app_secret = token or saved_token, app_secret or saved_secret
    if not phone_id or not token or not app_secret:
        raise HTTPException(400, "Phone number ID, access token and app secret are all needed")
    info = await _graph("GET", phone_id, token, params={"fields": "display_phone_number,verified_name"})
    if info.get("error"):
        raise HTTPException(400, f"WhatsApp said: {info['error'].get('message', 'token or phone number ID is wrong')}")
    await bots.set_whatsapp_secrets(acct, bot_id, token, app_secret)
    bot = bots.clean_bot({"whatsapp": {"phone_number_id": phone_id, "display_number": info.get("display_phone_number", ""),
                                       "trusted": body.get("trusted", old["whatsapp"].get("trusted", [])),
                                       "enabled": True}}, old)
    await bots.save_bots(acct, [bot if b["id"] == bot_id else b for b in all_bots])
    await bots.remember_owner(acct, bot_id)
    return _view(bot, True)


@router.delete("/{bot_id}/whatsapp")
async def disconnect_whatsapp(bot_id: str, account: dict = Depends(require_account)):
    acct = account["account_id"]
    all_bots = await bots.list_bots(acct)
    old = next((b for b in all_bots if b["id"] == bot_id), None)
    if not old:
        raise HTTPException(404, "No such bot")
    await bots.forget_whatsapp(acct, bot_id)
    bot = bots.clean_bot({"whatsapp": {"enabled": False}}, old)
    await bots.save_bots(acct, [bot if b["id"] == bot_id else b for b in all_bots])
    return _view(bot, False)


# ── WhatsApp webhooks (public: Meta calls these) ────────────────────────────

@public.get("/{bot_id}")
async def whatsapp_verify(bot_id: str, request: Request):
    found = await bots.find_bot(bot_id)
    p = request.query_params
    if found and p.get("hub.mode") == "subscribe" and hmac.compare_digest(
            p.get("hub.verify_token", ""), found[1]["whatsapp"]["verify_token"]):
        return PlainTextResponse(p.get("hub.challenge", ""))
    raise HTTPException(403, "Verification failed")


def _chunks(text: str) -> list[str]:
    out = []
    while text:
        cut = text.rfind("\n", 0, WHATSAPP_LIMIT) if len(text) > WHATSAPP_LIMIT else len(text)
        cut = cut if cut > 0 else WHATSAPP_LIMIT
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    return [c for c in out if c]


@public.post("/{bot_id}")
async def whatsapp_inbound(bot_id: str, request: Request):
    """A message to the bot's WhatsApp number. Only Meta-signed deliveries are answered; always 200 otherwise
    Meta retries the delivery (and duplicates are skipped by message id)."""
    raw = await request.body()
    found = await bots.find_bot(bot_id)
    if not found:
        return {"status": "ignored"}
    acct, bot = found
    token, app_secret = await bots.whatsapp_secrets(acct, bot_id)
    if not token or not app_secret or not bot["whatsapp"].get("enabled"):
        return {"status": "ignored", "reason": "bot isn't connected"}
    want = "sha256=" + hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, request.headers.get("x-hub-signature-256", "")):
        raise HTTPException(401, "Bad signature")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return {"status": "ignored"}
    phone_id = bot["whatsapp"]["phone_number_id"]
    answered = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in (change.get("value") or {}).get("messages", []):
                sender, text = msg.get("from", ""), ((msg.get("text") or {}).get("body") or "").strip()
                if msg.get("type") != "text" or not sender or not text:
                    continue
                if await bots.seen_message(bot_id, msg.get("id") or f"{sender}:{text}"):
                    continue
                trusted = sender in bot["whatsapp"].get("trusted", [])
                past = await bots.history(bot_id, sender)
                agent = bots.BotAgent(acct, bot, "whatsapp", trusted=trusted, deadline_seconds=22)
                reply = []
                async for event in agent.run(text, past):
                    if event.get("type") == "text":
                        reply.append(event["text"])
                answer = "\n\n".join(r.strip() for r in reply if r.strip()) or \
                    "Sorry, I couldn't answer that just now. Please try again."
                for part in _chunks(answer):
                    await _graph("POST", f"{phone_id}/messages", token, json={
                        "messaging_product": "whatsapp", "to": sender, "type": "text", "text": {"body": part}})
                await bots.save_history(bot_id, sender, [*past, {"role": "user", "content": text},
                                                         {"role": "assistant", "content": answer}])
                await log(f"bots:{bot_id}", "bots", f"ok:WhatsApp {'trusted ' if trusted else ''}…{sender[-4:]} answered")
                answered += 1
    return {"status": "ok", "answered": answered}
