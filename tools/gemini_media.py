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


MAX_REFERENCES = 4


def clean_references(refs) -> list[dict]:
    """Inspiration images from the browser: [{mime, base64}], images only, capped."""
    out = []
    for r in refs or []:
        if isinstance(r, dict) and str(r.get("mime", "")).startswith("image/") and r.get("base64"):
            out.append({"mime": r["mime"], "base64": r["base64"]})
    return out[:MAX_REFERENCES]


def _ref_parts(refs: list[dict]) -> list[dict]:
    return [{"inlineData": {"mimeType": r["mime"], "data": r["base64"]}} for r in refs]


async def generate_image(prompt: str, aspect_ratio: str = "1:1", references: list[dict] | None = None) -> dict:
    """Nano Banana (Gemini image model). Returns {ok, mime, base64}. With
    `references`, the images are sent alongside the prompt as style inspiration."""
    if aspect_ratio not in ASPECT_RATIOS:
        aspect_ratio = "1:1"
    refs = clean_references(references)
    text = prompt
    if refs:
        text = ("Use the attached image(s) as style inspiration — match their look, colours, composition and mood, "
                "but make a new, original image (don't copy logos or text from them).\n\n" + prompt)
    result = await _generate(settings.GEMINI_IMAGE_MODEL, {
        "contents": [{"parts": _ref_parts(refs) + [{"text": text}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": aspect_ratio}},
    }, timeout=120)
    if not result["ok"]:
        return result
    images = _inline_parts(result["data"])
    if not images:
        return {"ok": False, "error": "Gemini returned no image (the prompt may have been blocked) — try rewording it"}
    return {"ok": True, "mime": images[0].get("mimeType", "image/png"), "base64": images[0]["data"]}


async def describe_style(references: list[dict]) -> dict:
    """What the inspiration images look like, in words the copywriter and the
    image prompts can use. Returns {ok, text}."""
    refs = clean_references(references)
    if not refs:
        return {"ok": False, "error": "no reference images"}
    result = await _generate(settings.GEMINI_MODEL, {"contents": [{"parts": _ref_parts(refs) + [{"text": (
        "These are inspiration images (some may be frames from a video ad) for a small business's ads. In at most 8 "
        "short lines describe the visual style to reuse: colour palette (with hex guesses), typography, layout and "
        "composition, photography/illustration style, lighting, mood, and any recurring motifs. Style only — no "
        "brand names.")}]}]}, timeout=60)
    if not result["ok"]:
        return result
    parts = (((result["data"].get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts).strip()
    return {"ok": bool(text), "text": text, **({} if text else {"error": "Gemini returned no description"})}


async def describe_design(references: list[dict]) -> dict:
    """A UI design (e.g. Figma frames) as build notes a developer — or a text-only model — can rebuild from."""
    refs = clean_references(references)
    if not refs:
        return {"ok": False, "error": "no design images"}
    result = await _generate(settings.GEMINI_MODEL, {"contents": [{"parts": _ref_parts(refs) + [{"text": (
        "These are screens from a website/app design. Write build notes so a developer can rebuild them faithfully: "
        "for each screen, the sections from top to bottom with their layout (columns, alignment, spacing), every "
        "visible heading/button/label text, colours as hex, fonts (family guess, weights, sizes), corner radii, "
        "shadows, icons and image placeholders. Be concrete and concise; no commentary.")}]}]}, timeout=90)
    if not result["ok"]:
        return result
    parts = (((result["data"].get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts).strip()
    return {"ok": bool(text), "text": text, **({} if text else {"error": "Gemini returned no description"})}


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
