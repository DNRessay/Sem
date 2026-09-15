import datetime
import re
import time

# "When did I ask about Mandela" answered from whatever the model's own
# session history happened to contain, confidently, even though the real
# mention was in a completely different session 17 hours earlier — no
# grounding, just a plausible-sounding guess. This routes that exact
# question shape to a real search across every session's conversation
# history (storage.neon_store.search_conversations) instead, so the
# answer is a real timestamp and a real session, never a guess.
_WHEN_RE = re.compile(
    r"^\s*when did i (?:ask|say|mention|talk about|discuss)\b(?:\s+(?:u|you))?(?:\s+about)?\s+(.+?)\s*\??\s*$",
    re.I,
)
_COUNT_RE = re.compile(
    r"^\s*how many times (?:have i|did i) (?:say|said|mention|mentioned|ask|asked)\b(?:\s+about)?\s+(.+?)\s*\??\s*$",
    re.I,
)

_TIME_WINDOWS = {
    "today": 86400, "this week": 7 * 86400, "this month": 30 * 86400, "recently": 7 * 86400,
}


def _extract_time_window(text: str) -> tuple[str, int | None]:
    t = text.strip()
    for phrase in sorted(_TIME_WINDOWS, key=len, reverse=True):
        if t.lower().endswith(phrase):
            return t[: -len(phrase)].strip(), _TIME_WINDOWS[phrase]
    return t, None


def detect_memory_search_intent(query: str) -> dict | None:
    """Returns {"mode": "when"|"count", "term": str, "window": int|None}
    for a "when did I..."/"how many times have I..." question, else
    None. The term is whatever's left after stripping the trigger
    phrase and any trailing time-window words ("this month" etc.), which
    become a separate date filter instead of part of the search term."""
    m = _WHEN_RE.match(query)
    if m:
        term, window = _extract_time_window(m.group(1))
        if term:
            return {"mode": "when", "term": term, "window": window}
    m = _COUNT_RE.match(query)
    if m:
        term, window = _extract_time_window(m.group(1))
        if term:
            return {"mode": "count", "term": term, "window": window}
    return None


def memory_search_status_label(term: str) -> str:
    return f'Searching your conversation history for "{term}"…'


async def run_memory_search_intent(intent: dict, session_id: str) -> dict:
    """Routes to a literal cross-session search — no LLM call, no
    dependence on what happens to already be in this session's context,
    so the result is grounded in what was actually said, not a guess."""
    from storage.neon_store import get_store
    db = await get_store()
    matches = await db.search_conversations(intent["term"], window_seconds=intent.get("window"), limit=30)
    return {"term": intent["term"], "mode": intent["mode"], "matches": matches}


def _format_when(unix_seconds) -> str:
    dt = datetime.datetime.fromtimestamp(unix_seconds)
    diff = time.time() - unix_seconds
    if diff < 3600:
        rel = f"{max(1, int(diff // 60))}m ago"
    elif diff < 86400:
        rel = f"{int(diff // 3600)}h ago"
    else:
        rel = f"{int(diff // 86400)}d ago"
    return f'{dt.strftime("%b %d, %Y at %I:%M %p")} ({rel})'


def format_memory_search_result(result: dict) -> str:
    term = result["term"]
    matches = result["matches"]
    if not matches:
        return f'I couldn\'t find anything about "{term}" in any saved conversation.'

    if result["mode"] == "count":
        lines = [f'You\'ve mentioned "{term}" **{len(matches)}** time(s):', ""]
    else:
        lines = [f'Found {len(matches)} mention(s) of "{term}":', ""]

    for m in matches[:15]:
        when = _format_when(m["created_at"])
        label = m.get("title") or m["session_id"]
        role = "You" if m["role"] == "user" else "SEMBLANCE"
        snippet = (m["content"] or "")[:180].replace("\n", " ")
        lines.append(f'- **{when}** in "{label}" — {role}: {snippet}')
    return "\n".join(lines)
