import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from config import settings
from gateway.auth import require_account
from gateway.connectors import _callback_page, _make_state, _verify_state
from storage.neon_store import get_store

router = APIRouter()

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# One consent screen covers every Google tool this app has (Calendar,
# Gmail, Drive, Contacts) — narrowest scope each supports for what was
# actually asked: Calendar full read/write (create/edit/delete events),
# Gmail read + send only (not full modify/delete/trash), Drive via
# drive.file (app-created files only, not the much broader full-Drive
# scope), Contacts read-only (no write was requested).
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/contacts.readonly",
]


@router.get("/connectors/google/authorize")
async def authorize(account: dict = Depends(require_account)):
    """Same shape as gateway/connectors.py's GitHub/GitLab /authorize —
    see its docstring for why the signed state embeds the account id.
    Two extra params Google specifically needs that GitHub/GitLab don't:
    access_type=offline (without it, no refresh_token comes back — the
    connection would silently stop working once the ~1h access token
    expires) and prompt=consent (Google otherwise skips the consent
    screen on a repeat connection and omits the refresh_token then too)."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            400,
            "Google OAuth isn't configured on this deployment yet "
            "(GOOGLE_CLIENT_ID is unset) — see config.py's comment for setup steps.",
        )
    if not settings.PUBLIC_API_URL:
        raise HTTPException(400, "PUBLIC_API_URL isn't configured on this deployment yet")

    redirect_uri = f"{settings.PUBLIC_API_URL}/connectors/google/callback"
    state = _make_state("google", account["account_id"])
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = f"{AUTHORIZE_URL}?{httpx.QueryParams(params)}"
    return {"url": url}


@router.get("/connectors/google/callback")
async def oauth_callback(request: Request):
    """Hit by the browser as a plain redirect from Google after consent —
    deliberately NOT behind require_account, same reasoning as
    gateway/connectors.py's callback: there's no Authorization header on a
    browser navigation, so the signed `state` param is this endpoint's
    only security, not the auth dependency."""
    code = request.query_params.get("code")
    state = request.query_params.get("state", "")
    error = request.query_params.get("error")
    if error:
        return _callback_page("google", ok=False, message=request.query_params.get("error_description", error))
    account_id = _verify_state(state, "google")
    if not code or not account_id:
        return _callback_page("google", ok=False, message="Invalid or expired authorization request — try connecting again.")

    redirect_uri = f"{settings.PUBLIC_API_URL}/connectors/google/callback"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(TOKEN_URL, data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        return _callback_page("google", ok=False, message=f"Token exchange failed: {e}")

    access_token = data.get("access_token")
    if not access_token:
        return _callback_page("google", ok=False, message=f"No access_token in response: {data}")

    refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")
    expires_at = int(time.time()) + int(expires_in) if expires_in else None

    db = await get_store()
    await db.upsert_connector(account_id, "google", access_token, refresh_token, expires_at)
    return _callback_page("google", ok=True)
