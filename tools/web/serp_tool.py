import httpx

from config import settings


def _extract_answer_box(raw: dict | None) -> str | None:
    """Google's long-standing "answer box" (weather, calculator, currency
    and unit conversion, dictionary, sports scores...) — a direct
    structured answer, not the newer generative AI Overview. Shape varies
    a lot by type, so this only handles the common cases rather than every
    possible one: a plain `answer` field (most conversions/calculators), a
    `snippet` (generic featured-snippet style box), or the weather type's
    own temperature/location/weather fields."""
    if not raw:
        return None
    if raw.get("type") == "weather_result":
        temp = raw.get("temperature")
        unit = raw.get("unit") or ""
        weather = raw.get("weather")
        location = raw.get("location")
        parts = []
        if temp is not None:
            parts.append(f"{temp}°{unit}")
        if weather:
            parts.append(weather)
        if location:
            parts.append(f"in {location}")
        return " ".join(parts) if parts else None
    for key in ("answer", "snippet", "result"):
        if raw.get(key):
            return str(raw[key])
    return None


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

    async def search_full(self, query: str, num: int = 5) -> dict:
        """Like search(), but also returns Google's own AI Overview when
        Google shows one for this query (roughly half don't get one) — it
        rides in the *same* SerpAPI response as organic_results, so this is
        one search's worth of quota, not two, despite returning both. If
        Google truncates the overview behind a page_token (an expanded
        second-page fetch), that's skipped rather than silently spending a
        second call — ai_overview just comes back None in that case."""
        if not settings.SERP_API_KEY:
            return {"error": "SERP_API_KEY not set"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(self.BASE, params={
                "q": query, "api_key": settings.SERP_API_KEY,
                "num": num, "output": "json",
            })
            data = r.json()

        results = [
            {"title": o.get("title"), "link": o.get("link"), "snippet": o.get("snippet")}
            for o in data.get("organic_results", [])
        ]
        blocks = (data.get("ai_overview") or {}).get("text_blocks") or []
        text = "\n".join(b["snippet"] for b in blocks if b.get("snippet"))
        return {
            "results": results,
            "ai_overview": text or None,
            "answer_box": _extract_answer_box(data.get("answer_box")),
        }

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
