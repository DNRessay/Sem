"""✨ Improve: turns a rough idea typed into the Images, Music or Web composer into the detailed prompt that tool
works best with, for the user to check and edit before sending (like the storyboard does for videos)."""
import json
import re

from pipeline import llm_providers

_GUIDES = {
    "images": """Rewrite it as a campaign brief for a social media post writer, 3-5 sentences:
what's being promoted (the offer, price or freebie, exact), who it's for, the area (if given), the feeling or visual
idea that would stop someone scrolling, and the one action people should take. Keep every fact the user gave; don't
invent prices, dates or claims.""",
    "music": """Rewrite it as a prompt for the ACE-Step music model: comma-separated tags, under 40 words, covering
genre and sub-genre, mood, tempo in BPM, 3-5 key instruments, the vocal style (or "instrumental") and the production
feel (e.g. "amapiano, deep house, uplifting, 112 bpm, log drums, shakers, warm piano chords, airy pads, instrumental,
polished club mix"). If the user asked for singing or gave lyric ideas, also write short lyrics in "lyrics" using
[verse] and [chorus] sections (8-16 lines, in the language they used); otherwise "lyrics" is "".""",
    "web": """Rewrite it as a clear spec for a one-page website builder, as a short list:
the page's goal and audience, then each section in order (hero with headline and button, then e.g. services, offer,
how it works, reviews, pricing, FAQ, contact/WhatsApp) with what goes in it, the call to action, and the look (style,
colours, mood). Use real details from the business brief; keep anything the user asked for.""",
}

_PROMPT = """You improve prompts for a small business's marketing tools.

Business brief: {brief}
{extra}
The user typed: {text}

{guide}

Reply with JSON only: {{"text": the improved prompt{lyrics}}}"""


def _parse(reply: str) -> dict:
    reply = re.sub(r"<think>.*?(</think>|$)", "", reply or "", flags=re.S)
    reply = re.sub(r"```(?:json)?", "", reply).strip()
    i, j = reply.find("{"), reply.rfind("}")
    if i != -1 and j > i:
        try:
            data = json.loads(reply[i:j + 1])
            if isinstance(data, dict) and str(data.get("text") or "").strip():
                return data
        except json.JSONDecodeError:
            pass
    text = reply.strip().strip('"')
    return {"text": text} if len(text.split()) >= 5 else {}


async def improve(kind: str, text: str, brief: str = "", extra: str = "", model: str = "auto") -> dict:
    if kind not in _GUIDES:
        return {"ok": False, "error": f"Nothing to improve for {kind!r}"}
    if not text.strip():
        return {"ok": False, "error": "Type an idea first"}
    messages = [{"role": "user", "content": _PROMPT.format(
        brief=(brief or "(none given)").strip()[:1500], extra=extra.strip()[:300], text=text.strip()[:1500],
        guide=_GUIDES[kind], lyrics=', "lyrics": lyrics or ""' if kind == "music" else "")}]
    tried, result = set(), {}
    for choice in (model, "groq", "gemini", "bonsai"):
        if choice in tried or (choice in llm_providers.PROVIDERS and not llm_providers.PROVIDERS[choice].configured):
            continue
        tried.add(choice)
        result = await llm_providers.complete_within(choice, messages, seconds=45, max_tokens=1200)
        tried.add(result.get("_provider"))
        data = {} if "error" in result else _parse(result.get("content") or "")
        if data:
            out = {"ok": True, "text": str(data["text"]).strip()[:2000]}
            if kind == "music":
                out["lyrics"] = str(data.get("lyrics") or "").strip()[:3000]
            return out
    return {"ok": False, "error": result.get("error") or "Couldn't improve that — try again"}
