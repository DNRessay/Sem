import httpx

from config import settings
from tools.web.serp_tool import SerpTool


async def web_search(query: str, num: int = 5) -> dict:
    """{"ok", "engine", "results": [{"title", "url", "snippet"}]} — from the
    self-hosted SearXNG when SEARXNG_URL is set (no quota), else SerpAPI."""
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
    if not settings.SERP_API_KEY:
        return {"ok": False, "error": "No search engine configured — set SEARXNG_URL or SERP_API_KEY"}
    hits = await SerpTool().search(query, num=num)
    if hits and hits[0].get("error"):
        return {"ok": False, "error": hits[0]["error"]}
    return {"ok": True, "engine": "serpapi",
            "results": [{"title": h.get("title"), "url": h.get("link"), "snippet": h.get("snippet")} for h in hits]}
