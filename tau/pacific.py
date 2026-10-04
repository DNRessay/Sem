import json
import re
import time
from datetime import datetime, timedelta, timezone

_SAST = timezone(timedelta(hours=2))
_MIN_MESSAGES = 10

_PROMPT = """Below are recent messages one person sent to their AI assistant. Infer their Big Five personality
traits from how they write and what they ask about — implicit signals, not self-description.
Return ONLY JSON: {{"O": 0-1, "C": 0-1, "E": 0-1, "A": 0-1, "N": 0-1,
"style": "one or two sentences on how they like answers (length, tone, format) that an assistant should follow"}}
0.5 means average or not enough evidence. Be conservative.

Messages:
{messages}"""


async def refresh_profile() -> dict | None:
    """Medium tier, once a day from the tick: an LLM reads recent messages
    across every conversation and saves OCEAN scores plus an observed answer
    style to the owner's profile, which every chat's TAU context reads."""
    from config import settings
    from pipeline import llm_providers
    from storage.neon_store import get_store

    db = await get_store()
    today = datetime.now(_SAST).strftime("%Y-%m-%d")
    if await db.get_state("pacific:last_refresh") == today:
        return None
    memories = sorted(await db.get_recent_memories(limit=300), key=lambda m: m.get("created_at", 0))[-150:]
    texts = [m["content"][:300] for m in memories if m.get("content")]
    if len(texts) < _MIN_MESSAGES:
        await db.set_state("pacific:last_refresh", today)  # too little to read: try again tomorrow
        return None
    result = await llm_providers.complete(
        "auto", [{"role": "user", "content": _PROMPT.format(messages="\n".join(f"- {t}" for t in texts))}], max_tokens=500,
    )
    match = re.search(r"\{.*\}", result.get("content") or "", re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    ocean = {k: min(1.0, max(0.0, float(data[k]))) for k in "OCEAN" if isinstance(data.get(k), (int, float))}
    if len(ocean) != 5:
        return None
    owner = settings.OWNER_ACCOUNT_ID
    model = await db.get_user_model(owner) or {}
    model.update({"ocean": ocean, "ocean_updated_at": int(time.time())})
    if isinstance(data.get("style"), str) and data["style"].strip():
        model["observed_style"] = data["style"].strip()[:400]
    await db.save_user_model(owner, model)
    # Only a refresh that worked counts for today: a failed model call or a bad reply is retried on the next tick.
    await db.set_state("pacific:last_refresh", today)
    from cache.tau_cache import TAUCache
    TAUCache().bump_version()  # every chat picks up the new profile on its next message
    return {"ocean": ocean, "messages_read": len(texts)}


class PACIFICEngine:
    """
    Big Five OCEAN from implicit conversation signals. The real profile comes
    from refresh_profile() above (daily, LLM-read, saved); infer_traits() is
    the keyword estimate used only until that first refresh has run.
    """

    def infer_traits(self, history: list) -> dict:
        text = " ".join(
            m.get("content", "") for m in history if isinstance(m, dict)
        ).lower()

        return {
            "O": self._openness(text),
            "C": self._conscientiousness(text),
            "E": self._extraversion(text),
            "A": self._agreeableness(text),
            "N": self._neuroticism(text),
        }

    def _openness(self, t: str) -> float:
        keywords = ["explore", "creative", "idea", "curious", "imagine", "design", "novel"]
        return min(1.0, 0.5 + 0.07 * sum(k in t for k in keywords))

    def _conscientiousness(self, t: str) -> float:
        keywords = ["plan", "deadline", "organise", "structure", "detail", "precise", "schedule"]
        return min(1.0, 0.5 + 0.07 * sum(k in t for k in keywords))

    def _extraversion(self, t: str) -> float:
        keywords = ["team", "meeting", "social", "people", "network", "talk", "collaborate"]
        return min(1.0, 0.5 + 0.07 * sum(k in t for k in keywords))

    def _agreeableness(self, t: str) -> float:
        keywords = ["thanks", "please", "help", "appreciate", "support", "kind", "agree"]
        return min(1.0, 0.5 + 0.07 * sum(k in t for k in keywords))

    def _neuroticism(self, t: str) -> float:
        keywords = ["worried", "stress", "anxious", "problem", "issue", "stuck", "fail"]
        return min(1.0, 0.5 + 0.07 * sum(k in t for k in keywords))

    def get_personalization_vector(self, traits: dict) -> list:
        return [traits.get(k, 0.5) for k in ["O", "C", "E", "A", "N"]]
