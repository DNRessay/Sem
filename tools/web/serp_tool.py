import httpx

from config import settings


class SerpTool:
    BASE = "https://serpapi.com/search"

    async def search(self, query: str, num: int = 5) -> list[dict]:
        if not settings.SERP_API_KEY:
            return [{"error": "SERP_API_KEY not set"}]
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(self.BASE, params={
                "q": query, "api_key": settings.SERP_API_KEY,
                "num": num, "output": "json",
            })
            data = r.json()
            return [
                {"title": r.get("title"), "link": r.get("link"), "snippet": r.get("snippet")}
                for r in data.get("organic_results", [])
            ]

    async def news(self, query: str) -> list[dict]:
        if not settings.SERP_API_KEY:
            return []
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(self.BASE, params={
                "q": query, "api_key": settings.SERP_API_KEY,
                "tbm": "nws", "output": "json",
            })
            data = r.json()
            return [
                {"title": r.get("title"), "link": r.get("link"), "date": r.get("date")}
                for r in data.get("news_results", [])
            ]
