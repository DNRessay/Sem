import re

# Deterministic phrasing, same reasoning as every other intent in this
# package: no LLM tool-calling, just a regex trigger, so a question about
# SEMBLANCE's own capabilities gets a real answer from GuideAgent
# (agents/guide_agent.py — pure string lookup, zero LLM/network calls,
# so this is always safe to fire) instead of the model guessing at its
# own architecture from inside a chat turn.
_GUIDE_RE = re.compile(
    r"\b(what can you do|what are you capable of|what is semblance|"
    r"how do(?:es)? semblance work|how do you work|tell me about yourself|"
    r"what agents do you have|what tools do you have|what is your architecture|"
    r"who are you)\b",
    re.I,
)


def detect_guide_intent(query: str) -> str | None:
    """Returns the query itself (GuideAgent keyword-matches against the
    full text) if this looks like a self-knowledge question, else None."""
    if _GUIDE_RE.search(query):
        return query
    return None


def guide_status_label() -> str:
    return "Looking up SEMBLANCE's own docs…"


async def run_guide_intent(query: str, session_id: str) -> str:
    """Routes through CablesMan (Step 7) to GuideAgent — a plain string
    lookup against its own hardcoded self-knowledge, no LLM call and no
    external dependency, so failure here means a bug, not a rate limit or
    a down service. Returns "" on any unexpected shape so a caller falls
    back cleanly rather than crashing the turn."""
    from core.cables_man import CablesMan
    cables = CablesMan()
    result = await cables.route({"query": query, "agent": "guide", "session_id": session_id})
    if not isinstance(result, dict):
        return ""
    return result.get("answer", "")


def format_guide_result(answer: str) -> str:
    return answer or "I couldn't find anything in my self-knowledge for that."
