import httpx

from config import settings


class NewsTool:
    BASE = "https://serpapi.com/search"

    async def latest(self, topic: str = "technology", count: int = 5) -> list[dict]:
        if not settings.SERP_API_KEY:
            return [{"error": "SERP_API_KEY not set"}]
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(self.BASE, params={
                "q": topic, "tbm": "nws", "num": count,
                "api_key": settings.SERP_API_KEY, "output": "json",
            })
            return [
                {"title": n.get("title"), "link": n.get("link"),
                 "date": n.get("date"), "source": n.get("source")}
                for n in r.json().get("news_results", [])[:count]
            ]