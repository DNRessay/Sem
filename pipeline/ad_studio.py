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
        return {"ok": False, "error": "The model didn't return usable ad variants — try again or pick another model"}
    return {"ok": True, "variants": variants[: count * len(placements)]}
