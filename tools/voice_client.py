"""Client for modal_app/voice.py: Kokoro TTS and Whistle speech-to-text on Modal CPU. Same Modal workspace and
secret as the video app, so the URL is derived from MODAL_VIDEO_URL unless VOICE_URL says otherwise."""
import httpx

from config import settings


def url() -> str:
    if settings.VOICE_URL:
        return "" if settings.VOICE_URL == "off" else settings.VOICE_URL
    video = settings.MODAL_VIDEO_URL or ""
    return video.replace("semblance-video-api", "semblance-voice-api") if "semblance-video-api" in video else ""


async def _call(body: dict, timeout: float) -> dict:
    endpoint = url()
    if not endpoint:
        return {"ok": False, "error": "voice service not set up"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(endpoint, json=body, headers={"Authorization": f"Bearer {settings.MODAL_VIDEO_SECRET}"})
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "error": f"voice service unreachable: {type(e).__name__}"}


async def speak(text: str, voice: str = "Kore", timeout: float = 12) -> dict:
    return await _call({"action": "speak", "text": text, "voice": voice}, timeout)


async def transcribe(audio_b64: str, keywords: list[str] | None = None, timeout: float = 20) -> dict:
    return await _call({"action": "transcribe", "audio": audio_b64, "keywords": keywords or []}, timeout)


async def warm() -> dict:
    """Starts the container (Kokoro loads in ~10-20 s) when voice mode opens, so the first reply is quick."""
    return await _call({"action": "warm"}, 60)
