"""Video studio: short (Reels/TikTok/Shorts) and long-form (YouTube) videos. Wan 2.1 renders 5-second clips, so a
longer video is a storyboard: one 5-second scene per clip, all sharing one look, joined on Modal with an optional
Gemini voiceover read over the whole thing."""
import json
import math
import re

from pipeline import llm_providers
from pipeline.ad_studio import _json_items

CLIP_SECONDS = 5
MAX_SECONDS = 60
FORMATS = {"short": {"label": "Short (Reels, TikTok, Shorts)", "aspect_ratio": "9:16", "lengths": [5, 10, 15, 30]},
           "long": {"label": "Long (YouTube)", "aspect_ratio": "16:9", "lengths": [15, 30, 45, 60]},
           "square": {"label": "Square (feed)", "aspect_ratio": "1:1", "lengths": [5, 10, 15, 30]}}
# What one 5-second Wan clip costs on the L4 (about 10 minutes at $0.80/h), for the estimate before rendering.
CLIP_MINUTES = 10
CLIP_USD = round(CLIP_MINUTES / 60 * 0.80, 2)
WORDS_PER_SECOND = 2.3  # a relaxed voiceover pace

_PROMPT = """You are a video director making a {length}-second {kind} video for this business.

Business brief:
{brief}

What the video is about:
{idea}

It is made of exactly {n} scenes of {clip} seconds each, rendered one at a time by a text-to-video model that sees
ONLY that scene's prompt. So:
- Start with one "style" line (camera, lighting, colour grade, setting, the main subject's look) and repeat the
  important parts of it inside every scene prompt, so the clips look like one video.
- Each scene prompt is one concrete shot: subject, action, camera move, framing ({aspect}). No on-screen text, logos
  or brand names (the model can't draw them).
- Tell a story across the scenes: hook in the first scene, payoff or call to action in the last.
{voice}
Reply with JSON only:
{{"title": short title, "style": the style line, "scenes": [{{"prompt": scene prompt, "narration": {narration}}}]}}"""


def scene_count(seconds: int) -> int:
    return max(1, min(math.ceil(int(seconds or CLIP_SECONDS) / CLIP_SECONDS), MAX_SECONDS // CLIP_SECONDS))


def estimate(seconds: int) -> dict:
    n = scene_count(seconds)
    return {"scenes": n, "minutes": n * CLIP_MINUTES, "usd": round(n * CLIP_USD, 2)}


def _json_object(text: str) -> dict:
    text = re.sub(r"<think>.*?(</think>|$)", "", text or "", flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    i, j = text.find("{"), text.rfind("}")
    if i == -1 or j <= i:
        return {}
    for candidate in (text[i:j + 1], re.sub(r",\s*([\]}])", r"\1", text[i:j + 1])):
        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            continue
    return {}


def parse_plan(text: str, n: int, voiceover: bool) -> dict | None:
    meta = _json_object(text)
    scenes = meta.get("scenes") if isinstance(meta.get("scenes"), list) else _json_items(text)
    scenes = [s for s in scenes if isinstance(s, dict) and str(s.get("prompt") or "").strip()][:n]
    if not scenes:
        return None
    while len(scenes) < n:  # a model that wrote too few: hold the last shot rather than fail
        scenes.append(dict(scenes[-1]))
    return {"title": str(meta.get("title") or "").strip()[:80], "style": str(meta.get("style") or "").strip()[:400],
            "scenes": [{"prompt": str(s["prompt"]).strip()[:1200],
                        "narration": str(s.get("narration") or "").strip()[:300] if voiceover else ""} for s in scenes]}


async def plan_video(brief: str, idea: str, seconds: int, fmt: str, voiceover: bool, model: str) -> dict:
    fmt = fmt if fmt in FORMATS else "short"
    n = scene_count(seconds)
    words = int(CLIP_SECONDS * WORDS_PER_SECOND)
    prompt = _PROMPT.format(
        length=n * CLIP_SECONDS, kind=FORMATS[fmt]["label"], brief=(brief or "(no brief: keep it general)").strip()[:2000],
        idea=idea.strip()[:1500], n=n, clip=CLIP_SECONDS, aspect=FORMATS[fmt]["aspect_ratio"],
        voice=(f"- Write a voiceover line for every scene, at most {words} words, spoken while that scene plays; "
               "together they read as one script. South African English if the business is in South Africa.\n")
        if voiceover else "",
        narration=f'"voiceover line, max {words} words"' if voiceover else '""')
    messages = [{"role": "user", "content": prompt}]
    result = await llm_providers.complete(model, messages, max_tokens=3000)
    plan = None if "error" in result else parse_plan(result.get("content") or "", n, voiceover)
    if not plan and model == "auto":
        for pid in llm_providers.FREE_ORDER:
            if pid == result.get("_provider") or not llm_providers.PROVIDERS[pid].configured:
                continue
            retry = await llm_providers.complete(pid, messages, max_tokens=3000)
            plan = None if "error" in retry else parse_plan(retry.get("content") or "", n, voiceover)
            if plan:
                break
    if not plan:
        return {"ok": False, "error": result.get("error") or "The model didn't return a usable storyboard — try again or pick another model"}
    return {"ok": True, "format": fmt, "aspect_ratio": FORMATS[fmt]["aspect_ratio"], **plan, "estimate": estimate(n * CLIP_SECONDS)}
