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


@pytest.fixture(autouse=True)
def no_prompt_extension(monkeypatch):
    async def same(prompt, aspect, brief="", model="auto"):
        return prompt

    monkeypatch.setattr("gateway.design_router.extend_prompt", same)


@pytest.fixture
def client():
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app)
    app.dependency_overrides.pop(require_account, None)


def test_ads_stream_sends_copy_then_images(client, monkeypatch):
    async def fake_write(brief, campaign, placements, count, model, style="", area=""):
        return {"ok": True, "variants": [
            {"placement": "square", "headline": "A", "image_prompt": "a", "aspect_ratio": "1:1"},
            {"placement": "story_reel", "headline": "B", "image_prompt": "b", "aspect_ratio": "9:16"},
        ]}

    async def fake_image(prompt, aspect_ratio="1:1", references=None):
        if prompt == "b":
            return {"ok": False, "error": "blocked"}
        return {"ok": True, "mime": "image/png", "base64": "QUJD"}

    monkeypatch.setattr("gateway.design_router.write_variants", fake_write)
    monkeypatch.setattr("gateway.design_router.image_gen.generate_image", fake_image)
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

    async def fake_write(brief, campaign, placements, count, model, style="", area=""):
        seen["style"] = style
        return {"ok": True, "variants": [{"placement": "square", "headline": "A", "image_prompt": "a", "aspect_ratio": "1:1"}]}

    async def fake_image(prompt, aspect_ratio="1:1", references=None):
        seen["refs"] = len(references or [])
        return {"ok": True, "mime": "image/png", "base64": "QUJD"}

    monkeypatch.setattr("gateway.design_router.gemini_media.describe_style", fake_describe)
    monkeypatch.setattr("gateway.design_router.write_variants", fake_write)
    monkeypatch.setattr("gateway.design_router.image_gen.generate_image", fake_image)
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


def test_finished_video_is_saved_to_s3_and_listed_in_history(client, monkeypatch, moto_cache_table):
    calls = []

    async def fake_video(action, **kw):
        calls.append(action)
        if action == "submit":
            return {"ok": True, "job_id": "fc-1", "used_usd": 0, "cap_usd": 10}
        return {"ok": True, "status": "done", "mime": "video/mp4", "base64": "QUJD", "gpu_seconds": 600}

    async def fake_save(data, mime, kind):
        return "https://api/media/file/video/x.mp4"

    monkeypatch.setattr("gateway.design_router.video_call", fake_video)
    monkeypatch.setattr("gateway.design_router.media_store.save", fake_save)
    assert client.post("/design/video", json={"prompt": "bread rising", "chat_id": "c1"}).json()["job_id"] == "fc-1"
    assert client.get("/design/videos").json()["videos"][0]["status"] == "rendering"
    done = client.get("/design/video/fc-1").json()
    assert done["url"].endswith("x.mp4") and "base64" not in done
    assert client.get("/design/video/fc-1").json() == done and calls.count("status") == 1  # remembered
    listed = client.get("/design/videos").json()["videos"]
    assert [(v["job_id"], v["prompt"], v["chat_id"], v["url"]) for v in listed] == [("fc-1", "bread rising", "c1", done["url"])]


def test_storyboard_has_one_scene_per_five_seconds(client, monkeypatch):
    from pipeline import video_studio

    seen = {}

    async def fake_complete(model, messages, **kw):
        seen["prompt"] = messages[0]["content"]
        return {"content": '```json\n{"title": "Bread", "style": "warm light", "scenes": [{"prompt": "dough", "narration": "Fresh"},'
                           ' {"prompt": "oven", "narration": "Hot"},]}\n```'}

    monkeypatch.setattr(video_studio.llm_providers, "complete", fake_complete)
    plan = client.post("/design/video/plan", json={"idea": "bread reel", "seconds": 15, "format": "short",
                                                   "voiceover": True, "brief": "Vicinic Bakes"}).json()
    assert plan["aspect_ratio"] == "9:16" and plan["estimate"] == {"scenes": 3, "minutes": 30, "usd": 0.39}
    assert [s["prompt"] for s in plan["scenes"]] == ["dough", "oven", "oven"]  # too few: the last shot is held
    assert "exactly 3 scenes" in seen["prompt"] and "voiceover line" in seen["prompt"]
    assert video_studio.estimate(60) == {"scenes": 12, "minutes": 120, "usd": 1.56}
    assert client.post("/design/video/plan", json={"idea": ""}).status_code == 400


def test_long_video_renders_every_scene_then_joins_them_with_the_voiceover(client, monkeypatch, moto_cache_table):
    calls = []
    peeks = {"n": 0}

    async def fake_video(action, **kw):
        calls.append((action, kw))
        if action == "budget":
            return {"ok": True, "used_usd": 1.0, "cap_usd": 10}
        if action == "submit":
            return {"ok": True, "job_id": f"scene-{sum(1 for a, _ in calls if a == 'submit')}"}
        if action == "peek":
            peeks["n"] += 1
            return {"ok": True, "status": "done" if peeks["n"] > 2 else "rendering"}
        if action == "stitch":
            return {"ok": True, "job_id": "joined-1"}
        if action == "status":
            return {"ok": True, "status": "done", "mime": "video/mp4", "base64": "QUJD", "voice": True}

    async def fake_speak(text, voice):
        assert text == "Fresh bread. Every morning." and voice == "Puck"
        return {"ok": True, "mime": "audio/wav", "base64": "UklG"}

    async def fake_save(data, mime, kind):
        return f"https://api/media/file/{kind}/x.{'wav' if kind == 'speech' else 'mp4'}"

    monkeypatch.setattr("gateway.design_router.video_call", fake_video)
    monkeypatch.setattr("gateway.design_router.gemini_media.speak", fake_speak)
    monkeypatch.setattr("gateway.design_router.media_store.save", fake_save)
    p = client.post("/design/video/project", json={"title": "Bakery", "aspect_ratio": "16:9", "voiceover": True, "voice": "Puck",
                                                   "scenes": [{"prompt": "dough", "narration": "Fresh bread."},
                                                              {"prompt": "oven", "narration": "Every morning."}]}).json()
    assert p["status"] == "rendering" and [s["job_id"] for s in p["scenes"]] == ["scene-1", "scene-2"]
    assert p["audio_url"].endswith("x.wav")
    assert client.get(f"/design/video/project/{p['id']}").json()["status"] == "rendering"  # scene 1 not done yet
    joining = client.get(f"/design/video/project/{p['id']}").json()
    assert joining["status"] == "joining" and joining["stitch_job"] == "joined-1"
    stitch = next(kw for a, kw in calls if a == "stitch")
    assert stitch["job_ids"] == ["scene-1", "scene-2"] and stitch["audio_url"] == p["audio_url"]
    done = client.get(f"/design/video/project/{p['id']}").json()
    assert done["status"] == "done" and done["url"].endswith("x.mp4") and done["voice"]
    listed = client.get("/design/videos").json()["videos"]
    assert listed[0]["job_id"] == p["id"] and listed[0]["url"] == done["url"]


def test_long_video_is_refused_when_the_budget_cant_cover_it(client, monkeypatch, moto_cache_table):
    async def fake_video(action, **kw):
        return {"ok": True, "used_usd": 9.5, "cap_usd": 10}

    monkeypatch.setattr("gateway.design_router.video_call", fake_video)
    r = client.post("/design/video/project", json={"scenes": [{"prompt": f"shot {i}"} for i in range(12)]})
    assert r.status_code == 400 and "$1.56" in r.json()["detail"]


async def test_short_video_prompts_are_extended_for_wan(monkeypatch):
    from pipeline import video_studio

    seen = {}
    long = " ".join(["word"] * 60)

    async def fake_complete(model, messages, **kw):
        seen["prompt"] = messages[0]["content"]
        return {"content": f"<think>hmm</think>{long}"}

    monkeypatch.setattr(video_studio.llm_providers, "complete", fake_complete)
    assert await video_studio.extend_prompt("bread rising", "9:16", "Vicinic Bakes") == long
    assert "80-120 English words" in seen["prompt"] and "on-screen text" in seen["prompt"]
    assert await video_studio.extend_prompt(long, "9:16") == long  # already detailed: left alone

    async def broken(model, messages, **kw):
        return {"error": "down"}

    monkeypatch.setattr(video_studio.llm_providers, "complete", broken)
    assert await video_studio.extend_prompt("bread rising", "9:16") == "bread rising"


def test_fast_mode_is_passed_to_modal_and_costs_less(client, monkeypatch, moto_cache_table):
    from pipeline import video_studio

    submits = []

    async def fake_video(action, **kw):
        if action == "budget":
            return {"ok": True, "used_usd": 9.5, "cap_usd": 10}
        submits.append(kw)
        return {"ok": True, "job_id": f"s{len(submits)}"}

    monkeypatch.setattr("gateway.design_router.video_call", fake_video)
    assert video_studio.estimate(60, fast=True) == {"scenes": 12, "minutes": 24, "usd": 0.36}
    scenes = [{"prompt": f"shot {i}"} for i in range(12)]
    assert client.post("/design/video/project", json={"scenes": scenes}).status_code == 400  # $1.56 > $0.50 left
    p = client.post("/design/video/project", json={"scenes": scenes, "fast": True}).json()  # $0.36 fits
    assert p["fast"] and len(submits) == 12 and all(kw["fast"] for kw in submits)
    client.post(f"/design/video/project/{p['id']}/scene/0")
    assert submits[-1]["fast"] is True  # a re-render keeps the project's mode


def test_a_storyboard_cut_off_mid_scene_keeps_the_complete_scenes():
    from pipeline import video_studio

    cut = ('{"title": "Teaser", "style": "dark gold", "scenes": [{"prompt": "black surface, gold line widens", '
           '"narration": "Vicinic."}, {"prompt": "logo glows \\"softly\\"", "narration": "Coming soon."}, {"prompt": "count')
    plan = video_studio.parse_plan(cut, 3, True)
    assert plan["title"] == "Teaser" and plan["style"] == "dark gold"
    assert [s["prompt"] for s in plan["scenes"]] == ["black surface, gold line widens", 'logo glows "softly"', 'logo glows "softly"']
    assert plan["scenes"][1]["narration"] == "Coming soon."


def test_modal_callbacks_finish_a_video_with_nobody_watching(client, monkeypatch, moto_cache_table):
    from config import settings
    from gateway import design_router

    state = {"scenes_done": False, "stitch_done": False}
    calls = []

    async def fake_video(action, timeout=60, **kw):
        calls.append((action, kw))
        if action == "budget":
            return {"ok": True, "used_usd": 0, "cap_usd": 10}
        if action == "submit":
            return {"ok": True, "job_id": f"scene-{sum(1 for a, _ in calls if a == 'submit')}"}
        if action == "peek":
            done = state["stitch_done"] if kw["job_id"] == "join-1" else state["scenes_done"]
            return {"ok": True, "status": "done" if done else "rendering"}
        if action == "stitch":
            return {"ok": True, "job_id": "join-1"}
        if action == "status":
            return {"ok": True, "status": "done", "uploaded": True, "voice": False}

    monkeypatch.setattr(design_router, "video_call", fake_video)
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.example")
    monkeypatch.setattr(settings, "MODAL_VIDEO_SECRET", "s3cret")
    monkeypatch.setattr(design_router.media_store, "enabled", lambda: True)
    monkeypatch.setattr(design_router.media_store, "presign_put", lambda key, mime: f"https://s3.example/{key}?put")
    monkeypatch.setattr(design_router.media_store, "exists", lambda key: False)
    monkeypatch.setattr(design_router.media_store, "link", lambda key: f"https://api.example/media/file/{key}")

    p = client.post("/design/video/project", json={"scenes": [{"prompt": "a"}, {"prompt": "b"}], "aspect_ratio": "9:16"}).json()
    submit = next(kw for a, kw in calls if a == "submit")
    assert submit["callback"] == "https://api.example/design/video/callback"
    assert client.post("/design/video/callback", json={"job_id": "scene-1"}).status_code == 401  # Modal signs it

    state["scenes_done"] = True
    auth = {"Authorization": "Bearer s3cret"}
    assert client.post("/design/video/callback", json={"job_id": "scene-2"}, headers=auth).json()["status"] == "joining"
    stitch = next(kw for a, kw in calls if a == "stitch")
    assert stitch["upload_url"].startswith("https://s3.example/video/") and stitch["callback"].endswith("/callback")

    state["stitch_done"] = True
    assert client.post("/design/video/callback", json={"job_id": "join-1"}, headers=auth).json()["status"] == "done"
    done = client.get(f"/design/video/project/{p['id']}").json()
    assert done["url"].startswith("https://api.example/media/file/video/") and done["url"].endswith(".mp4")
    assert design_router._active() == []  # finished: off the safety-net list


async def test_the_tick_moves_unfinished_videos_on(monkeypatch):
    from gateway import design_router

    seen = []
    monkeypatch.setattr(design_router, "_active", lambda: ["owner:abc", "owner:gone"])
    monkeypatch.setattr(design_router, "_project", lambda acct, pid: {"id": pid, "status": "joining"} if pid == "abc" else None)

    async def advance(acct, project):
        seen.append((acct, project["id"]))
        return {**project, "status": "done"}

    monkeypatch.setattr(design_router, "_advance", advance)
    assert await design_router.advance_all() == {"abc": "done"} and seen == [("owner", "abc")]


async def test_a_join_from_before_uploads_is_redone_with_a_direct_upload(monkeypatch, moto_cache_table):
    from gateway import design_router

    calls = []

    async def fake_video(action, timeout=60, **kw):
        calls.append((action, kw))
        if action == "peek":
            return {"ok": True, "status": "rendering"}  # the old join's huge result never comes back
        if action == "stitch":
            return {"ok": True, "job_id": "join-2"}

    monkeypatch.setattr(design_router, "video_call", fake_video)
    monkeypatch.setattr(design_router.media_store, "enabled", lambda: True)
    monkeypatch.setattr(design_router.media_store, "presign_put", lambda key, mime: f"https://s3.example/{key}?put")
    monkeypatch.setattr(design_router.media_store, "exists", lambda key: False)
    old = {"id": "p1", "status": "joining", "aspect_ratio": "9:16", "audio_url": "", "stitch_job": "join-1",
           "scenes": [{"job_id": "s1", "status": "done", "prompt": "a"}], "created": 1}
    out = await design_router._advance("owner", old)
    stitch = next(kw for a, kw in calls if a == "stitch")
    assert out["stitch_job"] == "join-2" and out["rejoins"] == 1 and out["final_key"].startswith("video/")
    assert stitch["upload_url"].startswith("https://s3.example/video/")


async def test_a_video_already_in_s3_is_done_whatever_modal_says(monkeypatch, moto_cache_table):
    from gateway import design_router

    async def fake_video(action, timeout=60, **kw):
        return {"ok": True, "status": "rendering"}

    monkeypatch.setattr(design_router, "video_call", fake_video)
    monkeypatch.setattr(design_router.media_store, "enabled", lambda: True)
    monkeypatch.setattr(design_router.media_store, "exists", lambda key: key == "video/2026-10-04/x.mp4")
    monkeypatch.setattr(design_router.media_store, "link", lambda key: f"https://api.example/media/file/{key}")
    p = {"id": "p2", "status": "joining", "aspect_ratio": "9:16", "stitch_job": "join-1", "final_key": "video/2026-10-04/x.mp4",
         "stitch_started": 1, "rejoins": 2, "scenes": [{"job_id": "s1", "status": "done", "prompt": "a"}], "created": 1}
    out = await design_router._advance("owner", p)
    assert out["status"] == "done" and out["url"].endswith("x.mp4")


async def test_a_join_that_keeps_failing_says_so_instead_of_hanging(monkeypatch, moto_cache_table):
    from gateway import design_router

    async def fake_video(action, timeout=60, **kw):
        raise AssertionError("no more joins")

    monkeypatch.setattr(design_router, "video_call", fake_video)
    monkeypatch.setattr(design_router.media_store, "enabled", lambda: True)
    monkeypatch.setattr(design_router.media_store, "exists", lambda key: False)
    p = {"id": "p3", "status": "joining", "aspect_ratio": "9:16", "stitch_job": "join-3", "final_key": "video/2026-10-04/y.mp4",
         "stitch_started": 1, "rejoins": 2, "scenes": [{"job_id": "s1", "status": "done", "prompt": "a"}], "created": 1}
    out = await design_router._advance("owner", p)
    assert out["status"] == "failed" and "Retry join" in out["error"]


def test_background_music_renders_with_the_scenes_and_is_mixed_into_the_join(client, monkeypatch, moto_cache_table):
    from gateway import design_router

    calls, state = [], {"music_done": False}

    async def fake_video(action, timeout=60, **kw):
        calls.append((action, kw))
        if action == "budget":
            return {"ok": False}
        if action == "submit":
            return {"ok": True, "job_id": "scene-1"}
        if action == "music":
            return {"ok": True, "job_id": "music-1"}
        if action == "peek":
            if kw["job_id"] == "music-1":
                return {"ok": True, "status": "done" if state["music_done"] else "rendering"}
            return {"ok": True, "status": "done"}
        if action == "stitch":
            return {"ok": True, "job_id": "join-1"}

    monkeypatch.setattr(design_router, "video_call", fake_video)
    monkeypatch.setattr(design_router.media_store, "enabled", lambda: True)
    monkeypatch.setattr(design_router.media_store, "exists", lambda key: False)
    monkeypatch.setattr(design_router.media_store, "presign_put", lambda key, mime: f"https://s3.example/{key}?put")
    p = client.post("/design/video/project", json={"scenes": [{"prompt": "a"}], "aspect_ratio": "9:16", "music": True,
                                                   "music_prompt": "lo-fi, 85 BPM, piano"}).json()
    music = next(kw for a, kw in calls if a == "music")
    assert music["prompt"] == "lo-fi, 85 BPM, piano" and music["seconds"] == 5 and p["music_status"] == "rendering"

    waiting = client.get(f"/design/video/project/{p['id']}").json()
    assert waiting["status"] == "rendering" and not any(a == "stitch" for a, _ in calls)  # scenes done, music not yet

    state["music_done"] = True
    joining = client.get(f"/design/video/project/{p['id']}").json()
    assert joining["status"] == "joining" and next(kw for a, kw in calls if a == "stitch")["music_job"] == "music-1"


def test_the_storyboard_carries_a_music_line():
    from pipeline.video_studio import parse_plan

    plan = parse_plan('{"title": "t", "style": "s", "music": "warm lo-fi, 85 BPM", "scenes": [{"prompt": "p"}]}', 1, False)
    assert plan["music"] == "warm lo-fi, 85 BPM"


def test_each_platform_gets_its_own_playbook_and_the_area(monkeypatch):
    import asyncio

    seen = {}

    async def fake_complete(choice, messages, max_tokens=4096, **k):
        seen["prompt"] = messages[0]["content"]
        return {"content": '[{"placement": "pinterest", "image_prompt": "x", "caption": "c"}]', "_provider": "gemini"}

    monkeypatch.setattr(ad_studio.llm_providers, "complete", fake_complete)
    out = asyncio.run(ad_studio.write_variants("web design studio", "launch", ["pinterest", "fb_ig_feed"], 1, "gemini",
                                               area="Soweto, Johannesburg"))
    assert out["ok"] and out["variants"][0]["aspect_ratio"] == "2:3"
    prompt = seen["prompt"]
    assert "Soweto, Johannesburg" in prompt and "pin built to be clicked" in prompt
    assert "gallery-worthy" in prompt and "keywords" in prompt  # fb_ig_feed (old id) now means Instagram


def test_hashtags_are_cleaned_and_capped_per_platform():
    text = ('[{"placement": "instagram", "image_prompt": "a", "hashtags": ' + str([f"tag {i}" for i in range(20)]).replace("'", '"')
            + ', "keywords": ["websites Soweto"]},'
            ' {"placement": "google_display", "image_prompt": "b", "hashtags": ["#x"]},'
            ' {"placement": "facebook", "image_prompt": "c", "hashtags": ["Mzansi", "#Mzansi", "#SouthAfrica"], "primary_text": "old"}]')
    ig, banner, fb = ad_studio.parse_variants(text)
    assert len(ig["hashtags"]) == 12 and ig["hashtags"][0] == "#tag0" and ig["keywords"] == ["websites Soweto"]
    assert banner["hashtags"] == []
    assert fb["hashtags"] == ["#Mzansi", "#SouthAfrica"] and fb["caption"] == "old"


def test_music_tab_makes_a_track_that_lands_in_s3(client, monkeypatch, moto_cache_table):
    from gateway import design_router

    calls, state = [], {"uploaded": False}

    async def fake_video(action, timeout=60, **kw):
        calls.append((action, kw))
        if action == "music":
            return {"ok": True, "job_id": "music-9"}
        if action == "peek":
            return {"ok": True, "status": "rendering"}

    monkeypatch.setattr(design_router, "video_call", fake_video)
    monkeypatch.setattr(design_router.media_store, "enabled", lambda: True)
    monkeypatch.setattr(design_router.media_store, "presign_put", lambda key, mime: f"https://s3.example/{key}?put")
    monkeypatch.setattr(design_router.media_store, "exists", lambda key: state["uploaded"])
    monkeypatch.setattr(design_router.media_store, "link", lambda key: f"https://api.example/media/file/{key}")

    assert client.post("/design/music", json={"prompt": ""}).status_code == 400
    made = client.post("/design/music", json={"prompt": "amapiano, 112 BPM", "seconds": 25}).json()
    music = next(kw for a, kw in calls if a == "music")
    assert made["job_id"] == "music-9" and music["seconds"] == 20 and music["upload_url"].startswith("https://s3.example/music/")
    assert client.get("/design/music/music-9").json()["status"] == "rendering"
    state["uploaded"] = True
    done = client.get("/design/music/music-9").json()
    assert done["status"] == "done" and done["url"].startswith("https://api.example/media/file/music/")
    assert client.get("/design/music/nope").status_code == 404


def test_a_reply_cut_off_mid_array_keeps_the_finished_posts():
    text = ('```json\n[{"placement": "instagram", "image_prompt": "a \\"quoted\\" {brace}", "caption": "c"},\n'
            ' {"placement": "story", "image_prompt": "b", "hashtags": ["#Mzansi"]},\n {"placement": "story", "image_pro')
    assert [v["placement"] for v in ad_studio.parse_variants(text)] == ["instagram", "story"]


async def test_a_picked_model_that_fails_falls_back_to_the_free_ones(monkeypatch):
    asked = []

    async def fake_complete(choice, messages, max_tokens=4096, **k):
        asked.append(choice)
        if choice == "bonsai":
            return {"content": "Sure, here are some ideas for your posts!", "_provider": "bonsai"}
        if choice == "gemini":
            return {"error": "Gemini Flash error 503: high demand"}
        return {"content": '[{"placement": "instagram", "image_prompt": "x"}]', "_provider": choice}

    for pid in ("bonsai", "gemini", "groq"):
        monkeypatch.setattr(ad_studio.llm_providers.PROVIDERS[pid].__class__, "configured", property(lambda self: True))
    monkeypatch.setattr(ad_studio.llm_providers, "complete", fake_complete)
    out = await ad_studio.write_variants("bakery", "intro", ["instagram"], 1, "bonsai")
    assert out["ok"] and asked == ["bonsai", "gemini", "groq"]
