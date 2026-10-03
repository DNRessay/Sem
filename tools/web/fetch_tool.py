import re
from html.parser import HTMLParser

import httpx

from tools.web.url_guard import BlockedURL, safe_get

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


_GOOGLE = re.compile(r"https://docs\.google\.com/(document|spreadsheets|presentation)/d/([\w-]+)")
_EXPORT = {"document": "txt", "spreadsheets": "csv", "presentation": "txt"}


def google_export_url(url: str) -> str:
    """A shared Google Doc/Sheet/Slides link → its plain-text export (works for "anyone with the link")."""
    m = _GOOGLE.match(url or "")
    if not m:
        return url
    kind, doc_id = m.groups()
    return f"https://docs.google.com/{kind}/d/{doc_id}/export?format={_EXPORT[kind]}"


class FetchTool:
    MAX_CHARS = 20_000

    async def fetch(self, url: str, timeout: int = 20) -> dict:
        if not url:
            return {"error": "No URL provided"}
        url = google_export_url(url)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await safe_get(client, url, headers={"User-Agent": "Semblance/1.0"})
        except BlockedURL as e:
            return {"error": f"Not fetched: {e}", "url": url}
        except Exception as e:
            return {"error": str(e), "url": url}

        content_type = r.headers.get("content-type", "")
        if "accounts.google.com" in str(r.url) and "docs.google.com" in url:
            return {"error": "That Google file is private — share it as \"Anyone with the link\" or upload it", "url": url}
        if "html" in content_type:
            parser = _TextExtractor()
            parser.feed(r.text)
            text = parser.text()
        elif content_type.startswith(("text/", "application/json", "application/xml")):
            text = r.text
        else:  # a linked PDF, Word file, spreadsheet, audio… read like an upload
            from tools import file_reader
            text, how = await file_reader.read_file(url.split("?")[0].rsplit("/", 1)[-1], content_type.split(";")[0], r.content)
            text = text or f"[{how}]"

        return {
            "url": url,
            "status": r.status_code,
            "content": text[: self.MAX_CHARS],
            "content_type": content_type,
        }
