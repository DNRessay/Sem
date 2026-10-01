"""This month's Modal GPU spend for video ads and FLUX images, as tracked by
modal_app/video.py (Modal's own billing API is Team/Enterprise only), next
to the Starter plan's free monthly credit. Cached for 10 minutes."""
import json

from cache import ddb_backend
from config import settings
from tools.aws_cost import zar_rate
from tools.video_tool import video_call

_TTL = 600


async def month_to_date(account_id: str = "owner") -> dict:
    if not settings.MODAL_VIDEO_URL:
        return {"ok": False, "error": "Modal video/image app isn't connected (MODAL_VIDEO_URL)"}
    cached = ddb_backend.get("modal_cost", "mtd")
    if cached:
        return json.loads(cached)
    budget = await video_call("budget")
    if not budget.get("ok"):
        return {"ok": False, "error": budget.get("error") or "Modal didn't answer"}
    usd, free = float(budget["used_usd"]), settings.MODAL_FREE_CREDIT_USD
    rate, source = await zar_rate(account_id)
    result = {"ok": True, "usd": round(usd, 2), "cap_usd": budget["cap_usd"], "free_usd": free,
              "free_left_usd": round(max(free - usd, 0.0), 2), "tracked": "video + images",
              "zar": round(usd * rate, 2) if rate else None, "rate": rate, "rate_source": source}
    ddb_backend.set("modal_cost", "mtd", json.dumps(result), ttl=_TTL)
    return result
