import time

import httpx

from config import settings

TOKEN_URL = "https://oauth2.googleapis.com/token"


async def get_google_token(account_id: str, scope_hint: str = "") -> str | dict:
    """Returns a valid access token for this account's Google connector
    (gateway/google_oauth.py, stored in the same account-scoped `connectors`
    table GitHub/GitLab already use, provider="google"), or an {"error":
    ...} dict if not connected. One OAuth connection covers every scope
    granted at consent time — Calendar, Gmail, Drive, Contacts all share
    it, so every Google tool calls this same helper rather than each
    managing its own token."""
    from storage.neon_store import get_store
    db = await get_store()
    connector = await db.get_connector(account_id, "google")
    if not connector:
        hint = f" ({scope_hint} needs it)" if scope_hint else ""
        return {"error": f"No Google connector configured for this account — connect Google first{hint}."}
    return await _ensure_fresh_token(account_id, connector, db)


async def _ensure_fresh_token(account_id: str, connector: dict, db) -> str:
    """Google's OAuth access tokens expire in ~1h; refreshes and persists
    the new one when it's within 60s of expiring, same pattern as
    gateway/connectors.py's _ensure_fresh_gitlab_token. Google's refresh
    response normally omits a new refresh_token — the original one keeps
    working indefinitely unless the user revokes access, so it's reused
    rather than treated as missing."""
    expires_at = connector.get("expires_at")
    refresh_token = connector.get("refresh_token")
    if not expires_at or not refresh_token or expires_at > time.time() + 60:
        return connector["token"]

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(TOKEN_URL, data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        r.raise_for_status()
        data = r.json()

    new_token = data["access_token"]
    new_expires_at = int(time.time()) + int(data["expires_in"]) if data.get("expires_in") else None
    await db.upsert_connector(account_id, "google", new_token, refresh_token, new_expires_at)
    return new_token
