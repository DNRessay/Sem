import json
import re

from pipeline import llm_providers

# Placement -> (label, aspect ratio Nano Banana renders at).
PLACEMENTS = {
    "fb_ig_feed": ("Facebook/Instagram feed", "4:5"),
    "square": ("Square post", "1:1"),
    "story_reel": ("Story / Reel / TikTok", "9:16"),
    "google_display": ("Google Display / banner", "16:9"),
    "whatsapp_status": ("WhatsApp Status", "9:16"),
}

_PROMPT = """You are a performance-marketing copywriter and art director for a small business.

Business: {brief}
Campaign: {campaign}
Write {count} distinct ad variants for each of these placements: {placements}.

Return ONLY a JSON array. Each item:
{{"placement": one of {keys}, "angle": short name of the creative angle,
"headline": <= 40 chars, "primary_text": <= 125 chars for the main ad text, "cta": a call-to-action button label,
"hashtags": [up to 5], "image_prompt": a detailed prompt for an image generator — layout, subject, colours, lighting,
and any short on-image text in quotes (keep on-image text under 6 words)}}

Vary the angles (benefit, social proof, urgency/offer, problem/solution, local pride). Write for the audience and
location in the brief; South African English and Rand pricing if the business is in South Africa. No false claims.{style}"""


def parse_variants(text: str) -> list[dict]:
    match = re.search(r"\[.*\]", text or "", re.S)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or it.get("placement") not in PLACEMENTS or not it.get("image_prompt"):
            continue
        it["aspect_ratio"] = PLACEMENTS[it["placement"]][1]
        it["hashtags"] = [h for h in (it.get("hashtags") or []) if isinstance(h, str)][:5]
        out.append(it)
    return out


async def write_variants(brief: str, campaign: str, placements: list[str], count: int, model: str,
                         style: str = "") -> dict:
    placements = [p for p in placements if p in PLACEMENTS] or ["fb_ig_feed"]
    count = max(1, min(int(count or 1), 3))
    prompt = _PROMPT.format(
        brief=brief.strip()[:2000], campaign=campaign.strip()[:1000], count=count,
        style=f"\n\nVisual style to match (from the user's inspiration images) — reflect it in every image_prompt:\n{style[:1500]}"
        if style else "",
        placements=", ".join(f"{p} ({PLACEMENTS[p][0]})" for p in placements), keys=list(placements),
    )
    result = await llm_providers.complete(model, [{"role": "user", "content": prompt}], max_tokens=4096)
    if "error" in result:
        return {"ok": False, "error": result["error"]}
    variants = parse_variants(result.get("content") or "")
    if not variants:
        return {"ok": False, "error": "The model didn't return usable ad variants — try again or pick another model"}
    return {"ok": True, "variants": variants[: count * len(placements)]}
