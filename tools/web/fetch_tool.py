import httpx


class FetchTool:
    async def fetch(self, url: str, timeout: int = 20) -> dict:
        if not url:
            return {"error": "No URL provided"}
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.get(url, headers={"User-Agent": "Semblance/9.0"})
                return {
                    "url": url,
                    "status": r.status_code,
                    "content": r.text[:50000],
                    "content_type": r.headers.get("content-type", ""),
                }
        except Exception as e:
            return {"error": str(e), "url": url}