import json

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from gateway.auth import require_account
from main import app
from pipeline import ad_studio, site_brief

HOME = """<html><head><title>Vicinic Bakes</title><meta name="description" content="Fresh bread in Soweto">
<meta name="theme-color" content="#c0392b"></head><body><h1>Vicinic Bakes</h1>
<a href="/about-us">About</a><a href="/menu">Menu</a><a href="https://facebook.com/x">FB</a><a href="/blog/post-1">Blog</a>
<p>Sourdough from R45.</p><style>.a{color:#c0392b}</style></body></html>"""


def test_parse_variants_keeps_valid_items_and_sets_aspect_ratio():
    text = 'Sure! [{"placement": "story_reel", "headline": "H", "image_prompt": "bread", "hashtags": ["#a", 3]},' \
           ' {"placement": "billboard", "image_prompt": "x"}, {"placement": "square"}]'
    variants = ad_studio.parse_variants(text)
    assert len(variants) == 1
    assert variants[0]["aspect_ratio"] == "9:16" and variants[0]["hashtags"] == ["#a"]


def test_parse_variants_survives_garbage():
    assert ad_studio.parse_variants("no json here") == []
    assert ad_studio.parse_variants("[not json]") == []


def test_site_links_only_follow_key_pages_on_the_same_host():
    links = site_brief._internal_links("https://vicinic.co.za/", HOME)
    assert links == ["https://vicinic.co.za/about-us", "https://vicinic.co.za/menu"]


def test_site_meta_finds_title_description_and_colours():
    meta = site_brief._meta(HOME)
    assert meta["title"] == "Vicinic Bakes" and meta["description"] == "Fresh bread in Soweto"
    assert meta["theme_color"] == "#c0392b" and "#c0392b" in meta["colours"]


@pytest.mark.asyncio
async def test_learn_site_reads_pages_and_asks_the_model(monkeypatch):
    seen = {}

    async def fake_complete(model, messages, **kw):
        seen["prompt"] = messages[0]["content"]
        return {"content": "Business: Vicinic Bakes — bakery"}

    monkeypatch.setattr("pipeline.site_brief.llm_providers.complete", fake_complete)
    with respx.mock:
        respx.get("https://vicinic.co.za/about-us").mock(return_value=Response(200, text="<p>Since 2009</p>", headers={"content-type": "text/html"}))
        respx.get("https://vicinic.co.za/menu").mock(return_value=Response(404))
        respx.get(url__regex=r"^https://vicinic\.co\.za/?$").mock(return_value=Response(200, text=HOME, headers={"content-type": "text/html"}))
        result = await site_brief.learn_site("vicinic.co.za")
    assert result["ok"] and result["pages_read"] == 2 and result["brief"].startswith("Business:")
    assert "Sourdough from R45" in seen["prompt"] and "Since 2009" in seen["prompt"] and "#c0392b" in seen["prompt"]


@pytest.fixture
def client():
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app)
    app.dependency_overrides.pop(require_account, None)


def test_ads_stream_sends_copy_then_images(client, monkeypatch):
    async def fake_write(brief, campaign, placements, count, model, style=""):
        return {"ok": True, "variants": [
            {"placement": "square", "headline": "A", "image_prompt": "a", "aspect_ratio": "1:1"},
            {"placement": "story_reel", "headline": "B", "image_prompt": "b", "aspect_ratio": "9:16"},
        ]}

    async def fake_image(prompt, aspect_ratio="1:1", references=None):
        if prompt == "b":
            return {"ok": False, "error": "blocked"}
        return {"ok": True, "mime": "image/png", "base64": "QUJD"}

    monkeypatch.setattr("gateway.design_router.write_variants", fake_write)
    monkeypatch.setattr("gateway.design_router.gemini_media.generate_image", fake_image)
    r = client.post("/design/ads", json={"brief": "bakery", "campaign": "weekend special"})
    events = [json.loads(line[6:]) for line in r.text.split("\n") if line.startswith("data: {")]
    assert [e["type"] for e in events] == ["variants", "image", "image_error"]
    assert events[1]["index"] == 0 and events[2]["index"] == 1


def test_ads_require_brief_and_campaign(client):
    assert client.post("/design/ads", json={"brief": "x"}).status_code == 400


def test_video_without_modal_is_a_clear_error(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "MODAL_VIDEO_URL", "")
    r = client.post("/design/video", json={"prompt": "bread rising"})
    assert r.status_code == 400 and "modal_app/video.py" in r.json()["detail"]


def test_inspiration_images_shape_the_copy_and_the_images(client, monkeypatch):
    seen = {}

    async def fake_describe(refs):
        seen["described"] = len(refs)
        return {"ok": True, "text": "warm terracotta palette, hand-drawn type"}

    async def fake_write(brief, campaign, placements, count, model, style=""):
        seen["style"] = style
        return {"ok": True, "variants": [{"placement": "square", "headline": "A", "image_prompt": "a", "aspect_ratio": "1:1"}]}

    async def fake_image(prompt, aspect_ratio="1:1", references=None):
        seen["refs"] = len(references or [])
        return {"ok": True, "mime": "image/png", "base64": "QUJD"}

    monkeypatch.setattr("gateway.design_router.gemini_media.describe_style", fake_describe)
    monkeypatch.setattr("gateway.design_router.write_variants", fake_write)
    monkeypatch.setattr("gateway.design_router.gemini_media.generate_image", fake_image)
    refs = [{"mime": "image/jpeg", "base64": "QUJD"}] * 6 + [{"mime": "text/html", "base64": "x"}]
    r = client.post("/design/ads", json={"brief": "bakery", "campaign": "weekend", "references": refs})
    types = [json.loads(line[6:])["type"] for line in r.text.split("\n") if line.startswith("data: {")]
    assert types == ["status", "style", "variants", "image"]
    assert seen == {"described": 4, "style": "warm terracotta palette, hand-drawn type", "refs": 4}


def test_vicinic_site_brief_comes_over_mcp(client, monkeypatch):
    class Store:
        async def list_mcp_servers(self, account_id):
            return [{"name": "vicinic", "url": "https://vic.example/mcp", "auth": "vic_k"}]

    async def fake_store():
        return Store()

    calls = []

    class FakeClient:
        def __init__(self, url, auth, timeout=0):
            calls.append((url, auth))

        async def call_tool(self, name, args):
            if name == "sites":
                return {"ok": True, "text": json.dumps([{"slug": "bakes", "name": "Vicinic Bakes"}]), "images": []}
            return {"ok": True, "text": json.dumps({"slug": args["slug"], "brief": "Business: Vicinic Bakes"}), "images": []}

    monkeypatch.setattr("gateway.design_router.get_store", fake_store)
    monkeypatch.setattr("gateway.design_router.MCPClient", FakeClient)
    assert client.get("/design/vicinic/sites").json() == {"connected": True, "sites": [{"slug": "bakes", "name": "Vicinic Bakes"}]}
    assert client.get("/design/vicinic/brief/bakes").json()["brief"] == "Business: Vicinic Bakes"
    assert calls[0] == ("https://vic.example/mcp", "vic_k")
