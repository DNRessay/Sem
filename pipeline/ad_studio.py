import json
import re

from pipeline import llm_providers

# Platform -> (label, aspect ratio the image is made at). Each platform has its own playbook below: people use
# them differently, so the same picture and caption don't work everywhere.
PLACEMENTS = {
    "instagram": ("Instagram", "4:5"),
    "facebook": ("Facebook", "4:5"),
    "pinterest": ("Pinterest", "2:3"),
    "linkedin": ("LinkedIn", "1:1"),
    "story": ("Stories & Status", "9:16"),
    "tiktok": ("TikTok photo", "9:16"),
    "google_display": ("Google Display", "16:9"),
}
# Ids from before platforms (kept in saved chats).
ALIASES = {"fb_ig_feed": "instagram", "square": "facebook", "story_reel": "story", "whatsapp_status": "story"}

# (how the image should look, the post text, how many hashtags)
PLAYBOOK = {
    "instagram": (
        "A scroll-stopping, gallery-worthy photo people save because it's beautiful, not because it sells: strong "
        "composition, rich natural light, a striking colour story, real textures, an aspirational lifestyle moment. "
        "NO text on the image. The business is present (its product, place or craft) but it's art first, advert second.",
        "Instagram caption: a hook line, 2-4 short lines of story or feeling, a soft call to action (save, share, link "
        "in bio), the area named naturally. Emojis welcome but sparing.", 12),
    "facebook": (
        "A clear, friendly, informative image for a business page and boosted posts: show the actual offer or service "
        "plainly, warm and trustworthy, real local people and places. ONE short headline on the image in big bold "
        "readable letters (the offer, the price, 'free', 'new') with clean space around it.",
        "Facebook post: plain informative text like a helpful page update: what it is, why it's good value (free, "
        "cheaper, saves time), who it's for, where (area), and exactly what to do next (link, WhatsApp, call).", 3),
    "pinterest": (
        "A tall vertical pin built to be clicked: a bold title on the image in large clean type over a calm part of the "
        "picture (a how-to, a list, a promise: '5 ways…', 'How to…', 'Free…'), an inspiring styled photo below it, "
        "bright and clean, with obvious value.",
        "Pin: a keyword-rich pin title (what people type into search) and a 2-3 sentence description packed naturally "
        "with search phrases and the area, ending with what they get when they click.", 5),
    "linkedin": (
        "A professional, credible image: real people at work, a modern South African business setting, natural office "
        "or on-site light, confident and polished, muted corporate colours. At most one short line of text, "
        "understated.",
        "LinkedIn post: professional tone, opens with an insight or a business problem, 3-5 short lines on the value "
        "and results, ends with a question or a clear next step. No slang, few emojis.", 4),
    "story": (
        "A full-screen vertical story (Instagram/Facebook Stories, WhatsApp Status): bold and simple, the subject big "
        "in the middle, ONE punchy line of large text in the top or bottom third, leaving room for stickers/UI.",
        "Story text: one short punchy line plus a tap/swipe/reply action (e.g. 'Reply YES', 'Tap the link').", 2),
    "tiktok": (
        "A TikTok photo-mode slide: casual, authentic, phone-shot feel, trendy and fun, bold short text in TikTok "
        "style, bright and energetic. (TikTok is mostly video; this is for a photo post.)",
        "TikTok caption: short, casual, a hook and a question to drive comments, local slang welcome where it fits.", 5),
    "google_display": (
        "A wide clean web banner: the product or service on one side, clear space on the other for the headline, "
        "brand colours, uncluttered, readable at small sizes.",
        "Banner copy: headline and one line of benefit; no hashtags.", 0),
}

_PROMPT = """You are a social media strategist, copywriter and art director for a small business.

Business: {brief}
Campaign: {campaign}
Area to target: {area}

Write {count} distinct post(s) for each of these platforms, following each platform's playbook exactly:
{playbooks}

Return ONLY a JSON array. Each item:
{{"placement": one of {keys}, "angle": short name of the creative angle,
"headline": the line printed on the image or the pin title ("" for Instagram), <= 40 chars,
"caption": the full post text, ready to paste, written to that platform's playbook,
"cta": a short call-to-action label,
"hashtags": exactly the playbook's number of hashtags: a third popular and broad, a third for the industry or niche,
a third local (the area, city, province, and South Africa/Mzansi tags if the business is in South Africa); CamelCase,
no spaces, relevant only, never banned or spammy tags,
"keywords": 3-6 phrases people would actually type into Google, Instagram, Facebook or Pinterest search to find this,
including the area (e.g. "website design Soweto", "affordable websites Johannesburg"),
"alt_text": <= 125 chars describing the image with the main keyword (for accessibility and search),
"image_prompt": an art director's brief for the image model, 60-100 words, following the platform's look: the real
subject (product, food, person or place from the brief, with specific looks, materials and colours), what is
happening, the setting, composition for the platform's shape, lighting, camera and lens, style and colour palette in
words. Text on the image only as the playbook says, in quotes, under 6 words, with placement and font style}}

Weave the keywords and the area naturally into the caption so people searching for them find the post (no keyword
stuffing). Show the actual business, not abstract shapes or generic icons. Write for the audience and location in
the brief; South African English and Rand prices if the business is in South Africa. No false claims.{style}"""


def _json_items(text: str) -> list:
    """The JSON array in a model's reply. Open models often wrap it in <think> reasoning or ``` fences, leave
    trailing commas, or put it under a key ({"ads": [...]})."""
    text = re.sub(r"<think>.*?(</think>|$)", "", text or "", flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    for open_, close in (("[", "]"), ("{", "}")):
        i, j = text.find(open_), text.rfind(close)
        if i == -1 or j <= i:
            continue
        raw = text[i:j + 1]
        for candidate in (raw, re.sub(r",\s*([\]}])", r"\1", raw)):
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                data = next((v for v in data.values() if isinstance(v, list)), [data])
            if isinstance(data, list):
                return data
    return []


def _placement(value, wanted: list[str]) -> str:
    v = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    v = next((new for old, new in ALIASES.items() if v.startswith(old)), v)
    wanted = [ALIASES.get(w, w) for w in wanted]
    if v in PLACEMENTS:
        return v
    for key, (label, _) in PLACEMENTS.items():
        if v and (v in key or key in v or v in re.sub(r"[^a-z0-9]+", "_", label.lower())):
            return key
    return wanted[0] if len(wanted) == 1 else ""


def parse_variants(text: str, wanted: list[str] | None = None) -> list[dict]:
    out = []
    for it in _json_items(text):
        if not isinstance(it, dict) or not it.get("image_prompt"):
            continue
        it["placement"] = _placement(it.get("placement"), wanted or [])
        if it["placement"] not in PLACEMENTS:
            continue
        it["aspect_ratio"] = PLACEMENTS[it["placement"]][1]
        tags = [h.strip() for h in (it.get("hashtags") or []) if isinstance(h, str) and h.strip()]
        tags = ["#" + re.sub(r"\s+", "", t.lstrip("#")) for t in tags]
        it["hashtags"] = list(dict.fromkeys(tags))[:PLAYBOOK[it["placement"]][2]]
        it["keywords"] = [k for k in (it.get("keywords") or []) if isinstance(k, str)][:6]
        it["caption"] = str(it.get("caption") or it.get("primary_text") or "")
        it["primary_text"] = it["caption"]  # older app versions read this
        out.append(it)
    return out


def _playbook(p: str) -> str:
    look, text, tags = PLAYBOOK[p]
    return (f"- {p} ({PLACEMENTS[p][0]}, {PLACEMENTS[p][1]} image)\n  Look: {look}\n  Text: {text}\n"
            f"  Hashtags: {tags if tags else 'none'}")


async def write_variants(brief: str, campaign: str, placements: list[str], count: int, model: str,
                         style: str = "", area: str = "") -> dict:
    placements = list(dict.fromkeys(ALIASES.get(p, p) for p in placements if ALIASES.get(p, p) in PLACEMENTS)) or ["instagram"]
    count = max(1, min(int(count or 1), 3))
    prompt = _PROMPT.format(
        brief=brief.strip()[:2000], campaign=campaign.strip()[:1000], count=count,
        area=area.strip()[:120] or "the business's own area from the brief",
        style=f"\n\nVisual style to match (from the user's inspiration images) — reflect it in every image_prompt:\n{style[:1500]}"
        if style else "",
        playbooks="\n".join(_playbook(p) for p in placements), keys=list(placements),
    )
    messages = [{"role": "user", "content": prompt}]
    result = await llm_providers.complete(model, messages, max_tokens=4096)
    variants = [] if "error" in result else parse_variants(result.get("content") or "", placements)
    if not variants and model == "auto":
        # One free model answered with something unusable (or not at all): give the others a go.
        for pid in llm_providers.FREE_ORDER:
            if pid == result.get("_provider") or not llm_providers.PROVIDERS[pid].configured:
                continue
            retry = await llm_providers.complete(pid, messages, max_tokens=4096)
            variants = [] if "error" in retry else parse_variants(retry.get("content") or "", placements)
            if variants:
                break
            if "error" in result:
                result = retry
    if not variants:
        if "error" in result:
            return {"ok": False, "error": result["error"]}
        return {"ok": False, "error": "The model didn't return usable posts — try again or pick another model"}
    return {"ok": True, "variants": variants[: count * len(placements)]}
