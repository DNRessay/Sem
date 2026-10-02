"""Passphrase reset by email. Only addresses listed in RESET_EMAILS (a GitHub secret) can get a link; mail goes
out through SES from the verified vicinic.co.za domain. The link is single-use, lasts 30 minutes and carries the
token in the #fragment so it never reaches a server log. Setting a new passphrase signs out every other session."""
import asyncio
import hashlib
import json
import logging
import re
import secrets

from fastapi import APIRouter, HTTPException, Request

from cache import ddb_backend
from config import settings
from gateway import ratelimit
from gateway.auth import forget_version, issue_token
from gateway.passphrase import hash_passphrase
from storage.neon_store import get_store

router = APIRouter(prefix="/auth/reset")
log = logging.getLogger(__name__)

_NS = "pw_reset"
LINK_TTL_SECONDS = 30 * 60
MIN_PASSPHRASE = 12
SENT_MESSAGE = "If that address is allowed, a reset link is on its way. It works once, for 30 minutes."


def allowed_emails() -> set[str]:
    return {e.strip().lower() for e in re.split(r"[,; ]+", settings.RESET_EMAILS) if "@" in e}


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _send(to: str, subject: str, text: str) -> None:
    import boto3

    boto3.client("ses", region_name=settings.SES_REGION).send_email(
        Source=settings.SES_FROM_EMAIL,
        Destination={"ToAddresses": [to]},
        Message={"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body": {"Text": {"Data": text, "Charset": "UTF-8"}}},
    )


async def send_mail(to: str, subject: str, text: str) -> bool:
    try:
        await asyncio.to_thread(_send, to, subject, text)
        return True
    except Exception as e:  # logged for the owner; the caller still gets the same answer
        log.error("reset email to %s failed: %s", to.split("@")[-1], str(e)[:200])
        return False


def passphrase_problem(passphrase: str) -> str:
    if len(passphrase) < MIN_PASSPHRASE:
        return f"Use at least {MIN_PASSPHRASE} characters — a few words strung together works well."
    if passphrase.isdigit() or len(set(passphrase)) < 5:
        return "That's too easy to guess — mix in more different characters."
    return ""


@router.post("/request")
async def request_reset(request: Request):
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()[:254]
    ip = ratelimit.client_ip(request)
    if ratelimit.blocked("reset_ip", ip, 5) or (email and ratelimit.blocked("reset_email", email, 3)):
        raise HTTPException(429, "Too many reset requests — try again in an hour")
    ratelimit.record("reset_ip", ip, 3600)
    if email in allowed_emails():
        ratelimit.record("reset_email", email, 3600)
        token = secrets.token_urlsafe(32)
        ddb_backend.set(_NS, _key(token), json.dumps({"account": settings.OWNER_ACCOUNT_ID, "email": email}),
                        ttl=LINK_TTL_SECONDS)
        link = f"{settings.FRONTEND_URL.rstrip('/')}/#reset={token}"
        await send_mail(email, "Reset your SEMBLANCE passphrase",
                        f"Someone (hopefully you) asked to reset the SEMBLANCE passphrase.\n\n"
                        f"Set a new one here — the link works once, for 30 minutes:\n{link}\n\n"
                        f"Didn't ask for this? Ignore this email; nothing changes.")
    return {"message": SENT_MESSAGE}


@router.post("/confirm")
async def confirm_reset(request: Request):
    body = await request.json()
    token, passphrase = str(body.get("token") or ""), str(body.get("passphrase") or "")
    ip = ratelimit.client_ip(request)
    if ratelimit.blocked("reset_confirm", ip, 10):
        raise HTTPException(429, "Too many tries — wait an hour and ask for a new link")
    problem = passphrase_problem(passphrase)
    if problem:
        raise HTTPException(400, problem)
    raw = ddb_backend.get(_NS, _key(token)) if token else None
    if not raw:
        ratelimit.record("reset_confirm", ip, 3600)
        raise HTTPException(400, "This reset link is invalid or has expired — ask for a new one")
    ddb_backend.delete(_NS, _key(token))  # single use, whatever happens next
    data = json.loads(raw)

    db = await get_store()
    hashed = hash_passphrase(passphrase)
    version = await db.set_passphrase(data["account"], hashed)
    if version is None:  # no account row yet: create it
        await db.upsert_account(data["account"], hashed)
        version = 0
    account = await db.get_account(data["account"])
    forget_version(data["account"])
    ratelimit.clear("login", ip)
    ratelimit.clear("login", "*")
    await send_mail(data["email"], "Your SEMBLANCE passphrase was changed",
                    "The SEMBLANCE passphrase was just changed and every other device was signed out.\n\n"
                    "If this wasn't you, reset it again straight away from the login page.")
    return {"token": issue_token(data["account"], (account or {}).get("role", "owner"), version=version)}
