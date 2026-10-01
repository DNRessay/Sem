from fastapi import APIRouter, Depends, HTTPException, Request

from gateway.auth import require_account
from tools import gemini_media

router = APIRouter(prefix="/media")


@router.post("/image")
async def image(request: Request, _account: dict = Depends(require_account)):
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt required")
    result = await gemini_media.generate_image(prompt, body.get("aspect_ratio") or "1:1")
    if not result["ok"]:
        raise HTTPException(429 if result.get("rate_limited") else 400, result["error"])
    return result


@router.post("/speech")
async def speech(request: Request, _account: dict = Depends(require_account)):
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    result = await gemini_media.speak(text, body.get("voice") or "Kore")
    if not result["ok"]:
        raise HTTPException(429 if result.get("rate_limited") else 400, result["error"])
    return result


@router.get("/options")
async def options(_account: dict = Depends(require_account)):
    return {"aspect_ratios": list(gemini_media.ASPECT_RATIOS), "voices": list(gemini_media.VOICES)}
