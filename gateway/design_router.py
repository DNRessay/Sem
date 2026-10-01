import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from gateway.auth import require_account
from pipeline.ad_studio import PLACEMENTS, write_variants
from pipeline.site_brief import learn_site
from tools import gemini_media
from tools.video_tool import video_call

router = APIRouter(prefix="/design")


@router.get("/options")
async def options(_account: dict = Depends(require_account)):
    return {"placements": [{"id": k, "label": v[0], "aspect_ratio": v[1]} for k, v in PLACEMENTS.items()]}


@router.post("/brief")
async def brief_from_site(request: Request, _account: dict = Depends(require_account)):
    """Reads the business's own website and writes the ad brief from it."""
    body = await request.json()
    result = await learn_site(body.get("url") or "", body.get("model") or "auto")
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result


@router.post("/ads")
async def ads(request: Request, _account: dict = Depends(require_account)):
    """Ad studio: copy for every variant first, then each image as Nano Banana
    finishes it — so the copy is readable while images are still coming."""
    body = await request.json()
    brief, campaign = (body.get("brief") or "").strip(), (body.get("campaign") or "").strip()
    if not brief or not campaign:
        raise HTTPException(400, "brief and campaign required")

    async def stream():
        written = await write_variants(brief, campaign, body.get("placements") or [], body.get("count") or 2,
                                       body.get("model") or "auto")
        if not written["ok"]:
            yield f"data: {json.dumps({'type': 'error', 'text': written['error']})}\n\n"
            yield "data: [DONE]\n\n"
            return
        variants = written["variants"]
        yield f"data: {json.dumps({'type': 'variants', 'variants': variants})}\n\n"
        if body.get("images", True):
            for i, v in enumerate(variants):
                img = await gemini_media.generate_image(v["image_prompt"], v["aspect_ratio"])
                if img["ok"]:
                    yield f"data: {json.dumps({'type': 'image', 'index': i, 'mime': img['mime'], 'base64': img['base64']})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'image_error', 'index': i, 'error': img['error']})}\n\n"
                    if img.get("rate_limited"):
                        break
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/image")
async def regenerate_image(request: Request, _account: dict = Depends(require_account)):
    body = await request.json()
    result = await gemini_media.generate_image((body.get("prompt") or "").strip(), body.get("aspect_ratio") or "1:1")
    if not result["ok"]:
        raise HTTPException(429 if result.get("rate_limited") else 400, result["error"])
    return result


@router.post("/video")
async def video_submit(request: Request, _account: dict = Depends(require_account)):
    body = await request.json()
    result = await video_call("submit", prompt=(body.get("prompt") or "").strip(),
                              aspect_ratio=body.get("aspect_ratio") or "9:16", seconds=body.get("seconds") or 5)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "video submit failed")
    return result


@router.get("/video/budget")
async def video_budget(_account: dict = Depends(require_account)):
    return await video_call("budget")


@router.get("/video/{job_id}")
async def video_status(job_id: str, _account: dict = Depends(require_account)):
    result = await video_call("status", job_id=job_id)
    if not result.get("ok") and result.get("status") != "failed":
        raise HTTPException(400, result.get("error") or "status check failed")
    return result
