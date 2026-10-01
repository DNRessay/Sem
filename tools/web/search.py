import asyncio

import httpx

from config import settings
from tools.web.serp_tool import SerpTool


async def web_search(query: str, num: int = 5) -> dict:
    """{"ok", "engine", "results": [{"title", "url", "snippet"}]}. Tries a
    self-hosted SearXNG (SEARXNG_URL, no quota), then SerpAPI (100/month
    free), then the keyless ddgs package."""
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "query required"}
    if settings.SEARXNG_URL:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(settings.SEARXNG_URL.rstrip("/") + "/search",
                                     params={"q": query, "format": "json"})
            if r.status_code == 200:
                results = [
                    {"title": x.get("title"), "url": x.get("url"), "snippet": (x.get("content") or "")[:300]}
                    for x in r.json().get("results", [])[:num]
                ]
                return {"ok": True, "engine": "searxng", "results": results}
        except (httpx.HTTPError, ValueError):
            pass  # fall through to SerpAPI rather than failing the search outright
    if settings.SERP_API_KEY:
        hits = await SerpTool().search(query, num=num)
        if hits and not hits[0].get("error"):
            return {"ok": True, "engine": "serpapi",
                    "results": [{"title": h.get("title"), "url": h.get("link"), "snippet": h.get("snippet")} for h in hits]}
    return await _ddgs(query, num)


async def _ddgs(query: str, num: int) -> dict:
    """Open-source, keyless metasearch (the ddgs package) — the zero-setup
    fallback once SearXNG isn't set up and SerpAPI's monthly quota is gone."""
    try:
        from ddgs import DDGS
        hits = await asyncio.to_thread(lambda: DDGS().text(query, max_results=num))
    except Exception as e:  # network blocks/rate limits surface as varied exception types
        return {"ok": False, "error": f"web search failed: {str(e)[:200]}"}
    return {"ok": True, "engine": "ddgs",
            "results": [{"title": h.get("title"), "url": h.get("href"), "snippet": (h.get("body") or "")[:300]} for h in hits]}
