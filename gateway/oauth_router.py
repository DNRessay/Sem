"""Sign-in for Claude's custom connectors (and any MCP client) — see gateway/mcp_oauth.py. Claude gets an
MCP key for the owner account after the passphrase is entered on this app's own page."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import settings
from gateway import mcp_oauth, ratelimit
from gateway.auth import current_version, issue_token
from gateway.passphrase import verify_passphrase
from storage.neon_store import get_store

router = APIRouter()
APP, SLUG = "SEMBLANCE", "semblance"
FIELDS = [("passphrase", "Passphrase", "password")]
MCP_KEY_TTL_SECONDS = 365 * 24 * 60 * 60
LOGIN_FAILS_PER_IP, LOGIN_FAILS_TOTAL, LOGIN_WINDOW_SECONDS = 5, 30, 15 * 60


def base_url(request: Request) -> str:
    if settings.PUBLIC_API_URL:
        return settings.PUBLIC_API_URL.rstrip("/")
    return f"{request.headers.get('x-forwarded-proto', 'https')}://{request.headers.get('host', '')}"


async def _check_passphrase(request: Request, passphrase: str) -> dict | None:
    ip = ratelimit.client_ip(request)
    if ratelimit.blocked("login", ip, LOGIN_FAILS_PER_IP) or ratelimit.blocked("login", "*", LOGIN_FAILS_TOTAL):
        raise HTTPException(429, "Too many wrong passphrases — wait 15 minutes")
    account = await (await get_store()).get_account("owner")
    if not account or not passphrase or not verify_passphrase(passphrase, account["passphrase_hash"]):
        ratelimit.record("login", ip, LOGIN_WINDOW_SECONDS)
        ratelimit.record("login", "*", LOGIN_WINDOW_SECONDS)
        return None
    ratelimit.clear("login", ip)
    return account


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
async def protected_resource(request: Request):
    return mcp_oauth.resource_metadata(base_url(request))


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/oauth-authorization-server/mcp")
async def authorization_server(request: Request):
    return mcp_oauth.server_metadata(base_url(request))


@router.post("/oauth/register")
async def register(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = {}
    status, data = mcp_oauth.register(body, settings.SECRET_KEY)
    return JSONResponse(data, status)


@router.get("/oauth/authorize")
async def authorize_page(request: Request):
    req, error = mcp_oauth.check_authorize(dict(request.query_params), settings.SECRET_KEY)
    return HTMLResponse(mcp_oauth.login_page(APP, req, FIELDS, error), 200 if req else 400)


@router.post("/oauth/authorize")
async def authorize(request: Request):
    form = dict(await request.form())
    req, error = mcp_oauth.check_authorize(form, settings.SECRET_KEY)
    if not req:
        return HTMLResponse(mcp_oauth.login_page(APP, None, FIELDS, error), 400)
    try:
        account = await _check_passphrase(request, form.get("passphrase", ""))
    except HTTPException as e:
        return HTMLResponse(mcp_oauth.login_page(APP, req, FIELDS, e.detail), 429)
    if not account:
        return HTMLResponse(mcp_oauth.login_page(APP, req, FIELDS, "Incorrect passphrase."), 401)
    return RedirectResponse(mcp_oauth.issue_code(account["id"], req, settings.SECRET_KEY), 302)


@router.post("/oauth/token")
async def token(request: Request):
    form = dict(await request.form())
    account_id, err = mcp_oauth.redeem(form, settings.SECRET_KEY, request.headers.get("authorization", ""))
    if not account_id:
        return JSONResponse(err, 401 if err.get("error") == "invalid_client" else 400)
    account = await (await get_store()).get_account(account_id)
    if not account:
        return JSONResponse({"error": "invalid_grant"}, 400)
    version = await current_version(account_id) or 0
    key = issue_token(account_id, account["role"], ttl_seconds=MCP_KEY_TTL_SECONDS, version=version)
    return JSONResponse({**mcp_oauth.token_response(key), "expires_in": MCP_KEY_TTL_SECONDS},
                        headers={"Cache-Control": "no-store"})


@router.get("/oauth/client")
async def client_page():
    return HTMLResponse(mcp_oauth.client_page(APP, "", None, FIELDS))


@router.post("/oauth/client")
async def client_details(request: Request):
    form = dict(await request.form())
    try:
        account = await _check_passphrase(request, form.get("passphrase", ""))
    except HTTPException as e:
        return HTMLResponse(mcp_oauth.client_page(APP, "", None, FIELDS, e.detail), 429)
    if not account:
        return HTMLResponse(mcp_oauth.client_page(APP, "", None, FIELDS, "Incorrect passphrase."), 401)
    return HTMLResponse(mcp_oauth.client_page(APP, base_url(request) + "/mcp", mcp_oauth.own_client(SLUG, settings.SECRET_KEY), FIELDS),
                        headers={"Cache-Control": "no-store"})
