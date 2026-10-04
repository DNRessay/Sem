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
FAST_CLIP_MINUTES = 2  # fast mode (CausVid LoRA, ~6 steps)
FAST_CLIP_USD = round(FAST_CLIP_MINUTES / 60 * 0.80, 2)
WORDS_PER_SECOND = 2.6  # TTS reads briskly: lines written at a slower pace left silence at the end

# How Wan 2.1 wants to be prompted: its demos all run through "prompt extension", which turns a short idea into one
# dense English paragraph like this. Short prompts are the main reason our clips looked worse than the demos.
WAN_GUIDE = """Write each scene prompt the way Wan 2.1 was trained: ONE paragraph of 80-120 English words, concrete and visual:
1. Main subject with specific looks: age, build, skin, hair, clothing (colours, materials), or the product's shape,
   texture and colour.
2. One simple, continuous action with natural motion words (slowly pours, steam rises, turns to the camera, smiles).
3. Setting and background details: place, props, time of day, weather.
4. Lighting: source, direction and quality (soft morning window light, golden-hour backlight, warm tungsten).
5. Camera: shot size, angle, lens and ONE movement (close-up, low angle, 35mm, shallow depth of field, slow dolly-in,
   smooth tracking shot, static tripod).
6. Look: photorealistic, cinematic, colour palette, film grain, high detail.
Words on screen only when the user asks for them (a business name on a sign or a screen): then write the exact word
in double quotes with its look, e.g. the screen shows the word "VICINIC" in large glowing gold letters, keep it short,
and repeat it in every scene it should appear in.
Avoid: other on-screen text, logos, brand names, crowds, more than two people, fast or complicated actions, cuts or several
shots in one clip, and abstract words (amazing, quality, success) that show nothing."""

_EXTEND = """Rewrite this idea as a prompt for a 5-second {aspect} clip.

{guide}

Business context (for setting and props only): {brief}
Idea: {idea}

Reply with the prompt paragraph only."""

_PROMPT = """You are a video director making a {length}-second {kind} video for this business.

Business brief:
{brief}

What the video is about:
{idea}

It is made of exactly {n} scenes of {clip} seconds each, rendered one at a time by a text-to-video model that sees
ONLY that scene's prompt. So:
- Start with one "style" line (camera, lighting, colour grade, setting, the main subject's look) and repeat the
  important parts of it inside every scene prompt, so the clips look like one video.
- Each scene prompt is one concrete shot framed for {aspect}.

{guide}
- Tell a story across the scenes: hook in the first scene, payoff or call to action in the last.
{voice}
- One "music" line for an instrumental background track: genre, mood, tempo (BPM) and 2-3 instruments, e.g.
  "warm lo-fi hip hop, relaxed, 85 BPM, soft piano, vinyl crackle, mellow drums". No vocals, no artist names.
Reply with JSON only:
{{"title": short title, "style": the style line, "music": the music line, "scenes": [{{"prompt": scene prompt, "narration": {narration}}}]}}"""


def scene_count(seconds: int) -> int:
    return max(1, min(math.ceil(int(seconds or CLIP_SECONDS) / CLIP_SECONDS), MAX_SECONDS // CLIP_SECONDS))


def estimate(seconds: int, fast: bool = False) -> dict:
    n = scene_count(seconds)
    minutes, usd = (FAST_CLIP_MINUTES, FAST_CLIP_USD) if fast else (CLIP_MINUTES, CLIP_USD)
    return {"scenes": n, "minutes": n * minutes, "usd": round(n * usd, 2)}


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


_SCENE_RE = re.compile(r'\{\s*"prompt"\s*:\s*"((?:[^"\\]|\\.)*)"(?:\s*,\s*"narration"\s*:\s*"((?:[^"\\]|\\.)*)")?\s*\}')


def _salvage(text: str) -> list[dict]:
    """Complete scenes out of a reply that was cut off mid-way (a model's output limit)."""
    out = []
    for m in _SCENE_RE.finditer(text or ""):
        try:
            out.append({"prompt": json.loads(f'"{m.group(1)}"'), "narration": json.loads(f'"{m.group(2) or ""}"')})
        except ValueError:
            continue
    return out


def parse_plan(text: str, n: int, voiceover: bool) -> dict | None:
    meta = _json_object(text)
    scenes = meta.get("scenes") if isinstance(meta.get("scenes"), list) else (_json_items(text) or _salvage(text))
    if not meta:
        title = re.search(r'"title"\s*:\s*"([^"]*)"', text or "")
        style = re.search(r'"style"\s*:\s*"([^"]*)"', text or "")
        music = re.search(r'"music"\s*:\s*"([^"]*)"', text or "")
        meta = {"title": title.group(1) if title else "", "style": style.group(1) if style else "",
                "music": music.group(1) if music else ""}
    scenes = [s for s in scenes if isinstance(s, dict) and str(s.get("prompt") or "").strip()][:n]
    if not scenes:
        return None
    while len(scenes) < n:  # a model that wrote too few: hold the last shot rather than fail
        scenes.append(dict(scenes[-1]))
    return {"title": str(meta.get("title") or "").strip()[:80], "style": str(meta.get("style") or "").strip()[:400],
            "music": str(meta.get("music") or "").strip()[:300],
            "scenes": [{"prompt": str(s["prompt"]).strip()[:1500],
                        "narration": str(s.get("narration") or "").strip()[:300] if voiceover else ""} for s in scenes]}


async def plan_video(brief: str, idea: str, seconds: int, fmt: str, voiceover: bool, model: str) -> dict:
    fmt = fmt if fmt in FORMATS else "short"
    n = scene_count(seconds)
    words = int(CLIP_SECONDS * WORDS_PER_SECOND)
    prompt = _PROMPT.format(
        length=n * CLIP_SECONDS, kind=FORMATS[fmt]["label"], brief=(brief or "(no brief: keep it general)").strip()[:2000],
        idea=idea.strip()[:1500], n=n, clip=CLIP_SECONDS, aspect=FORMATS[fmt]["aspect_ratio"], guide=WAN_GUIDE,
        voice=(f"- Write a voiceover line for every scene, {words - 3}-{words} words (fill the scene, no dead air), "
               "spoken while that scene plays; "
               "together they read as one script. South African English if the business is in South Africa.\n")
        if voiceover else "",
        narration=f'"voiceover line, max {words} words"' if voiceover else '""')
    messages = [{"role": "user", "content": prompt}]
    # A storyboard is long (80-120 words a scene). Gemini allows long replies; Groq stops at ~800 tokens, which cut
    # 30-second storyboards off mid-scene. So with "auto", Gemini writes it first and the others are the fallback.
    first = "gemini" if model == "auto" and llm_providers.PROVIDERS["gemini"].configured else model
    result = await llm_providers.complete(first, messages, max_tokens=6000)
    plan = None if "error" in result else parse_plan(result.get("content") or "", n, voiceover)
    if not plan:  # unusable, cut off or down: the free models get a go whichever one was picked
        tried = {model, first, result.get("_provider")}
        for pid in llm_providers.FREE_ORDER:
            if pid in tried or not llm_providers.PROVIDERS[pid].configured:
                continue
            retry = await llm_providers.complete(pid, messages, max_tokens=6000)
            plan = None if "error" in retry else parse_plan(retry.get("content") or "", n, voiceover)
            if plan:
                break
    if not plan:
        return {"ok": False, "error": result.get("error") or "The model didn't return a usable storyboard — try again or pick another model"}
    return {"ok": True, "format": fmt, "aspect_ratio": FORMATS[fmt]["aspect_ratio"], **plan, "estimate": estimate(n * CLIP_SECONDS)}


def needs_extending(prompt: str) -> bool:
    return len(prompt.split()) < 45


async def extend_prompt(prompt: str, aspect: str, brief: str = "", model: str = "auto") -> str:
    """A short idea → the dense paragraph Wan renders well. Falls back to the idea itself if no model answers."""
    if not needs_extending(prompt):
        return prompt
    messages = [{"role": "user", "content": _EXTEND.format(aspect=aspect, guide=WAN_GUIDE, brief=(brief or "none")[:800],
                                                          idea=prompt.strip()[:800])}]
    result = await llm_providers.complete(model, messages, max_tokens=600)
    text = re.sub(r"<think>.*?(</think>|$)", "", result.get("content") or "", flags=re.S).strip().strip('"')
    return text[:1500] if "error" not in result and len(text.split()) >= 30 else prompt
