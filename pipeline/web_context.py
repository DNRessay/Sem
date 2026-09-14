import re

from tools.registry import get_registry

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_NEWS_RE = re.compile(
    r"\b(latest news|breaking news|news (?:on|about)|"
    r"what'?s (?:on|in) the news|any news (?:on|about))\b",
    re.I,
)
_SEARCH_RE = re.compile(
    r"\b(search (?:the web )?for|search the web|look up|google|"
    r"what'?s the latest|find (?:me )?(?:info|information) (?:on|about))\b",
    re.I,
)


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


async def run_web_intent(kind: str, target: str) -> str:
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
        result = await registry.execute("web_news", {"topic": target})
        if not result or result[0].get("error"):
            return ""
        lines = [f"- {r.get('title')} ({r.get('source')}, {r.get('date')}): {r.get('link')}" for r in result]
        return "<web_news>\n" + "\n".join(lines) + "\n</web_news>"

    result = await registry.execute("web_search", {"query": target, "num": 5})
    if not result or result[0].get("error"):
        return ""
    lines = [f"- {r.get('title')}: {r.get('snippet')} ({r.get('link')})" for r in result]
    return "<web_search>\n" + "\n".join(lines) + "\n</web_search>"
