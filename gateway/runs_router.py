import json
import time

from fastapi import APIRouter, Depends, HTTPException

from gateway.auth import require_account
from storage.neon_store import get_store

router = APIRouter(prefix="/runs")

# Lambda stops a request after 15 minutes; a run with no news for longer than that is gone.
LOST_AFTER_SECONDS = 16 * 60


@router.get("/{run_id}")
async def events(run_id: str, after: int = 0, account: dict = Depends(require_account)):
    """What a run emitted after `after` (the browser's count of events it already has)."""
    db = await get_store()
    run = await db.get_run(run_id, account["account_id"], max(after, 0))
    if not run:
        raise HTTPException(404, "Unknown run")
    status = run["status"]
    if status == "running" and time.time() - run["updated_at"] > LOST_AFTER_SECONDS:
        status = "lost"
    out = []
    for e in run["events"]:
        try:
            out.append({"seq": e["seq"], "event": json.loads(e["data"])})
        except ValueError:
            continue
    return {"status": status, "events": out}


@router.post("/{run_id}/cancel")
async def cancel(run_id: str, account: dict = Depends(require_account)):
    db = await get_store()
    if not await db.set_run_status(run_id, "cancelled", account["account_id"]):
        raise HTTPException(404, "Unknown run")
    return {"cancelled": True}
