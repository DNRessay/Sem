import re

from storage.embeddings import embed_text
from storage.neon_store import get_store
from tools.registry import get_registry

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_NEWS_RE = re.compile(
    r"\b(latest news|breaking news|news (?:on|about)|"
    r"what'?s (?:on|in) the news|any news (?:on|about))\b",
    re.I,
)
_SEARCH_RE = re.compile(
    # A bare "search" trigger, not just "search the web for"/"search the web"
    # literally — a phrasing like "search on the web who X is" or "can you
    # search who X is" has "search" nowhere near either fixed phrase and used
    # to fall through to no web intent at all, silently answering from
    # training knowledge with no search chip shown.
    r"\b(search|look up|google|"
    r"what'?s the latest|find (?:me )?(?:info|information) (?:on|about)|"
    r"what'?s the weather|weather (?:in|for|at|like)|weather forecast)\b",
    re.I,
)
# Strips the generic scaffolding around a news request ("what's on the
# latest news", "any breaking news today?") so what's left, if anything, is
# an actual topic — feeding the whole sentence to a news search returns
# stale/irrelevant results because it's matched too literally.
_NEWS_FILLER_RE = re.compile(
    r"\b(what'?s|on|in|the|any|breaking|latest|news|about|today|happening|for|me)\b",
    re.I,
)


def _news_topic(query: str) -> str:
    cleaned = _NEWS_FILLER_RE.sub("", query)
    cleaned = re.sub(r"[?!.]+", "", cleaned).strip()
    return cleaned if len(cleaned) >= 3 else "top stories"


def detect_web_intent(query: str) -> tuple[str, str] | None:
    """Deterministic, regex-only trigger — no LLM tool-calling involved, same
    reasoning as the skills system: Groq's function-calling reliability on
    the models this app runs isn't something to bet every message on.
    Checked in order of specificity: a URL wins over everything, then a news
    phrase (routes to the dedicated news tool, dated/sourced results) over a
    generic search phrase. Returns (kind, target) — kind is 'fetch', 'news',
    or 'search' — or None."""
    urls = _URL_RE.findall(query)
    if urls:
        return ("fetch", urls[0])
    if _NEWS_RE.search(query):
        return ("news", query)
    if _SEARCH_RE.search(query):
        return ("search", query)
    return None


def status_label(kind: str, target: str) -> str:
    if kind == "fetch":
        return f"Fetching {target}…"
    if kind == "news":
        return "Checking the latest news…"
    return "Searching the web…"


async def _personalized_topic(session_id: str) -> str | None:
    """Pulls one topic out of the user's own accumulated long-term memory
    (see Bootstrap.run, which now actually writes to it), so a generic news
    ask blends a personal angle in alongside top stories — the same idea as
    a personalized news feed mixing trending stories with things you've
    shown interest in. Returns None until enough memory exists to say
    anything — that's expected for a new/quiet session, not a bug; it grows
    as the user keeps chatting."""
    try:
        db = await get_store()
        embedding = await embed_text("topics and interests the user cares about")
        memories = await db.semantic_search(embedding, top_k=3)
    except Exception:
        return None
    if not memories:
        return None
    text = (memories[0].get("content") or "").strip()
    return text[:60] or None


async def _fetch_news(registry, topic: str) -> str:
    # Was calling the "web_news" tool (SerpTool.news, which takes a `query`
    # kwarg) with a {"topic": ...} dict — ToolsRegistry.execute's TypeError
    # fallback then called the handler with that whole dict as a single
    # positional arg, sending SerpAPI a garbled q={"topic": "..."} instead
    # of the actual topic string. That's why news answers came back
    # off-topic (a skating magazine, a stale timeline) rather than erroring
    # outright — the call "succeeded", just on garbage input. "news_tool"
    # (NewsTool.latest) is the tool actually registered to take `topic`.
    result = await registry.execute("news_tool", {"topic": topic})
    # ToolsRegistry.execute catches any exception the tool itself raises
    # (a SerpAPI quota/network failure, not just "no key configured") and
    # returns a plain {"error": ...} dict — NewsTool's own success/no-key
    # paths return a list instead, so indexing result[0] on that dict
    # crashed this whole request mid-stream with nothing surfaced to the
    # client. Anything that isn't the expected list shape is just "no news
    # this time", same as any other failure here.
    if not isinstance(result, list) or not result or result[0].get("error"):
        # One retry — a SerpAPI rate-limit/network hiccup is common enough
        # that the identical call succeeding a moment later is the normal
        # case, not "genuinely no news" (this exact pattern showed up live:
        # "what's the weather" failed once, then worked immediately on the
        # very next identical request).
        result = await registry.execute("news_tool", {"topic": topic})
        if not isinstance(result, list) or not result or result[0].get("error"):
            return ""
    lines = [f"- {r.get('title')} ({r.get('source')}, {r.get('date')}): {r.get('link')}" for r in result[:5]]
    return f'<web_news topic="{topic}">\n' + "\n".join(lines) + "\n</web_news>"


async def _fetch_search(registry, query: str) -> str:
    """One call (web_search_full) returns Google's direct answer box
    (weather, calculator, unit/currency conversion — a structured answer,
    not generative), its AI Overview (roughly half of queries don't get
    one), and the regular organic results — so a query like "what's the
    weather in Pretoria" gets an actual answer instead of "I don't have a
    weather tool", the same basic lookup a plain script could always do
    without any AI involved."""
    result = await registry.execute("web_search_full", {"query": query, "num": 5})
    if not result or result.get("error"):
        # One retry, same reasoning as _fetch_news above — a transient
        # upstream failure recovering on the very next identical call is
        # the common case here, not a real "no results."
        result = await registry.execute("web_search_full", {"query": query, "num": 5})
        if not result or result.get("error"):
            return ""
    blocks = []
    if result.get("answer_box"):
        blocks.append(f'<google_answer query="{query}">\n{result["answer_box"]}\n</google_answer>')
    if result.get("ai_overview"):
        blocks.append(f'<google_ai_overview query="{query}">\n{result["ai_overview"]}\n</google_ai_overview>')
    results = result.get("results") or []
    if results:
        lines = [f"- {r.get('title')}: {r.get('snippet')} ({r.get('link')})" for r in results]
        blocks.append("<web_search>\n" + "\n".join(lines) + "\n</web_search>")
    return "\n".join(blocks)


async def run_web_intent(kind: str, target: str, session_id: str | None = None) -> str:
    """Executes the intent via the existing tool registry and returns a
    context block to fold into the user's message — empty string on any
    failure (missing SERP_API_KEY, network error, etc), so a broken/unset
    web tool degrades to "no web context added", never a chat-breaking error."""
    registry = get_registry()

    if kind == "fetch":
        result = await registry.execute("web_fetch", {"url": target})
        if result.get("error"):
            return ""
        content = result.get("content", "")
        if not content:
            return ""
        return f'<web_fetch url="{target}">\n{content}\n</web_fetch>'

    if kind == "news":
        topic = _news_topic(target)
        topics = [topic]
        # Only blend in a personal angle for a fully generic ask — a query
        # that already names a topic ("news about load shedding") stays
        # exactly what was asked for, not padded with unrelated interests.
        if topic == "top stories" and session_id:
            personal = await _personalized_topic(session_id)
            if personal and personal.lower() != topic:
                topics.append(personal)
        blocks = [b for b in [await _fetch_news(registry, t) for t in topics] if b]
        return "\n".join(blocks)

    return await _fetch_search(registry, target)
