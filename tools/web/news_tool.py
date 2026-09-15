import httpx

from config import settings


class NewsTool:
    BASE = "https://serpapi.com/search"

    async def latest(self, topic: str = "technology", count: int = 5) -> list[dict]:
        if not settings.SERP_API_KEY:
            return [{"error": "SERP_API_KEY not set"}]
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(self.BASE, params={
                    "q": topic, "tbm": "nws", "num": count,
                    "api_key": settings.SERP_API_KEY, "output": "json",
                })
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            return [{"error": str(exc)}]
        # A rate-limited/transient SerpAPI failure often comes back as HTTP
        # 200 with an `error` field in the body, not an exception — left
        # unchecked, that looked identical to "no news_results for this
        # topic" and silently produced an empty/irrelevant-feeling result
        # instead of something the caller could retry.
        if data.get("error"):
            return [{"error": data["error"]}]
        return [
            {"title": n.get("title"), "link": n.get("link"),
             "date": n.get("date"), "source": n.get("source")}
            for n in data.get("news_results", [])[:count]
        ]
