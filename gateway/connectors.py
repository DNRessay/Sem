import base64
import hashlib
import hmac
import json
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from config import settings
from gateway.auth import require_account
from storage.neon_store import get_store

router = APIRouter()

_PROVIDERS = {"github", "gitlab"}
_MAX_FETCH_CHARS = 60_000  # keeps one repo file from blowing the model's context on its own

_OAUTH = {
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scope": "repo",
        "client_id": lambda: settings.GITHUB_CLIENT_ID,
        "client_secret": lambda: settings.GITHUB_CLIENT_SECRET,
    },
    "gitlab": {
        "authorize_url": "https://gitlab.com/oauth/authorize",
        "token_url": "https://gitlab.com/oauth/token",
        "scope": "api",
        "client_id": lambda: settings.GITLAB_CLIENT_ID,
        "client_secret": lambda: settings.GITLAB_CLIENT_SECRET,
    },
}


@router.get("/connectors")
async def list_connectors(account: dict = Depends(require_account)):
    db = await get_store()
    return {"connectors": await db.list_connectors(account["account_id"])}


@router.post("/connectors/{provider}")
async def save_connector(provider: str, request: Request, account: dict = Depends(require_account)):
    if provider not in _PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}' — must be one of {sorted(_PROVIDERS)}")
    body = await request.json()
    token = (body.get("token") or "").strip()
    if not token:
        raise HTTPException(400, "token required")

    db = await get_store()
    await db.upsert_connector(account["account_id"], provider, token)
    return {"provider": provider, "connected": True}


@router.delete("/connectors/{provider}")
async def remove_connector(provider: str, account: dict = Depends(require_account)):
    db = await get_store()
    await db.delete_connector(account["account_id"], provider)
    return {"provider": provider, "connected": False}


@router.get("/connectors/{provider}/authorize")
async def authorize(provider: str, account: dict = Depends(require_account)):
    """Returns the URL to send the browser to for the provider's OAuth
    consent screen. Requires a real Bearer token to call (this is a normal
    authenticated fetch from the app, not the browser redirect itself) — the
    signed state it mints embeds *this* account's id, so any SEMBLANCE user
    (owner or guest) can connect their own GitHub/GitLab independently and
    the callback (which has no Authorization header to read account_id
    from) still knows whose connector row to write."""
    if provider not in _PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}' — must be one of {sorted(_PROVIDERS)}")
    cfg = _OAUTH[provider]
    client_id = cfg["client_id"]()
    if not client_id:
        raise HTTPException(
            400,
            f"{provider} OAuth isn't configured on this deployment yet "
            f"({provider.upper()}_CLIENT_ID is unset) — paste a personal access token instead for now.",
        )
    if not settings.PUBLIC_API_URL:
        raise HTTPException(400, "PUBLIC_API_URL isn't configured on this deployment yet")

    redirect_uri = f"{settings.PUBLIC_API_URL}/connectors/{provider}/callback"
    state = _make_state(provider, account["account_id"])
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": cfg["scope"],
        "state": state,
    }
    if provider == "gitlab":
        params["response_type"] = "code"
    url = f"{cfg['authorize_url']}?{httpx.QueryParams(params)}"
    return {"url": url}


@router.get("/connectors/{provider}/callback")
async def oauth_callback(provider: str, request: Request):
    """Hit by the browser as a plain redirect from GitHub/GitLab after the
    user approves — there's no Authorization header on a browser navigation,
    so this endpoint is deliberately NOT behind require_account. Its own
    security is the signed `state` param: it only accepts a code paired with
    a state this same app minted (via /authorize, which IS authenticated)
    less than 10 minutes ago for this exact provider."""
    if provider not in _PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}'")

    code = request.query_params.get("code")
    state = request.query_params.get("state", "")
    error = request.query_params.get("error")
    if error:
        return _callback_page(provider, ok=False, message=request.query_params.get("error_description", error))
    account_id = _verify_state(state, provider)
    if not code or not account_id:
        return _callback_page(provider, ok=False, message="Invalid or expired authorization request — try connecting again.")

    cfg = _OAUTH[provider]
    redirect_uri = f"{settings.PUBLIC_API_URL}/connectors/{provider}/callback"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                cfg["token_url"],
                data={
                    "client_id": cfg["client_id"](),
                    "client_secret": cfg["client_secret"](),
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        return _callback_page(provider, ok=False, message=f"Token exchange failed: {e}")

    access_token = data.get("access_token")
    if not access_token:
        return _callback_page(provider, ok=False, message=f"No access_token in response: {data}")

    refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")
    expires_at = int(time.time()) + int(expires_in) if expires_in else None

    db = await get_store()
    await db.upsert_connector(account_id, provider, access_token, refresh_token, expires_at)
    return _callback_page(provider, ok=True)


def _callback_page(provider: str, ok: bool, message: str = "") -> HTMLResponse:
    title = f"{provider.capitalize()} connected" if ok else f"{provider.capitalize()} connection failed"
    body = "You can close this tab and go back to SEMBLANCE." if ok else message
    return HTMLResponse(f"<title>{title}</title><body style='font-family:sans-serif;padding:40px;text-align:center'>"
                         f"<h2>{title}</h2><p>{body}</p></body>")


def _make_state(provider: str, account_id: str) -> str:
    payload = json.dumps({"provider": provider, "account_id": account_id, "exp": int(time.time()) + 600}).encode()
    sig = hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).digest()
    return _b64url(payload) + "." + _b64url(sig)


def _verify_state(state: str, provider: str) -> str | None:
    """Returns the embedded account_id if the state is a valid, unexpired,
    unmodified state minted for this provider — None otherwise."""
    try:
        payload_b64, sig_b64 = state.split(".")
        payload = _b64url_decode(payload_b64)
        sig = _b64url_decode(sig_b64)
        expected_sig = hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        data = json.loads(payload)
        if data.get("provider") != provider or data.get("exp", 0) <= time.time():
            return None
        return data.get("account_id")
    except Exception:
        return None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


@router.get("/connectors/{provider}/repos")
async def list_repos(provider: str, account: dict = Depends(require_account)):
    """Lists the connected account's own repos, so the frontend can offer a
    dropdown instead of asking the user to type "owner/repo" from memory."""
    if provider not in _PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}' — must be one of {sorted(_PROVIDERS)}")

    db = await get_store()
    connector = await db.get_connector(account["account_id"], provider)
    if not connector:
        raise HTTPException(400, f"No {provider} connector configured — add a token first")

    try:
        if provider == "github":
            repos = await _list_github_repos(connector["token"])
        else:
            token = await _ensure_fresh_gitlab_token(account["account_id"], connector, db)
            repos = await _list_gitlab_repos(token)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"{provider} error: {e.response.text[:300]}")

    return {"provider": provider, "repos": repos}


async def _list_github_repos(token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            "https://api.github.com/user/repos",
            params={"sort": "updated", "per_page": 100},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
    return [
        {"full_name": d["full_name"], "private": d.get("private", False), "default_branch": d.get("default_branch")}
        for d in data
    ]


async def _list_gitlab_repos(token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            "https://gitlab.com/api/v4/projects",
            params={"membership": "true", "order_by": "last_activity_at", "per_page": 100},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
    return [
        {
            "full_name": d["path_with_namespace"],
            "private": d.get("visibility") != "public",
            "default_branch": d.get("default_branch"),
        }
        for d in data
    ]


@router.get("/connectors/{provider}/branches")
async def list_branches(provider: str, repo: str, account: dict = Depends(require_account)):
    """Lists a repo's branches, so ref selection can be a dropdown instead of
    a free-text field the user has to already know."""
    if provider not in _PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}' — must be one of {sorted(_PROVIDERS)}")
    if not repo:
        raise HTTPException(400, "repo required")

    db = await get_store()
    connector = await db.get_connector(account["account_id"], provider)
    if not connector:
        raise HTTPException(400, f"No {provider} connector configured — add a token first")

    try:
        if provider == "github":
            branches = await _list_github_branches(repo, connector["token"])
        else:
            token = await _ensure_fresh_gitlab_token(account["account_id"], connector, db)
            branches = await _list_gitlab_branches(repo, token)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"{provider} error: {e.response.text[:300]}")

    return {"provider": provider, "repo": repo, "branches": branches}


async def _list_github_branches(repo: str, token: str) -> list[str]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"https://api.github.com/repos/{repo}/branches",
            params={"per_page": 100},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
    return [b["name"] for b in data]


async def _list_gitlab_branches(repo: str, token: str) -> list[str]:
    project_enc = repo.replace("/", "%2F")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"https://gitlab.com/api/v4/projects/{project_enc}/repository/branches",
            params={"per_page": 100},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
    return [b["name"] for b in data]


@router.get("/connectors/{provider}/tree")
async def list_tree(provider: str, repo: str, path: str = "", ref: str = "", account: dict = Depends(require_account)):
    """Lists one directory's contents (files and subfolders) in a repo, so
    the frontend can offer a folder browser instead of asking the user to
    type a file path from memory."""
    if provider not in _PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}' — must be one of {sorted(_PROVIDERS)}")
    if not repo:
        raise HTTPException(400, "repo required")

    db = await get_store()
    connector = await db.get_connector(account["account_id"], provider)
    if not connector:
        raise HTTPException(400, f"No {provider} connector configured — add a token first")

    try:
        if provider == "github":
            entries = await _list_github_tree(repo, path, ref, connector["token"])
        else:
            token = await _ensure_fresh_gitlab_token(account["account_id"], connector, db)
            entries = await _list_gitlab_tree(repo, path, ref, token)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"{provider} error: {e.response.text[:300]}")

    return {"provider": provider, "repo": repo, "path": path, "entries": entries}


def _sorted_entries(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: (e["type"] != "dir", e["name"].lower()))


async def _list_github_tree(repo: str, path: str, ref: str, token: str) -> list[dict]:
    url = f"https://api.github.com/repos/{repo}/contents/{path}" if path else f"https://api.github.com/repos/{repo}/contents"
    params = {"ref": ref} if ref else {}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, list):
        raise HTTPException(400, f"'{path}' is a file, not a directory")
    return _sorted_entries([
        {"name": d["name"], "path": d["path"], "type": "dir" if d["type"] == "dir" else "file"} for d in data
    ])


async def _list_gitlab_tree(repo: str, path: str, ref: str, token: str) -> list[dict]:
    project_enc = repo.replace("/", "%2F")
    headers = {"Authorization": f"Bearer {token}"}
    params = {"per_page": 100}
    if path:
        params["path"] = path
    if ref:
        params["ref"] = ref
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"https://gitlab.com/api/v4/projects/{project_enc}/repository/tree",
            params=params, headers=headers,
        )
        r.raise_for_status()
        data = r.json()
    return _sorted_entries([
        {"name": d["name"], "path": d["path"], "type": "dir" if d["type"] == "tree" else "file"} for d in data
    ])


@router.post("/connectors/{provider}/fetch")
async def fetch_file(provider: str, request: Request, account: dict = Depends(require_account)):
    """Fetch one file's raw content from a GitHub or GitLab repo, for attaching to a chat message."""
    if provider not in _PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}' — must be one of {sorted(_PROVIDERS)}")

    body = await request.json()
    repo = (body.get("repo") or "").strip()
    path = (body.get("path") or "").strip()
    ref = (body.get("ref") or "").strip()
    if not repo or not path:
        raise HTTPException(400, "repo and path required")

    db = await get_store()
    connector = await db.get_connector(account["account_id"], provider)
    if not connector:
        raise HTTPException(400, f"No {provider} connector configured — add a token first")

    try:
        if provider == "github":
            content = await _fetch_github(repo, path, ref, connector["token"])
        else:
            token = await _ensure_fresh_gitlab_token(account["account_id"], connector, db)
            content = await _fetch_gitlab(repo, path, ref, token)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"{provider} error: {e.response.text[:300]}")

    truncated = len(content) > _MAX_FETCH_CHARS
    if truncated:
        content = content[:_MAX_FETCH_CHARS]

    return {"provider": provider, "repo": repo, "path": path, "content": content, "truncated": truncated}


async def _fetch_github(repo: str, path: str, ref: str, token: str) -> str:
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    params = {"ref": ref} if ref else {}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()
    if isinstance(data, list):
        raise HTTPException(400, f"'{path}' is a directory, not a file")
    return base64.b64decode(data["content"]).decode("utf-8", errors="replace")


async def _fetch_gitlab(repo: str, path: str, ref: str, token: str) -> str:
    project_enc = repo.replace("/", "%2F")
    path_enc = path.replace("/", "%2F")
    url = f"https://gitlab.com/api/v4/projects/{project_enc}/repository/files/{path_enc}/raw"
    params = {"ref": ref or "HEAD"}
    # Bearer works for both a manually pasted PAT and an OAuth-issued token —
    # GitLab's PRIVATE-TOKEN header only accepts PATs, not OAuth tokens.
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params=params, headers=headers)
        r.raise_for_status()
        return r.text


_MAX_REPO_CHARS = 50_000  # whole-repo attach budget — bigger than one file, still bounded
_MAX_REPO_FILES = 40
_SKIP_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".pdf", ".zip", ".gz",
    ".tar", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".mov", ".exe", ".dll",
    ".so", ".dylib", ".class", ".jar", ".lock", ".bin", ".wasm", ".db", ".sqlite",
}
_SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "venv", "vendor", ".next"}


def _should_skip_in_repo(path: str) -> bool:
    parts = path.split("/")
    if any(p in _SKIP_DIRS for p in parts[:-1]):
        return True
    name = parts[-1]
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in _SKIP_EXT


@router.post("/connectors/{provider}/fetch-repo")
async def fetch_repo(provider: str, request: Request, account: dict = Depends(require_account)):
    """Attaches a whole repo at once (tree overview + as many text files as
    fit the budget) instead of one file at a time — mirrors "add this repo"
    in other tools' repo pickers, for when the user wants the model to see
    the codebase rather than a single named file."""
    if provider not in _PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}' — must be one of {sorted(_PROVIDERS)}")

    body = await request.json()
    repo = (body.get("repo") or "").strip()
    ref = (body.get("ref") or "").strip()
    if not repo:
        raise HTTPException(400, "repo required")

    db = await get_store()
    connector = await db.get_connector(account["account_id"], provider)
    if not connector:
        raise HTTPException(400, f"No {provider} connector configured — add a token first")

    try:
        if provider == "github":
            content, truncated, file_count = await _fetch_github_repo(repo, ref, connector["token"])
        else:
            token = await _ensure_fresh_gitlab_token(account["account_id"], connector, db)
            content, truncated, file_count = await _fetch_gitlab_repo(repo, ref, token)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"{provider} error: {e.response.text[:300]}")

    return {"provider": provider, "repo": repo, "content": content, "truncated": truncated, "file_count": file_count}


def _bundle_repo_files(repo: str, all_paths: list[str], blobs: list[dict]) -> tuple[list[str], int]:
    """Shared budgeting: a tree overview block first, then as many file
    blocks as fit `_MAX_REPO_CHARS`/`_MAX_REPO_FILES` — `blobs` entries
    already have their `content` fetched by the caller (provider-specific,
    since GitHub and GitLab fetch blob content differently)."""
    parts = [f'<repo_tree repo="{repo}">\n' + "\n".join(all_paths) + "\n</repo_tree>"]
    total = len(parts[0])
    file_count = 0
    for b in blobs:
        if file_count >= _MAX_REPO_FILES or total >= _MAX_REPO_CHARS:
            break
        content = b["content"]
        remaining = _MAX_REPO_CHARS - total
        if len(content) > remaining:
            content = content[:remaining]
        block = f'<file path="{b["path"]}">\n{content}\n</file>'
        parts.append(block)
        total += len(block)
        file_count += 1
    return parts, file_count


async def _fetch_github_repo(repo: str, ref: str, token: str) -> tuple[str, bool, int]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"https://api.github.com/repos/{repo}/git/trees/{ref or 'HEAD'}",
            params={"recursive": "1"}, headers=headers,
        )
        r.raise_for_status()
        tree = r.json()
        all_entries = tree.get("tree", [])
        candidates = [t for t in all_entries if t["type"] == "blob" and not _should_skip_in_repo(t["path"])]

        blobs = []
        total_so_far = 0
        for t in candidates:
            if len(blobs) >= _MAX_REPO_FILES or total_so_far >= _MAX_REPO_CHARS:
                break
            br = await client.get(f"https://api.github.com/repos/{repo}/git/blobs/{t['sha']}", headers=headers)
            if br.status_code != 200:
                continue
            bdata = br.json()
            try:
                content = base64.b64decode(bdata["content"]).decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                continue  # binary file that slipped past the extension filter
            blobs.append({"path": t["path"], "content": content})
            total_so_far += len(content)

    parts, file_count = _bundle_repo_files(repo, [t["path"] for t in all_entries], blobs)
    truncated = bool(tree.get("truncated")) or file_count < len(candidates) or sum(len(p) for p in parts) >= _MAX_REPO_CHARS
    return "\n\n".join(parts), truncated, file_count


async def _fetch_gitlab_repo(repo: str, ref: str, token: str) -> tuple[str, bool, int]:
    project_enc = repo.replace("/", "%2F")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        params = {"recursive": "true", "per_page": 100}
        if ref:
            params["ref"] = ref
        all_entries = []
        page_truncated = False
        for page in range(1, 6):  # caps pagination — a huge tree isn't worth crawling in full for a chat attach
            r = await client.get(
                f"https://gitlab.com/api/v4/projects/{project_enc}/repository/tree",
                params={**params, "page": page}, headers=headers,
            )
            r.raise_for_status()
            batch = r.json()
            all_entries.extend(batch)
            if len(batch) < 100:
                break
            if page == 5:
                page_truncated = True

        candidates = [e for e in all_entries if e["type"] == "blob" and not _should_skip_in_repo(e["path"])]

        blobs = []
        total_so_far = 0
        for e in candidates:
            if len(blobs) >= _MAX_REPO_FILES or total_so_far >= _MAX_REPO_CHARS:
                break
            fr = await client.get(f"https://gitlab.com/api/v4/projects/{project_enc}/repository/blobs/{e['id']}/raw", headers=headers)
            if fr.status_code != 200:
                continue
            try:
                content = fr.content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            blobs.append({"path": e["path"], "content": content})
            total_so_far += len(content)

    parts, file_count = _bundle_repo_files(repo, [e["path"] for e in all_entries], blobs)
    truncated = page_truncated or file_count < len(candidates) or sum(len(p) for p in parts) >= _MAX_REPO_CHARS
    return "\n\n".join(parts), truncated, file_count


async def _ensure_fresh_gitlab_token(account_id: str, connector: dict, db) -> str:
    """OAuth-issued GitLab access tokens expire in ~2h; a manually pasted PAT
    has no expires_at/refresh_token and is returned as-is. Refreshes and
    persists the new token/expiry when it's within 60s of expiring, so a
    long chat session doesn't start failing fetches mid-way through."""
    expires_at = connector.get("expires_at")
    refresh_token = connector.get("refresh_token")
    if not expires_at or not refresh_token or expires_at > time.time() + 60:
        return connector["token"]

    cfg = _OAUTH["gitlab"]
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(cfg["token_url"], data={
            "client_id": cfg["client_id"](),
            "client_secret": cfg["client_secret"](),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        r.raise_for_status()
        data = r.json()

    new_token = data["access_token"]
    new_refresh = data.get("refresh_token", refresh_token)
    new_expires_at = int(time.time()) + int(data["expires_in"]) if data.get("expires_in") else None
    await db.upsert_connector(account_id, "gitlab", new_token, new_refresh, new_expires_at)
    return new_token
