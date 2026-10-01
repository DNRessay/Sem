"""Images for Design, Co-work and MCP: Gemini (Nano Banana) first, then
FLUX.1-schnell on Modal (open-source) when Gemini is out of free quota or
not set up. Same {ok, mime, base64} shape either way, plus `engine`."""
import asyncio
import time

from config import settings
from tools import gemini_media
from tools.video_tool import video_call

_WAIT_SECONDS = 240  # covers a FLUX cold start; warm images take seconds


async def _flux(prompt: str, aspect_ratio: str) -> dict:
    job = await video_call("image", prompt=prompt, aspect_ratio=aspect_ratio)
    if not job.get("ok"):
        return {"ok": False, "error": job.get("error") or "open-source image service failed"}
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        status = await video_call("status", job_id=job["job_id"])
        if status.get("status") == "done":
            return {"ok": True, "mime": status["mime"], "base64": status["base64"], "engine": "flux"}
        if not status.get("ok"):
            return {"ok": False, "error": status.get("error") or "open-source image failed"}
    return {"ok": False, "error": "open-source image took too long — tap New image to try again"}


async def generate_image(prompt: str, aspect_ratio: str = "1:1", references: list[dict] | None = None) -> dict:
    result = await gemini_media.generate_image(prompt, aspect_ratio, references=references)
    if result["ok"]:
        return {**result, "engine": "gemini"}
    blocked = "no image" in result["error"]  # Gemini refused the prompt itself — FLUX can still try
    if not settings.MODAL_VIDEO_URL or not (result.get("rate_limited") or blocked
                                            or "not set" in result["error"] or "unreachable" in result["error"]):
        return result
    flux = await _flux(prompt, aspect_ratio)
    if flux["ok"]:
        return flux
    return {**result, "error": f"{result['error']}; open-source fallback: {flux['error']}"}
