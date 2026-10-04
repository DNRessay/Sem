"""One way to make speech: Kokoro on Modal first (fast, no rate limit), Gemini TTS when Kokoro isn't reachable."""
from tools import gemini_media, voice_client


async def speak(text: str, voice: str = "Kore") -> dict:
    """{ok, mime: "audio/wav", base64, engine} or {ok: False, error, rate_limited?}."""
    result = await voice_client.speak(text, voice)
    if result.get("ok") and result.get("base64"):
        return {"ok": True, "mime": result.get("mime") or "audio/wav", "base64": result["base64"], "engine": "kokoro"}
    fallback = await gemini_media.speak(text, voice)
    return {**fallback, "engine": "gemini"} if fallback.get("ok") else fallback
