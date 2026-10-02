import base64
import json

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from gateway.auth import require_account
from main import app
from pipeline import llm_providers, web_studio


def _events(r):
    return [json.loads(ln[6:]) for ln in r.text.split("\n") if ln.startswith("data: {")]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("config.settings.MEDIA_BUCKET", "")
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app)
    app.dependency_overrides.pop(require_account, None)


def test_extract_html_strips_reasoning_and_fences():
    reply = "<think>plan</think>Sure!\n```html\n<!DOCTYPE html><html><body>Hi</body></html>\n```\nEnjoy"
    assert web_studio.extract_html(reply) == "<!DOCTYPE html><html><body>Hi</body></html>"
    assert web_studio.extract_html("<!DOCTYPE html><html><body>cut off") == ""


def test_figma_links():
    assert web_studio.figma_target("https://www.figma.com/design/AbC123xyz0/Shop?node-id=12-34&t=x") == ("AbC123xyz0", "12:34")
    assert web_studio.figma_target("https://figma.com/file/AbC123xyz0/Shop") == ("AbC123xyz0", "")
    assert web_studio.figma_target("https://example.com/design/x") == ("", "")


def test_logo_prompt_keeps_the_name_and_style():
    p = web_studio.logo_prompt("Mama's Kitchen", "Soweto takeaway", "monogram")
    assert '"Mama\'s Kitchen"' in p and "monogram" in p and "white background" in p


def test_logos_stream_one_per_style(client, monkeypatch):
    prompts = []

    async def fake_image(prompt, aspect_ratio="1:1", references=None):
        prompts.append(prompt)
        if "emblem" in prompt:
            return {"ok": False, "error": "blocked"}
        return {"ok": True, "mime": "image/png", "base64": "QUJD"}

    monkeypatch.setattr("gateway.design_router.image_gen.generate_image", fake_image)
    assert client.post("/design/logos", json={"name": " "}).status_code == 400
    r = client.post("/design/logos", json={"name": "Vicinic", "brief": "web studio", "styles": ["wordmark", "emblem", "nope"]})
    ev = [e for e in _events(r) if e["type"] != "status"]
    assert [e["type"] for e in ev] == ["logo", "logo_error"] and ev[0]["base64"] == "QUJD" and ev[1]["style"] == "emblem"
    assert len(prompts) == 2


def test_page_stream_and_refine(client, monkeypatch):
    seen = []

    async def fake_make(brief, request, model="auto", design="", current=""):
        seen.append((request, design, current))
        return {"ok": True, "html": "<!DOCTYPE html><html></html>", "model": "gemini"}

    monkeypatch.setattr("gateway.design_router.make_page", fake_make)
    assert client.post("/design/page", json={"request": ""}).status_code == 400
    page = [e for e in _events(client.post("/design/page", json={"request": "landing page", "design": "notes"})) if e["type"] == "page"]
    assert page[0]["html"].startswith("<!DOCTYPE") and seen[0] == ("landing page", "notes", "")
    client.post("/design/page", json={"request": "dark header", "html": "<html>old</html>"})
    assert seen[1][2] == "<html>old</html>"


async def test_pages_prefer_the_free_model_with_room_and_skip_cut_off_replies(monkeypatch):
    asked = []

    async def fake_complete(choice, messages, tools=None, max_tokens=4096, **k):
        asked.append(choice)
        if choice == "gemini":
            return {"content": "<!DOCTYPE html><html><body>cut", "_provider": "gemini"}
        return {"content": "<!DOCTYPE html><html><body>ok</body></html>", "_provider": choice}

    for pid in ("bonsai", "gemini", "groq"):
        monkeypatch.setattr(llm_providers.PROVIDERS[pid].__class__, "configured", property(lambda self: True))
    monkeypatch.setattr(web_studio.llm_providers, "complete", fake_complete)
    result = await web_studio.make_page("bakery", "landing page")
    assert result["ok"] and result["model"] == "bonsai" and asked == ["gemini", "bonsai"]


class Store:
    def __init__(self):
        self.connectors = {}

    async def get_connector(self, account_id, provider):
        token = self.connectors.get(provider)
        return {"provider": provider, "token": token} if token else None

    async def upsert_connector(self, account_id, provider, token, refresh_token=None, expires_at=None):
        self.connectors[provider] = token


def test_figma_connect_and_import(client, monkeypatch):
    store = Store()

    async def fake_store():
        return store

    async def fake_describe(frames):
        return {"ok": True, "text": f"{len(frames)} screen(s): hero, menu"}

    async def no_check(url):
        return None

    monkeypatch.setattr("gateway.design_router.get_store", fake_store)
    monkeypatch.setattr("gateway.design_router.gemini_media.describe_design", fake_describe)
    monkeypatch.setattr("tools.web.url_guard.check_url", no_check)
    assert client.post("/design/figma/import", json={"url": "https://figma.com/design/AbC123xyz0/x"}).status_code == 400
    png = b"\x89PNG fake"
    with respx.mock:
        respx.get("https://api.figma.com/v1/me").mock(side_effect=lambda req: Response(200, json={"handle": "roy"})
                                                      if req.headers.get("x-figma-token") == "figd_ok" else Response(403))
        assert client.post("/design/figma/connect", json={"token": "bad"}).status_code == 400
        assert client.post("/design/figma/connect", json={"token": "figd_ok"}).json() == {"connected": True, "handle": "roy"}
        respx.get("https://api.figma.com/v1/files/AbC123xyz0").mock(return_value=Response(200, json={"document": {"children": [
            {"children": [{"id": "1:2", "type": "FRAME", "name": "Home"}, {"id": "1:3", "type": "TEXT", "name": "x"}]}]}}))
        respx.get("https://api.figma.com/v1/images/AbC123xyz0").mock(return_value=Response(200, json={"images": {"1:2": "https://cdn.figma.example/a.png"}}))
        respx.get("https://cdn.figma.example/a.png").mock(return_value=Response(200, content=png))
        r = client.post("/design/figma/import", json={"url": "https://www.figma.com/design/AbC123xyz0/Shop"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["notes"] == "1 screen(s): hero, menu" and d["frames"][0]["name"] == "Home"
    assert base64.b64decode(d["frames"][0]["base64"]) == png
    assert client.get("/design/figma").json() == {"connected": True}
