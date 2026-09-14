import re
from html.parser import HTMLParser

import httpx

_SKIP_TAGS = {"script", "style", "noscript", "svg"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self._parts))


class FetchTool:
    MAX_CHARS = 20_000

    async def fetch(self, url: str, timeout: int = 20) -> dict:
        if not url:
            return {"error": "No URL provided"}
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.get(url, headers={"User-Agent": "Semblance/9.0"})
        except Exception as e:
            return {"error": str(e), "url": url}

        content_type = r.headers.get("content-type", "")
        if "html" in content_type:
            parser = _TextExtractor()
            parser.feed(r.text)
            text = parser.text()
        else:
            text = r.text

        return {
            "url": url,
            "status": r.status_code,
            "content": text[: self.MAX_CHARS],
            "content_type": content_type,
        }
