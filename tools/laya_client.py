"""Client for modal_app/laya.py. Always answers fast: anything slower than TIMEOUT (a cold container,
an outage) returns None and the caller falls back to its keyword rules — the reply is never held up."""
import hashlib
import json
import time

import httpx

from config import settings

TIMEOUT = 1.5
_cache: dict[str, tuple[float, dict]] = {}


def url() -> str:
    if settings.LAYA_URL:
        return "" if settings.LAYA_URL == "off" else settings.LAYA_URL
    video = settings.MODAL_VIDEO_URL or ""
    return video.replace("semblance-video-api", "semblance-laya-api") if "semblance-video-api" in video else ""


async def decide(state: str, questions: dict, timeout: float = TIMEOUT) -> dict | None:
    """{question: answer} as Laya returns it ({"noul": p} / {"choice": label, ...}), or None."""
    endpoint = url()
    if not endpoint or not state.strip():
        return None
    key = hashlib.sha1(json.dumps([state, questions], sort_keys=True).encode()).hexdigest()
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(endpoint, json={"state": state, "questions": questions},
                                  headers={"Authorization": f"Bearer {settings.MODAL_VIDEO_SECRET}"})
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not data.get("ok"):
        return None
    _cache[key] = (time.time(), data["answers"])
    if len(_cache) > 500:
        _cache.pop(next(iter(_cache)))
    return data["answers"]
