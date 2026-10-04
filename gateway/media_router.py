import asyncio
import base64

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from gateway.auth import require_account
from tools import gemini_media, image_gen, media_store, tts, voice_client
from tools.file_reader import _groq_transcribe

router = APIRouter(prefix="/media")
_warming: set = set()


@router.post("/image")
async def image(request: Request, _account: dict = Depends(require_account)):
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt required")
    result = await image_gen.generate_image(prompt, body.get("aspect_ratio") or "1:1")
    if not result["ok"]:
        raise HTTPException(429 if result.get("rate_limited") else 400, result["error"])
    return result


@router.post("/speech")
async def speech(request: Request, _account: dict = Depends(require_account)):
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    result = await tts.speak(text, body.get("voice") or "Kore")
    if not result["ok"]:
        raise HTTPException(429 if result.get("rate_limited") else 400, result["error"])
    return result


@router.post("/transcribe")
async def transcribe(request: Request, _account: dict = Depends(require_account)):
    """Speech to text for browsers that can't do it themselves: Whistle on Modal, Groq Whisper as fallback.
    Body: {audio: base64 16 kHz mono WAV (up to ~30 s), keywords?: [names to listen for]}."""
    body = await request.json()
    audio = body.get("audio") or ""
    if not audio:
        raise HTTPException(400, "audio required")
    result = await voice_client.transcribe(audio, body.get("keywords") or [])
    if result.get("ok"):
        return {"ok": True, "text": (result.get("text") or "").strip(), "engine": "whistle", "took": result.get("took")}
    try:
        text = await _groq_transcribe(base64.b64decode(audio), "speech.wav")
    except Exception:
        text = ""
    if not text:
        raise HTTPException(503, result.get("error") or "Couldn't transcribe the audio")
    return {"ok": True, "text": text.strip(), "engine": "groq"}


@router.post("/voice/warm")
async def voice_warm(_account: dict = Depends(require_account)):
    """Voice mode opening: start the Kokoro/Whistle container now so the first reply doesn't wait for it."""
    task = asyncio.create_task(voice_client.warm())
    _warming.add(task)
    task.add_done_callback(_warming.discard)
    await asyncio.sleep(0)
    return {"ok": True, "configured": bool(voice_client.url())}


@router.get("/options")
async def options(_account: dict = Depends(require_account)):
    return {"aspect_ratios": list(gemini_media.ASPECT_RATIOS), "voices": list(gemini_media.VOICES)}


@router.get("/file/{key:path}")
async def media_file(key: str, exp: int = 0, sig: str = ""):
    """A saved ad image or video. The link itself is the permission (signed, 7 days, matching the bucket's
    lifecycle), so <img>/<video> can load it without a login header."""
    if not media_store.enabled() or not media_store.verify(key, exp, sig):
        raise HTTPException(404, "This file has expired or the link is wrong")
    url = await asyncio.to_thread(media_store.presigned, key)
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "private, max-age=300"})
