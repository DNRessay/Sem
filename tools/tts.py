"""One way to make speech: Kokoro on Modal first (fast, no rate limit), Gemini TTS when Kokoro isn't reachable.
Each call logs which engine spoke and how long it took (CloudWatch: "tts kokoro 0.84s 63 chars")."""
import logging
import time

from tools import gemini_media, voice_client

log = logging.getLogger("semblance.tts")


async def speak(text: str, voice: str = "Kore") -> dict:
    """{ok, mime: "audio/wav", base64, engine} or {ok: False, error, rate_limited?}."""
    started = time.monotonic()
    result = await voice_client.speak(text, voice)
    if result.get("ok") and result.get("base64"):
        log.warning("tts kokoro %.2fs %d chars", time.monotonic() - started, len(text))
        return {"ok": True, "mime": result.get("mime") or "audio/wav", "base64": result["base64"], "engine": "kokoro"}
    fallback = await gemini_media.speak(text, voice)
    log.warning("tts gemini %.2fs %d chars (kokoro: %s)%s", time.monotonic() - started, len(text),
                result.get("error", "no audio"), "" if fallback.get("ok") else f" — gemini failed: {fallback.get('error')}")
    return {**fallback, "engine": "gemini"} if fallback.get("ok") else fallback
