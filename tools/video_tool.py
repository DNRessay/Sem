import httpx

from config import settings


async def video_call(action: str, timeout: float = 60, **kwargs) -> dict:
    """Client for modal_app/video.py: submit / status / budget. "status" on a finished job sends the video back,
    which can take minutes for a long one, hence the longer timeout callers pass for it."""
    if not settings.MODAL_VIDEO_URL:
        return {"ok": False, "error": "Video isn't set up — deploy modal_app/video.py and set MODAL_VIDEO_URL"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(settings.MODAL_VIDEO_URL, json={"action": action, **kwargs},
                                  headers={"Authorization": f"Bearer {settings.MODAL_VIDEO_SECRET}"})
            return r.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "error": f"video service unreachable: {e}"}
