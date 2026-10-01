from datetime import datetime, timedelta, timezone

from agents.cowork_agent import TOOLS as COWORK_TOOLS
from agents.tool_loop import ToolLoopAgent
from config import settings
from storage.neon_store import get_store
from tools.web.fetch_tool import FetchTool
from tools.web.search import web_search

_SAST = timezone(timedelta(hours=2))

_SYSTEM = """You are SEMBLANCE in deep research mode. It is {now} (South Africa time).
Research the user's question properly before answering:
- Run several web_search queries from different angles, then fetch_url the most relevant, most authoritative sources.
- Cross-check important facts across sources; note disagreements and how recent each source is.
- Stop searching when more sources stop changing the answer (usually 3-8 pages read).
Then write the answer: a direct conclusion first, then the supporting detail, then a "Sources" list of markdown links
to the pages you actually read. Cite inline like [1]. Say plainly what you couldn't verify."""

_TOOLS = ("web_search", "fetch_url", "search_memory")


class ResearchAgent(ToolLoopAgent):
    """Chat's "Deep research" toggle: search, read, cross-check, then a cited answer."""

    def __init__(self, provider: str = "auto", max_steps: int | None = None, deadline_seconds: float | None = None):
        super().__init__(provider, max_steps or settings.RESEARCH_MAX_STEPS,
                         deadline_seconds or settings.RESEARCH_TIMEOUT_SECONDS)
        self.allow_handoff = False  # research answers in place; it has no tab to hand off from

    def system_prompt(self) -> str:
        return _SYSTEM.format(now=datetime.now(_SAST).strftime("%A %d %B %Y, %H:%M"))

    def tools(self) -> list[dict]:
        return [COWORK_TOOLS[n] for n in _TOOLS]

    async def dispatch(self, name: str, args: dict) -> dict:
        if name == "web_search":
            return await web_search(args.get("query", ""), num=6)
        if name == "fetch_url":
            return await FetchTool().fetch(args.get("url", ""))
        if name == "search_memory":
            db = await get_store()
            return {"matches": await db.search_conversations(args.get("term", ""), limit=20)}
        return {"ok": False, "error": f"unknown tool {name}"}
