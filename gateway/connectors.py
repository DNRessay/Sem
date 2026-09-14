import base64

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from gateway.auth import require_account
from storage.neon_store import get_store

router = APIRouter()

_PROVIDERS = {"github", "gitlab"}
_MAX_FETCH_CHARS = 60_000  # keeps one repo file from blowing the model's context on its own


@router.get("/connectors")
async def list_connectors(_account: dict = Depends(require_account)):
    db = await get_store()
    return {"connectors": await db.list_connectors()}


@router.post("/connectors/{provider}")
async def save_connector(provider: str, request: Request, _account: dict = Depends(require_account)):
    if provider not in _PROVIDERS:
        raise HTTPException(400, f"Unknown provider '{provider}' — must be one of {sorted(_PROVIDERS)}")
    body = await request.json()
    token = (body.get("token") or "").strip()
    if not token:
        raise HTTPException(400, "token required")

    db = await get_store()
    await db.upsert_connector(provider, token)
    return {"provider": provider, "connected": True}


@router.delete("/connectors/{provider}")
async def remove_connector(provider: str, _account: dict = Depends(require_account)):
    db = await get_store()
    await db.delete_connector(provider)
    return {"provider": provider, "connected": False}


@router.post("/connectors/{provider}/fetch")
async def fetch_file(provider: str, request: Request, _account: dict = Depends(require_account)):
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
    connector = await db.get_connector(provider)
    if not connector:
        raise HTTPException(400, f"No {provider} connector configured — add a token first")
    token = connector["token"]

    try:
        if provider == "github":
            content = await _fetch_github(repo, path, ref, token)
        else:
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
    headers = {"PRIVATE-TOKEN": token}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, params=params, headers=headers)
        r.raise_for_status()
        return r.text
