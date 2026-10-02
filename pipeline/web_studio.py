"""Design → Web: logo concepts (Nano Banana), single-file web pages (any text model), and Figma frames as input."""
import base64
import re
from urllib.parse import parse_qs, urlsplit

import httpx

from pipeline import llm_providers
from tools.web.url_guard import BlockedURL, safe_get

LOGO_STYLES = [
    ("wordmark", "a wordmark logo: the name set in distinctive, custom-feeling typography, no separate icon"),
    ("icon", "a logo with a simple, memorable icon mark beside the name"),
    ("emblem", "an emblem/badge logo with the name inside the shape"),
    ("monogram", "a monogram logo built from the initials, with the full name small underneath"),
]

_PAGE = """You are a senior web designer and front-end developer.

Build: {request}
Business: {brief}{design}

Reply with ONE complete, self-contained HTML5 file and nothing else, starting with <!DOCTYPE html>:
- semantic HTML, mobile-first and responsive, all CSS in a single <style> tag (CSS variables for the palette)
- no frameworks or external scripts; a few lines of inline JS only if needed (e.g. a mobile menu)
- no external images: use inline SVG, CSS gradients/shapes or clearly marked photo placeholders
- Google Fonts via <link> is fine
- accessible: landmarks, alt text, labels, good contrast, visible focus styles
- real, specific copy for this business (South African English and Rand if it's in South Africa); no lorem ipsum"""

_EDIT = """You are a senior front-end developer. Change this page as asked and reply with the COMPLETE updated HTML file
only (starting with <!DOCTYPE html>), keeping everything else as it is.

Change: {request}{design}

Current page:
{html}"""


def logo_prompt(name: str, brief: str, style: str, notes: str = "") -> str:
    desc = dict(LOGO_STYLES).get(style, LOGO_STYLES[0][1])
    return (f'Design {desc} for the business "{name}". About the business: {brief[:600]}. '
            f"{notes[:300] + '. ' if notes else ''}"
            "Flat vector logo, centred on a plain white background, crisp edges, 2-3 brand colours at most, "
            "spelled exactly as given, no mockup, no photo, no extra text.")


def extract_html(text: str) -> str:
    text = re.sub(r"<think>.*?(</think>|$)", "", text or "", flags=re.S)
    text = re.sub(r"```(?:html)?", "", text)
    start = min([i for i in (text.lower().find("<!doctype"), text.lower().find("<html")) if i != -1], default=-1)
    end = text.lower().rfind("</html>")
    if start == -1 or end == -1 or end < start:
        return ""
    return text[start:end + len("</html>")].strip()


def _page_models(choice: str) -> list[str]:
    """A page needs thousands of output tokens: Auto goes to the free model that allows the most first."""
    if choice != "auto":
        return [choice]
    order = ("gemini", "bonsai", "groq")
    return [p for p in order if llm_providers.PROVIDERS[p].configured] or ["auto"]


async def make_page(brief: str, request: str, model: str = "auto", design: str = "", current: str = "") -> dict:
    design_text = f"\n\nFollow this design closely (from the user's Figma/screens):\n{design[:4000]}" if design else ""
    if current:
        prompt = _EDIT.format(request=request.strip()[:1500], design=design_text, html=current[:60000])
    else:
        prompt = _PAGE.format(request=request.strip()[:1500], brief=brief.strip()[:2000] or "(not given)", design=design_text)
    last = "No model answered"
    for choice in _page_models(model):
        result = await llm_providers.complete(choice, [{"role": "user", "content": prompt}], max_tokens=16000)
        if "error" in result:
            last = result["error"]
            continue
        html = extract_html(result.get("content") or "")
        if html:
            return {"ok": True, "html": html, "model": result.get("_provider", choice)}
        last = ("The model's reply was cut off or wasn't a web page — pick Gemini or a bigger model"
                if "<html" in (result.get("content") or "").lower() else "The model didn't return a web page — try again")
    return {"ok": False, "error": last}


# ── Figma ──────────────────────────────────────────────────────────────────

FIGMA_API = "https://api.figma.com/v1"
_FIGMA_URL = re.compile(r"figma\.com/(?:file|design|proto|board)/([A-Za-z0-9]{10,})")
MAX_FRAMES = 4


def figma_target(url: str) -> tuple[str, str]:
    """(file key, node id or "") from a Figma link; node-id=1-2 in links is 1:2 in the API."""
    m = _FIGMA_URL.search(url or "")
    if not m:
        return "", ""
    node = (parse_qs(urlsplit(url).query).get("node-id") or [""])[0].replace("-", ":")
    return m.group(1), node


async def figma_me(token: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{FIGMA_API}/me", headers={"X-Figma-Token": token})
    return r.json() if r.status_code == 200 else {}


async def figma_frames(token: str, url: str) -> dict:
    """Renders the linked frame (or the first page's top frames) to PNG. Returns {ok, frames: [{name, mime, base64}]}."""
    key, node = figma_target(url)
    if not key:
        return {"ok": False, "error": "That isn't a Figma file link (figma.com/design/…)"}
    headers = {"X-Figma-Token": token}
    async with httpx.AsyncClient(timeout=60) as c:
        names = {}
        if node:
            names[node] = "Selected frame"
        else:
            r = await c.get(f"{FIGMA_API}/files/{key}", params={"depth": 2}, headers=headers)
            if r.status_code != 200:
                return {"ok": False, "error": f"Figma said {r.status_code}: {r.text[:200]} — check the link and that your token can open it"}
            pages = (r.json().get("document") or {}).get("children") or []
            for child in (pages[0].get("children") or []) if pages else []:
                if child.get("type") in ("FRAME", "COMPONENT", "SECTION", "COMPONENT_SET") and len(names) < MAX_FRAMES:
                    names[child["id"]] = child.get("name") or "Frame"
            if not names:
                return {"ok": False, "error": "No frames on the first page — link a specific frame (right-click → Copy link)"}
        r = await c.get(f"{FIGMA_API}/images/{key}", params={"ids": ",".join(names), "format": "png", "scale": 1},
                        headers=headers)
        if r.status_code != 200:
            return {"ok": False, "error": f"Figma couldn't render the frames ({r.status_code}): {r.text[:200]}"}
        frames = []
        for node_id, image_url in (r.json().get("images") or {}).items():
            if not image_url:
                continue
            try:
                img = await safe_get(c, image_url)
            except (BlockedURL, httpx.HTTPError):
                continue
            if img.status_code == 200 and len(img.content) <= 7_000_000:
                frames.append({"name": names.get(node_id, "Frame"), "mime": "image/png",
                               "base64": base64.b64encode(img.content).decode()})
    if not frames:
        return {"ok": False, "error": "Figma returned no images for that link"}
    return {"ok": True, "frames": frames}
