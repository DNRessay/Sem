import asyncio
import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from cache import ddb_backend
from config import settings
from gateway.auth import require_account
from pipeline.activity import log, session_for
from pipeline.ad_studio import PLACEMENTS, write_variants
from pipeline.runs import durable
from pipeline.site_brief import learn_site
from pipeline.video_studio import CLIP_USD, FAST_CLIP_USD, FORMATS, estimate, extend_prompt, needs_extending, plan_video
from pipeline.web_studio import LOGO_STYLES, figma_frames, figma_me, logo_prompt, make_page
from storage.neon_store import get_store
from tools import gemini_media, image_gen, media_store, tts
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
        await log(session, "design", f"ok:create images · {len(refs)} inspiration image(s) · {campaign[:100]}")
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
                                       body.get("model") or "auto", style=style, area=body.get("area") or "")
        await log(session, "design", f"{'ok' if written['ok'] else 'blocked'}:post copy — "
                                     f"{len(written.get('variants') or [])} variant(s){'' if written['ok'] else ': ' + written['error']}")
        if not written["ok"]:
            yield f"data: {json.dumps({'type': 'error', 'text': written['error']})}\n\n"
            yield "data: [DONE]\n\n"
            return
        variants = written["variants"]
        yield f"data: {json.dumps({'type': 'variants', 'variants': variants})}\n\n"
        if body.get("images", True):
            for i, v in enumerate(variants):
                img = await image_gen.generate_image(v["image_prompt"], v["aspect_ratio"], references=refs)
                await log(session, "gemini", f"{'ok' if img['ok'] else 'blocked'}:image {i + 1} — "
                                             f"{('made with ' + img.get('engine', 'gemini')) if img['ok'] else img['error']}")
                if img["ok"]:
                    url = await media_store.save(img["base64"], img["mime"], "ads")
                    shown = {"url": url} if url else {"base64": img["base64"]}
                    yield f"data: {json.dumps({'type': 'image', 'index': i, 'mime': img['mime'], **shown})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'image_error', 'index': i, 'error': img['error']})}\n\n"
                    if img.get("rate_limited"):
                        break
        yield "data: [DONE]\n\n"

    return durable(stream(), _account["account_id"], body, "design")


@router.post("/image")
async def regenerate_image(request: Request, _account: dict = Depends(require_account)):
    body = await request.json()
    result = await image_gen.generate_image((body.get("prompt") or "").strip(), body.get("aspect_ratio") or "1:1",
                                               references=body.get("references"))
    if not result["ok"]:
        raise HTTPException(429 if result.get("rate_limited") else 400, result["error"])
    url = await media_store.save(result["base64"], result["mime"], "ads")
    return {"ok": True, "mime": result["mime"], **({"url": url} if url else {"base64": result["base64"]})}


VIDEO_JOBS = "video_jobs"
MAX_VIDEO_JOBS = 30


def _video_jobs(account_id: str) -> list[dict]:
    try:
        return json.loads(ddb_backend.get(VIDEO_JOBS, account_id, fresh=True) or "[]")
    except ValueError:
        return []


def _save_video_job(account_id: str, job: dict):
    jobs = [j for j in _video_jobs(account_id) if j["job_id"] != job["job_id"]]
    ddb_backend.set(VIDEO_JOBS, account_id, json.dumps([job, *jobs][:MAX_VIDEO_JOBS]), ttl=media_store.KEEP_SECONDS)


async def _video_result(job_id: str) -> dict:
    """A render's state. A finished one is copied from Modal to S3 once and remembered, so it plays in the
    app (and stays 7 days) whether or not anyone was watching when it finished."""
    saved = ddb_backend.get("video_url", job_id)
    if saved:
        return json.loads(saved)
    result = await video_call("status", job_id=job_id, timeout=240)
    if result.get("status") == "done" and result.get("base64"):
        url = await media_store.save(result["base64"], result.get("mime") or "video/mp4", "video")
        if url:
            result = {k: v for k, v in result.items() if k != "base64"} | {"url": url}
            ddb_backend.set("video_url", job_id, json.dumps(result), ttl=media_store.KEEP_SECONDS)
    elif result.get("status") == "failed":
        ddb_backend.set("video_url", job_id, json.dumps(result), ttl=3600)  # an hour: Modal may just have hiccuped
    return result


@router.post("/video")
async def video_submit(request: Request, account: dict = Depends(require_account)):
    body = await request.json()
    prompt, aspect = (body.get("prompt") or "").strip(), body.get("aspect_ratio") or "9:16"
    if not prompt:
        raise HTTPException(400, "Describe the clip first")
    prompt = await _extended(prompt, aspect, body.get("brief") or "", body.get("model") or "auto")
    result = await video_call("submit", prompt=prompt, aspect_ratio=aspect, seconds=body.get("seconds") or 5,
                              fast=bool(body.get("fast")))
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "video submit failed")
    _save_video_job(account["account_id"], {"job_id": result["job_id"], "prompt": prompt[:500], "aspect_ratio": aspect,
                                            "chat_id": body.get("chat_id") or "", "created": int(time.time())})
    return result


@router.get("/video/budget")
async def video_budget(_account: dict = Depends(require_account)):
    return await video_call("budget")


@router.get("/videos")
async def video_history(account: dict = Depends(require_account)):
    """Every render from the last 7 days, newest first, with its saved link once finished."""
    jobs = _video_jobs(account["account_id"])
    for j in jobs:
        saved = ddb_backend.get("video_url", j["job_id"])
        j.update(json.loads(saved) if saved else {"status": "rendering"})
    for pid in _project_ids(account["account_id"]):  # finished storyboard videos sit beside the single clips
        p = _project(account["account_id"], pid)
        if p and p.get("url"):
            jobs.append({"job_id": p["id"], "prompt": p["title"], "aspect_ratio": p["aspect_ratio"], "url": p["url"],
                         "status": "done", "created": p["created"], "mime": "video/mp4"})
    jobs.sort(key=lambda j: -int(j.get("created") or 0))
    return {"videos": jobs}


async def _extended(prompt: str, aspect: str, brief: str, model: str) -> str:
    """Short prompts become the dense paragraph Wan renders well (what its demos do). Never blocks a render."""
    if not needs_extending(prompt):
        return prompt
    try:
        return await asyncio.wait_for(extend_prompt(prompt, aspect, brief, model), timeout=20)
    except Exception:
        return prompt


# ── Video studio: short and long videos as storyboards of 5-second scenes ─────
VIDEO_PROJECTS = "video_projects"
MAX_PROJECTS = 20


def _project_ids(account_id: str) -> list[str]:
    try:
        return json.loads(ddb_backend.get(VIDEO_PROJECTS, account_id, fresh=True) or "[]")
    except ValueError:
        return []


def _project(account_id: str, pid: str) -> dict | None:
    raw = ddb_backend.get("video_project", f"{account_id}:{pid}", fresh=True)
    return json.loads(raw) if raw else None


def _save_project(account_id: str, project: dict):
    ddb_backend.set("video_project", f"{account_id}:{project['id']}", json.dumps(project), ttl=media_store.KEEP_SECONDS)
    ids = [project["id"], *[i for i in _project_ids(account_id) if i != project["id"]]][:MAX_PROJECTS]
    ddb_backend.set(VIDEO_PROJECTS, account_id, json.dumps(ids), ttl=media_store.KEEP_SECONDS)
    ref = f"{account_id}:{project['id']}"
    for job in [s.get("job_id") for s in project["scenes"]] + [project.get("stitch_job"), project.get("music_job")]:
        if job:  # lets Modal's "done" callback find the project from a job id
            ddb_backend.set("video_job_owner", job, ref, ttl=media_store.KEEP_SECONDS)
    active = _active()
    if project["status"] in ("done", "failed", "scene_failed"):
        active = [a for a in active if a != ref]
    elif ref not in active:
        active = [*active, ref]
    ddb_backend.set("video_active", "all", json.dumps(active[-50:]), ttl=media_store.KEEP_SECONDS)


def _active() -> list[str]:
    try:
        return json.loads(ddb_backend.get("video_active", "all", fresh=True) or "[]")
    except ValueError:
        return []


def _callback_url() -> str:
    base = (settings.PUBLIC_API_URL or "").rstrip("/")
    return f"{base}/design/video/callback" if base else ""


@router.get("/video/formats")
async def video_formats(_account: dict = Depends(require_account)):
    return {"formats": FORMATS, "clip_seconds": 5, "clip_usd": CLIP_USD, "fast_clip_usd": FAST_CLIP_USD,
            "voices": list(gemini_media.VOICES)}


MUSIC_SECONDS = (10, 20, 30, 47)


@router.post("/music")
async def music(request: Request, account: dict = Depends(require_account)):
    """Music tab: an instrumental track (Stable Audio Open on Modal), uploaded straight to S3 when it's done."""
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Describe the music first")
    if not media_store.enabled():
        raise HTTPException(400, "Music needs media storage (MEDIA_BUCKET)")
    seconds = min(MUSIC_SECONDS, key=lambda s: abs(s - int(body.get("seconds") or 30)))
    key = media_store.new_key("music", "audio/wav")
    upload_url = await asyncio.to_thread(media_store.presign_put, key, "audio/wav")
    made = await video_call("music", prompt=prompt[:500], seconds=seconds, upload_url=upload_url)
    if not made.get("ok"):
        raise HTTPException(400, made.get("error") or "Modal couldn't start the track")
    ddb_backend.set("music_job", made["job_id"], json.dumps({"key": key, "account": account["account_id"]}),
                    ttl=media_store.KEEP_SECONDS)
    return {"ok": True, "job_id": made["job_id"], "seconds": seconds, "status": "rendering"}


@router.get("/music/{job_id}")
async def music_status(job_id: str, account: dict = Depends(require_account)):
    raw = ddb_backend.get("music_job", job_id, fresh=True)
    job = json.loads(raw) if raw else None
    if not job or job.get("account") != account["account_id"]:
        raise HTTPException(404, "This track is gone (kept 7 days)")
    if await asyncio.to_thread(media_store.exists, job["key"]):
        return {"status": "done", "url": media_store.link(job["key"]), "mime": "audio/wav"}
    peek = await video_call("peek", job_id=job_id)
    if peek.get("status") == "failed":
        error = peek.get("error") or ""
        return {"status": "failed", "error": error if error and "render failed" not in error else
                "The music model failed. If it never worked, accept its licence on Hugging Face "
                "(stabilityai/stable-audio-open-1.0) and redeploy Modal."}
    return {"status": "rendering"}


@router.post("/video/plan")
async def video_plan(request: Request, _account: dict = Depends(require_account)):
    """The storyboard: one 5-second scene per clip, sharing one look, with voiceover lines if asked."""
    body = await request.json()
    idea = (body.get("idea") or "").strip()
    if not idea:
        raise HTTPException(400, "Describe the video first")
    plan = await plan_video(body.get("brief") or "", idea, int(body.get("seconds") or 15), body.get("format") or "short",
                            bool(body.get("voiceover")), body.get("model") or "auto")
    if not plan["ok"]:
        raise HTTPException(400, plan["error"])
    return plan


async def _voiceover(lines: list[str], voice: str) -> tuple[str, str]:
    """(audio link, problem). Gemini reads the whole script at once so it sounds like one take."""
    script = " ".join(x.strip() for x in lines if x.strip())
    if not script:
        return "", ""
    try:
        spoken = await asyncio.wait_for(tts.speak(script, voice), timeout=25)
    except asyncio.TimeoutError:
        return "", "The voiceover took too long, so the video will be silent"
    if not spoken["ok"]:
        return "", f"No voiceover ({spoken['error']}), so the video will be silent"
    url = await media_store.save(spoken["base64"], spoken["mime"], "speech")
    return (url or ""), ("" if url else "Couldn't store the voiceover, so the video will be silent")


@router.post("/video/project")
async def video_project(request: Request, account: dict = Depends(require_account)):
    """Renders every scene of a storyboard (one GPU at a time on Modal) and remembers them as one project;
    polling it joins them into one video when the last scene is done."""
    body = await request.json()
    scenes = [s for s in body.get("scenes") or [] if isinstance(s, dict) and str(s.get("prompt") or "").strip()][:12]
    if not scenes:
        raise HTTPException(400, "The storyboard has no scenes")
    aspect = body.get("aspect_ratio") or "9:16"
    budget = await video_call("budget")
    if budget.get("ok"):
        cost = estimate(len(scenes) * 5, bool(body.get("fast")))["usd"]
        left = float(budget["cap_usd"]) - float(budget["used_usd"])
        if cost > left:
            raise HTTPException(400, f"This video needs about ${cost:.2f} of GPU time and ${max(left, 0):.2f} is left this "
                                     "month. Make it shorter, or raise VIDEO_MONTHLY_CAP_USD in the Modal secret.")
    style = str(body.get("style") or "").strip()
    # Scenes the user shortened or typed themselves get extended too (all at once, so it stays quick).
    prompts = await asyncio.gather(*[_extended(str(s["prompt"]).strip(), aspect, body.get("brief") or "", body.get("model") or "auto")
                                     for s in scenes])
    jobs = []
    for s, prompt in zip(scenes, prompts):
        result = await video_call("submit", prompt=prompt, aspect_ratio=aspect, seconds=5, fast=bool(body.get("fast")),
                                  callback=_callback_url())
        if not result.get("ok"):
            if not jobs:
                raise HTTPException(400, result.get("error") or "video submit failed")
            jobs.append({"prompt": prompt, "narration": s.get("narration") or "", "status": "failed",
                         "error": result.get("error") or "submit failed"})
            continue
        jobs.append({"prompt": prompt, "narration": str(s.get("narration") or "")[:300], "job_id": result["job_id"],
                     "status": "rendering"})
    audio, note = ("", "")
    if body.get("voiceover"):
        audio, note = await _voiceover([j["narration"] for j in jobs], body.get("voice") or "Kore")
    music_job, music_prompt = "", str(body.get("music_prompt") or "").strip()[:300]
    if body.get("music"):
        music_prompt = music_prompt or f"instrumental background music for: {style or scenes[0]['prompt']}"[:300]
        made = await video_call("music", prompt=music_prompt, seconds=len(jobs) * 5, callback=_callback_url())
        if made.get("ok"):
            music_job = made["job_id"]
        else:
            note = (note + " " if note else "") + f"No background music ({made.get('error') or 'Modal refused it'})."
    project = {"id": uuid.uuid4().hex[:12], "title": str(body.get("title") or "")[:80] or scenes[0]["prompt"][:60],
               "style": style[:400], "format": body.get("format") or "short", "aspect_ratio": aspect, "scenes": jobs,
               "audio_url": audio, "note": note, "status": "rendering", "fast": bool(body.get("fast")), "chat_id": body.get("chat_id") or "",
               "music_job": music_job, "music_prompt": music_prompt, "music_status": "rendering" if music_job else "",
               "created": int(time.time())}
    _save_project(account["account_id"], project)
    return project


async def _advance(account_id: str, project: dict) -> dict:
    """Checks the scenes; once all are done, starts the join; once that's done, the video is saved to S3."""
    if project["status"] in ("done", "failed"):
        return project
    changed = False
    for s in project["scenes"]:
        if s.get("status") == "rendering" and s.get("job_id"):
            peek = await video_call("peek", job_id=s["job_id"])
            if peek.get("status") in ("done", "failed"):
                s["status"], s["error"] = peek["status"], peek.get("error", "")
                changed = True
    if project.get("music_status") == "rendering":
        peek = await video_call("peek", job_id=project["music_job"])
        if peek.get("status") in ("done", "failed"):
            project["music_status"] = peek["status"]
            if peek["status"] == "failed":
                project["note"] = (project.get("note", "") + " No background music this time.").strip()
            changed = True
    if any(s.get("status") == "failed" for s in project["scenes"]):
        if not any(s.get("status") == "rendering" for s in project["scenes"]):
            project["status"] = "scene_failed"
            changed = True
    elif all(s.get("status") == "done" for s in project["scenes"]):
        latest = _project(account_id, project["id"]) or project
        if latest.get("stitch_job") and not project.get("stitch_job"):
            project = latest  # a callback or another poll already started the join
        # A join normally takes a minute or two. One still "running" after 10 minutes, or started before uploads
        # existed (its result is too big to fetch), is joined again with a direct upload: CPU only, a few cents.
        # The joined video in S3 is the truth: once it's there the video is done, whatever Modal says.
        if project.get("stitch_job") and project.get("final_key") and \
                await asyncio.to_thread(media_store.exists, project["final_key"]):
            result = await video_call("status", job_id=project["stitch_job"], timeout=60)  # small: the video went to S3
            if result.get("voice_error"):
                project["note"] = f"No voiceover: {result['voice_error']}"
            project.update(status="done", url=media_store.link(project["final_key"]), error="",
                           voice=bool(result.get("voice")), music=bool(result.get("music")))
            _save_project(account_id, project)
            return project
        stale = media_store.enabled() and project.get("stitch_job") and (
            not project.get("final_key") or time.time() - project.get("stitch_started", 0) > 660)
        if stale:
            if project.get("rejoins", 0) >= 2:
                project.update(status="failed", error="Joining the scenes kept failing — tap Retry join")
                _save_project(account_id, project)
                return project
            project.update(stitch_job="", rejoins=project.get("rejoins", 0) + 1)
        # The music renders alongside the scenes and is usually done first; wait for it a few minutes at most.
        waiting_for_music = project.get("music_status") == "rendering" and time.time() - project.get("created", 0) < 900
        if not project.get("stitch_job") and waiting_for_music:
            if changed:
                _save_project(account_id, project)
            return project
        if not project.get("stitch_job"):
            # Modal uploads the joined video straight to S3 (a presigned PUT): a long video sent back through the
            # API timed out, so finished videos never arrived.
            key, upload_url = "", ""
            if media_store.enabled():
                key = media_store.new_key("video", "video/mp4")
                upload_url = await asyncio.to_thread(media_store.presign_put, key, "video/mp4")
            audio_url = project.get("audio_url") or ""
            if audio_url and media_store.enabled():
                audio_url = await asyncio.to_thread(media_store.direct, audio_url)
            joined = await video_call("stitch", job_ids=[s["job_id"] for s in project["scenes"]],
                                      audio_url=audio_url, upload_url=upload_url, callback=_callback_url(),
                                      music_job=project["music_job"] if project.get("music_status") == "done" else "")
            if joined.get("ok"):
                project.update(stitch_job=joined["job_id"], status="joining", final_key=key, stitch_started=time.time())
            else:
                project["status"], project["error"] = "failed", joined.get("error") or "couldn't join the scenes"
            changed = True
        else:
            peek = await video_call("peek", job_id=project["stitch_job"])
            if peek.get("stage") and peek["stage"] != project.get("join_stage"):
                project["join_stage"] = peek["stage"]  # e.g. "fetching scene 2 of 3": shows where a join is
                changed = True
            if peek.get("status") == "failed":
                project.update(status="failed", error=peek.get("error") or "couldn't join the scenes")
                changed = True
            elif peek.get("status") == "done":
                result = await video_call("status", job_id=project["stitch_job"], timeout=240)
                if result.get("voice_error"):
                    project["note"] = f"No voiceover: {result['voice_error']}"
                if result.get("uploaded") and project.get("final_key"):
                    project.update(status="done", url=media_store.link(project["final_key"]), voice=bool(result.get("voice")),
                                   music=bool(result.get("music")))
                    changed = True
                elif result.get("base64"):  # joined before uploads existed: copy it to S3 once
                    url = await media_store.save(result["base64"], "video/mp4", "video")
                    if url:
                        project.update(status="done", url=url, voice=bool(result.get("voice")))
                        changed = True
                elif result.get("status") == "failed":
                    project.update(status="failed", error=result.get("error") or "couldn't join the scenes")
                    changed = True
    if changed:
        _save_project(account_id, project)
    return project


@router.post("/video/callback")
async def video_callback(request: Request):
    """Modal calls this when a scene or a join finishes, so the next step runs with nobody's app open."""
    from gateway.auth import secret_matches

    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not secret_matches(given, settings.MODAL_VIDEO_SECRET):
        raise HTTPException(401, "Bad token")
    body = await request.json()
    ref = ddb_backend.get("video_job_owner", str(body.get("job_id") or ""), fresh=True)
    if not ref:
        return {"ok": True, "ignored": "not part of a video project"}
    account_id, pid = ref.split(":", 1)
    project = _project(account_id, pid)
    if not project:
        return {"ok": True, "ignored": "project gone"}
    project = await _advance(account_id, project)
    return {"ok": True, "status": project["status"]}


async def advance_all() -> dict:
    """The tick's safety net (every 15 min): moves every unfinished video on, in case a callback was missed."""
    moved = {}
    for ref in _active():
        account_id, pid = ref.split(":", 1)
        project = _project(account_id, pid)
        if not project:
            continue
        try:
            moved[pid] = (await _advance(account_id, project))["status"]
        except Exception as e:
            moved[pid] = f"error: {str(e)[:120]}"
    return moved


@router.get("/video/project/{pid}")
async def video_project_status(pid: str, account: dict = Depends(require_account)):
    project = _project(account["account_id"], pid)
    if not project:
        raise HTTPException(404, "This video is gone (kept 7 days)")
    return await _advance(account["account_id"], project)


@router.post("/video/project/{pid}/join")
async def video_project_rejoin(pid: str, account: dict = Depends(require_account)):
    """Joins the finished scenes again (CPU only, a few cents) after a failed join."""
    project = _project(account["account_id"], pid)
    if not project:
        raise HTTPException(404, "This video is gone (kept 7 days)")
    if not all(s.get("status") == "done" for s in project["scenes"]):
        raise HTTPException(400, "Some scenes aren't rendered yet")
    project.update(status="joining", error="", stitch_job="", rejoins=0)
    _save_project(account["account_id"], project)
    return await _advance(account["account_id"], project)


@router.post("/video/project/{pid}/scene/{index}")
async def video_project_retry(pid: str, index: int, account: dict = Depends(require_account)):
    """Renders one failed scene again; the join waits for it."""
    project = _project(account["account_id"], pid)
    if not project or not 0 <= index < len(project["scenes"]):
        raise HTTPException(404, "No such scene")
    scene = project["scenes"][index]
    result = await video_call("submit", prompt=scene["prompt"], aspect_ratio=project["aspect_ratio"], seconds=5,
                              fast=bool(project.get("fast")), callback=_callback_url())
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "video submit failed")
    scene.update(job_id=result["job_id"], status="rendering", error="")
    project.update(status="rendering", error="")
    project.pop("stitch_job", None)
    _save_project(account["account_id"], project)
    return project


@router.get("/video/projects")
async def video_projects(account: dict = Depends(require_account)):
    out = []
    for pid in _project_ids(account["account_id"]):
        p = _project(account["account_id"], pid)
        if p:
            out.append({k: p.get(k) for k in ("id", "title", "format", "aspect_ratio", "status", "url", "created")}
                       | {"scenes": len(p["scenes"])})
    return {"projects": out}


@router.get("/video/{job_id}")
async def video_status(job_id: str, _account: dict = Depends(require_account)):
    result = await _video_result(job_id)
    if not result.get("ok") and result.get("status") != "failed":
        raise HTTPException(400, result.get("error") or "status check failed")
    return result


# ── Web: logos, single-file pages, Figma frames ───────────────────────────

FIGMA = "figma"


@router.post("/logos")
async def logos(request: Request, account: dict = Depends(require_account)):
    body = await request.json()
    name = (body.get("name") or "").strip()[:60]
    if not name:
        raise HTTPException(400, "Give the business name for the logo")
    wanted = [s for s in (body.get("styles") or [s for s, _ in LOGO_STYLES]) if s in dict(LOGO_STYLES)][:4]
    brief, notes = (body.get("brief") or "")[:2000], (body.get("notes") or "")[:300]
    session = session_for("design", body)

    async def stream():
        for i, style in enumerate(wanted):
            yield f"data: {json.dumps({'type': 'status', 'text': f'Drawing logo {i + 1} of {len(wanted)} ({style})…'})}\n\n"
            img = await image_gen.generate_image(logo_prompt(name, brief, style, notes), "1:1")
            await log(session, "gemini", f"{'ok' if img['ok'] else 'blocked'}:logo {style}")
            if img["ok"]:
                url = await media_store.save(img["base64"], img["mime"], "web")
                shown = {"url": url} if url else {"base64": img["base64"]}
                yield f"data: {json.dumps({'type': 'logo', 'index': i, 'style': style, 'mime': img['mime'], **shown})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'logo_error', 'index': i, 'style': style, 'error': img['error']})}\n\n"
                if img.get("rate_limited"):
                    break
        yield "data: [DONE]\n\n"

    return durable(stream(), account["account_id"], body, "design")


@router.post("/page")
async def page(request: Request, account: dict = Depends(require_account)):
    body = await request.json()
    ask = (body.get("request") or "").strip()
    if not ask:
        raise HTTPException(400, "Say what to build, e.g. a one-page site for the bakery")
    current = body.get("html") or ""
    session = session_for("design", body)

    async def stream():
        text = "Updating the page…" if current else "Designing the page…"
        yield f"data: {json.dumps({'type': 'status', 'text': text})}\n\n"
        result = await make_page(body.get("brief") or "", ask, body.get("model") or "auto", body.get("design") or "", current)
        await log(session, "design", f"{'ok' if result['ok'] else 'blocked'}:web page — {result.get('model') or result.get('error', '')[:120]}")
        if result["ok"]:
            yield f"data: {json.dumps({'type': 'page', 'html': result['html'], 'model': result['model']})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'text': result['error']})}\n\n"
        yield "data: [DONE]\n\n"

    return durable(stream(), account["account_id"], body, "design")


@router.get("/figma")
async def figma_status(account: dict = Depends(require_account)):
    db = await get_store()
    return {"connected": bool(await db.get_connector(account["account_id"], FIGMA))}


@router.post("/figma/connect")
async def figma_connect(request: Request, account: dict = Depends(require_account)):
    token = ((await request.json()).get("token") or "").strip()
    me = await figma_me(token) if token else {}
    if not me:
        raise HTTPException(400, "Figma didn't accept that token — make one in Figma → Settings → Security → Personal access tokens (File content: read)")
    db = await get_store()
    await db.upsert_connector(account["account_id"], FIGMA, token)
    return {"connected": True, "handle": me.get("handle", "")}


@router.post("/figma/import")
async def figma_import(request: Request, account: dict = Depends(require_account)):
    """A Figma link → its frames as images (kept 7 days) plus build notes the page generator follows."""
    url = ((await request.json()).get("url") or "").strip()
    db = await get_store()
    conn = await db.get_connector(account["account_id"], FIGMA)
    if not conn:
        raise HTTPException(400, "Connect Figma first")
    result = await figma_frames(conn["token"], url)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    frames = result["frames"]
    notes = await gemini_media.describe_design(frames)
    shown = []
    for f in frames:
        saved = await media_store.save(f["base64"], f["mime"], "web")
        shown.append({"name": f["name"], **({"url": saved} if saved else {"mime": f["mime"], "base64": f["base64"]})})
    return {"frames": shown, "notes": notes.get("text", ""),
            **({} if notes.get("ok") else {"notes_error": notes.get("error", "Couldn't read the design")})}


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
