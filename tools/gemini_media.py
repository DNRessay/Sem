import base64
import io
import wave

import httpx

from config import settings

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
ASPECT_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "4:5", "5:4", "3:2", "2:3", "21:9")
VOICES = ("Kore", "Puck", "Charon", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr")
_TTS_RATE = 24000  # Gemini TTS returns raw 16-bit mono PCM at 24 kHz


def _inline_parts(data: dict) -> list[dict]:
    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    return [p["inlineData"] for p in parts if p.get("inlineData")]


async def _generate(model: str, body: dict, timeout: float) -> dict:
    if not settings.GEMINI_API_KEY:
        return {"ok": False, "error": "GEMINI_API_KEY not set — add a Google AI Studio key"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{_BASE}/{model}:generateContent", json=body,
                                  headers={"x-goog-api-key": settings.GEMINI_API_KEY})
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"Gemini unreachable: {e}"}
    if r.status_code == 429:
        return {"ok": False, "error": "Gemini free-tier limit reached — try again later", "rate_limited": True}
    if r.status_code != 200:
        return {"ok": False, "error": f"Gemini error {r.status_code}: {r.text[:300]}"}
    return {"ok": True, "data": r.json()}


async def generate_image(prompt: str, aspect_ratio: str = "1:1") -> dict:
    """Nano Banana (Gemini image model). Returns {ok, mime, base64, text}."""
    if aspect_ratio not in ASPECT_RATIOS:
        aspect_ratio = "1:1"
    result = await _generate(settings.GEMINI_IMAGE_MODEL, {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": aspect_ratio}},
    }, timeout=120)
    if not result["ok"]:
        return result
    images = _inline_parts(result["data"])
    if not images:
        return {"ok": False, "error": "Gemini returned no image (the prompt may have been blocked) — try rewording it"}
    return {"ok": True, "mime": images[0].get("mimeType", "image/png"), "base64": images[0]["data"]}


def _pcm_to_wav(pcm: bytes, rate: int = _TTS_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


async def speak(text: str, voice: str = "Kore") -> dict:
    """Gemini TTS. Returns {ok, mime: "audio/wav", base64}."""
    if voice not in VOICES:
        voice = "Kore"
    result = await _generate(settings.GEMINI_TTS_MODEL, {
        "contents": [{"parts": [{"text": text[:5000]}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }, timeout=90)
    if not result["ok"]:
        return result
    audio = _inline_parts(result["data"])
    if not audio:
        return {"ok": False, "error": "Gemini returned no audio"}
    raw = base64.b64decode(audio[0]["data"])
    mime = audio[0].get("mimeType", "")
    if "wav" not in mime:
        rate = _TTS_RATE
        if "rate=" in mime:
            try:
                rate = int(mime.split("rate=")[1].split(";")[0])
            except ValueError:
                pass
        raw = _pcm_to_wav(raw, rate)
    return {"ok": True, "mime": "audio/wav", "base64": base64.b64encode(raw).decode()}
