import asyncio
import re
from urllib.parse import urljoin, urlparse

import httpx

from pipeline import llm_providers
from tools.web.fetch_tool import _TextExtractor

_KEY_PAGES = re.compile(r"about|service|product|pricing|price|menu|shop|store|contact|team|work|portfolio|offer", re.I)
_MAX_PAGES = 5
_PAGE_CHARS = 4000

_PROMPT = """Below is text from a business's website ({url}). Write the brief a marketer needs before making ads
for it. Use only what the site supports; write "unknown" rather than guessing.

Format exactly:
Business: name — one line on what they do
Sells: main products/services (with prices if shown)
Audience: who they serve
Location: where they operate / deliver
Tone: how the brand talks
Strengths: what makes them stand out (USPs, proof such as reviews or years in business)
Current offers: any promotions on the site
Brand colours: from the theme colours listed, if any
Website gaps: 2-3 quick wins for their online visibility (SEO/meta, calls to action, contact details, speed)

--- SITE ---
{pages}"""


def _meta(html: str) -> dict:
    def find(pattern):
        m = re.search(pattern, html, re.I | re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    colours = sorted(set(re.findall(r"#[0-9a-fA-F]{6}\b", html)), key=lambda c: -html.count(c))[:6]
    return {
        "title": find(r"<title[^>]*>(.*?)</title>"),
        "description": find(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']'),
        "theme_color": find(r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\'](.*?)["\']'),
        "colours": colours,
    }


def _text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def _internal_links(base: str, html: str) -> list[str]:
    host = urlparse(base).netloc
    seen, out = set(), []
    for href in re.findall(r'href=["\']([^"\'#]+)["\']', html, re.I):
        url = urljoin(base, href)
        parsed = urlparse(url)
        if parsed.netloc != host or parsed.scheme not in ("http", "https") or url in seen:
            continue
        seen.add(url)
        if _KEY_PAGES.search(parsed.path):
            out.append(url)
    return out[: _MAX_PAGES - 1]


async def _get(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Semblance site reader)"})
        return r.text if r.status_code == 200 and "html" in r.headers.get("content-type", "") else ""
    except httpx.HTTPError:
        return ""


async def learn_site(url: str, model: str = "auto") -> dict:
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "url required"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        home = await _get(client, url)
        if not home:
            return {"ok": False, "error": f"Couldn't read {url} — check the address is public"}
        links = _internal_links(url, home)
        others = await asyncio.gather(*[_get(client, link) for link in links])

    meta = _meta(home)
    sections = [f"[Home] {url}\nTitle: {meta['title']}\nMeta description: {meta['description'] or '(none)'}\n"
                f"Theme colours: {', '.join(filter(None, [meta['theme_color'], *meta['colours']])) or '(none found)'}\n"
                + _text(home)[:_PAGE_CHARS]]
    sections += [f"[Page] {link}\n" + _text(html)[:_PAGE_CHARS] for link, html in zip(links, others) if html]

    result = await llm_providers.complete(
        model, [{"role": "user", "content": _PROMPT.format(url=url, pages="\n\n".join(sections))}], max_tokens=2048,
    )
    if "error" in result:
        return {"ok": False, "error": result["error"]}
    return {"ok": True, "url": url, "pages_read": 1 + sum(1 for h in others if h), "brief": (result.get("content") or "").strip(),
            "meta": meta}
