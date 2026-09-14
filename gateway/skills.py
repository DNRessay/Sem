import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from gateway.auth import require_account
from storage.neon_store import get_store

router = APIRouter()


@router.get("/skills")
async def list_skills(_account: dict = Depends(require_account)):
    db = await get_store()
    return {"skills": await db.list_skills()}


@router.post("/skills")
async def save_skill(request: Request, _account: dict = Depends(require_account)):
    body = await request.json()
    name = (body.get("name") or "").strip()
    content = (body.get("content") or "").strip()
    if not name or not content:
        raise HTTPException(400, "name and content required")

    triggers = body.get("triggers") or []
    if isinstance(triggers, str):
        triggers = [t.strip() for t in triggers.split(",") if t.strip()]
    triggers = [t.lower() for t in triggers]

    skill_id = body.get("id") or f"skill_{uuid.uuid4().hex[:8]}_{int(time.time())}"
    enabled = body.get("enabled", True)

    db = await get_store()
    await db.upsert_skill(skill_id, name, triggers, content, enabled)
    return {"id": skill_id, "name": name, "triggers": triggers, "enabled": enabled}


@router.delete("/skills/{skill_id}")
async def remove_skill(skill_id: str, _account: dict = Depends(require_account)):
    db = await get_store()
    await db.delete_skill(skill_id)
    return {"deleted": skill_id}
