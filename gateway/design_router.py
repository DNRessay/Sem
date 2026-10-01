import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from gateway.auth import require_account
from pipeline.activity import log, session_for
from pipeline.ad_studio import PLACEMENTS, write_variants
from pipeline.site_brief import learn_site
from storage.neon_store import get_store
from tools import gemini_media
from tools.mcp_client import MCPClient
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

    refs = gemini_media.clean_references(body.get("references"))
    session = session_for("design", body)

    async def stream():
        await log(session, "design", f"ok:create ads · {len(refs)} inspiration image(s) · {campaign[:100]}")
        style = ""
        if refs:
            yield f"data: {json.dumps({'type': 'status', 'text': 'Studying your inspiration…'})}\n\n"
            described = await gemini_media.describe_style(refs)
            await log(session, "gemini", f"{'ok' if described['ok'] else 'blocked'}:style read — "
                                         f"{(described.get('text') or described.get('error') or '')[:150]}")
            if described["ok"]:
                style = described["text"]
                yield f"data: {json.dumps({'type': 'style', 'text': style})}\n\n"
        written = await write_variants(brief, campaign, body.get("placements") or [], body.get("count") or 2,
                                       body.get("model") or "auto", style=style)
        await log(session, "design", f"{'ok' if written['ok'] else 'blocked'}:ad copy — "
                                     f"{len(written.get('variants') or [])} variant(s){'' if written['ok'] else ': ' + written['error']}")
        if not written["ok"]:
            yield f"data: {json.dumps({'type': 'error', 'text': written['error']})}\n\n"
            yield "data: [DONE]\n\n"
            return
        variants = written["variants"]
        yield f"data: {json.dumps({'type': 'variants', 'variants': variants})}\n\n"
        if body.get("images", True):
            for i, v in enumerate(variants):
                img = await gemini_media.generate_image(v["image_prompt"], v["aspect_ratio"], references=refs)
                await log(session, "gemini", f"{'ok' if img['ok'] else 'blocked'}:image {i + 1} — "
                                             f"{'made' if img['ok'] else img['error']}")
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
    result = await gemini_media.generate_image((body.get("prompt") or "").strip(), body.get("aspect_ratio") or "1:1",
                                               references=body.get("references"))
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


# ── Vicinic (DNRessay/Digital) over MCP: pick a customer site, use its brief ──

VICINIC_SERVER = "vicinic"


async def _vicinic(account_id: str) -> dict | None:
    db = await get_store()
    return next((s for s in await db.list_mcp_servers(account_id) if s["name"] == VICINIC_SERVER), None)


async def _vicinic_call(server: dict, tool: str, args: dict | None = None):
    try:
        result = await MCPClient(server["url"], server.get("auth", ""), timeout=40).call_tool(tool, args or {})
    except Exception as e:
        raise HTTPException(502, f"Vicinic didn't answer: {str(e)[:300]}")
    if not result["ok"]:
        raise HTTPException(400, result["text"][:300] or "Vicinic refused that")
    try:
        return json.loads(result["text"])
    except ValueError:
        return result["text"]


@router.post("/vicinic/connect")
async def vicinic_connect(request: Request, account: dict = Depends(require_account)):
    """Saves Vicinic as the MCP server "vicinic" — also gives Co-work and Code its blog tools."""
    body = await request.json()
    url, key = (body.get("url") or "").strip().rstrip("/"), (body.get("key") or "").strip()
    if not url.startswith("https://") or not key:
        raise HTTPException(400, "Paste Vicinic's https:// backend address and a key from Vicinic Admin → Connect apps")
    if not url.endswith("/mcp"):
        url += "/mcp"
    try:
        tools = await MCPClient(url, key, timeout=30).list_tools(use_cache=False)
    except Exception as e:
        raise HTTPException(400, f"Couldn't connect to Vicinic: {str(e)[:300]}")
    db = await get_store()
    await db.upsert_mcp_server(account["account_id"], VICINIC_SERVER, url, key, False)
    return {"connected": True, "tools": [t.get("name") for t in tools]}


@router.get("/vicinic/sites")
async def vicinic_sites(account: dict = Depends(require_account)):
    server = await _vicinic(account["account_id"])
    if not server:
        return {"connected": False, "sites": []}
    return {"connected": True, "sites": await _vicinic_call(server, "sites")}


@router.get("/vicinic/brief/{slug}")
async def vicinic_brief(slug: str, account: dict = Depends(require_account)):
    server = await _vicinic(account["account_id"])
    if not server:
        raise HTTPException(400, "Connect Vicinic first")
    return await _vicinic_call(server, "site_brief", {"slug": slug})
