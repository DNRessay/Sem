import json
import time

import pytest
from fastapi.testclient import TestClient

from cache import ddb_backend
from gateway.auth import require_account
from main import app
from pipeline import ad_studio, llm_providers
from tools import media_store


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = (Bucket, Body, ContentType)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://s3.example/{Params['Bucket']}/{Params['Key']}?ttl={ExpiresIn}"


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(media_store, "_client", lambda: fake)
    monkeypatch.setattr("config.settings.MEDIA_BUCKET", "media-bucket")
    monkeypatch.setattr("config.settings.PUBLIC_API_URL", "https://api.example")
    monkeypatch.setattr("config.settings.SECRET_KEY", "k" * 32)
    ddb_backend._l1.clear()
    return fake


@pytest.fixture
def client():
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.pop(require_account, None)


async def test_saved_files_get_a_signed_seven_day_link(s3):
    url = await media_store.save("QUJD", "image/png", "ads")
    key = next(iter(s3.objects))
    assert s3.objects[key] == ("media-bucket", b"ABC", "image/png") and key.startswith("ads/") and key.endswith(".png")
    assert url.startswith(f"https://api.example/media/file/{key}?exp=")
    exp = int(url.split("exp=")[1].split("&")[0])
    assert 7 * 86400 - 60 < exp - time.time() <= 7 * 86400


async def test_no_bucket_or_odd_types_keep_inline(s3, monkeypatch):
    assert await media_store.save("QUJD", "text/html", "ads") is None
    monkeypatch.setattr("config.settings.MEDIA_BUCKET", "")
    assert await media_store.save("QUJD", "image/png", "ads") is None


async def test_file_link_redirects_only_when_signed_and_fresh(s3, client):
    url = await media_store.save("QUJD", "image/png", "ads")
    path = url.removeprefix("https://api.example")
    r = client.get(path)
    assert r.status_code == 302 and r.headers["location"].startswith("https://s3.example/media-bucket/ads/")
    assert client.get(path.replace("sig=", "sig=0")).status_code == 404
    key = next(iter(s3.objects))
    old = int(time.time()) - 1
    assert client.get(f"/media/file/{key}?exp={old}&sig={media_store.sign(key, old)}").status_code == 404
    exp = int(time.time()) + 60
    assert client.get(f"/media/file/../../etc?exp={exp}&sig={media_store.sign('../../etc', exp)}").status_code == 404


def test_ad_images_go_to_s3(s3, client, monkeypatch):
    async def fake_write(*a, **k):
        return {"ok": True, "variants": [{"placement": "square", "headline": "A", "image_prompt": "a", "aspect_ratio": "1:1"}]}

    async def fake_image(prompt, aspect_ratio="1:1", references=None):
        return {"ok": True, "mime": "image/png", "base64": "QUJD"}

    monkeypatch.setattr("gateway.design_router.write_variants", fake_write)
    monkeypatch.setattr("gateway.design_router.image_gen.generate_image", fake_image)
    r = client.post("/design/ads", json={"brief": "bakery", "campaign": "launch"})
    image = [json.loads(ln[6:]) for ln in r.text.split("\n") if ln.startswith("data: {")][1]
    assert image["type"] == "image" and "base64" not in image and image["url"].startswith("https://api.example/media/file/ads/")
    again = client.post("/design/image", json={"prompt": "a", "aspect_ratio": "1:1"}).json()
    assert again["url"].startswith("https://api.example/media/file/ads/") and "base64" not in again


def test_finished_video_is_saved_once(s3, client, monkeypatch):
    calls = []

    async def fake_video(action, **kw):
        calls.append(action)
        return {"ok": True, "status": "done", "mime": "video/mp4", "base64": "QUJD", "gpu_seconds": 300}

    monkeypatch.setattr("gateway.design_router.video_call", fake_video)
    first = client.get("/design/video/job-1").json()
    second = client.get("/design/video/job-1").json()
    assert first == second and "base64" not in first and first["url"].startswith("https://api.example/media/file/video/")
    assert calls == ["status"] and len(s3.objects) == 1


@pytest.mark.parametrize("reply", [
    '<think>They want ads… let me plan [the] layout.</think>\n```json\n[{"placement": "square", "image_prompt": "bread",},]\n```',
    'Here you go:\n{"ads": [{"placement": "Square post", "headline": "H", "image_prompt": "bread"}]}',
    '[{"placement": "SQUARE", "image_prompt": "bread"}]',
])
def test_open_model_replies_still_parse(reply):
    variants = ad_studio.parse_variants(reply, ["square"])
    assert len(variants) == 1 and variants[0]["placement"] == "square" and variants[0]["aspect_ratio"] == "1:1"


async def test_auto_tries_the_next_free_model_when_one_returns_junk(monkeypatch):
    asked = []

    async def fake_complete(choice, messages, tools=None, max_tokens=4096, **k):
        asked.append(choice)
        if choice == "auto":
            return {"content": "I'd be happy to help with your ads!", "_provider": "bonsai"}
        return {"content": '[{"placement": "fb_ig_feed", "image_prompt": "x"}]', "_provider": choice}

    for pid in ("bonsai", "gemini", "groq"):
        monkeypatch.setattr(llm_providers.PROVIDERS[pid].__class__, "configured", property(lambda self: True))
    monkeypatch.setattr(ad_studio.llm_providers, "complete", fake_complete)
    result = await ad_studio.write_variants("bakery", "launch", ["fb_ig_feed"], 1, "auto")
    assert result["ok"] and asked == ["auto", "gemini"]


def test_presigned_links_are_sigv4_on_the_regional_endpoint(monkeypatch):
    from tools import media_store

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATEST")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setattr(media_store.settings, "MEDIA_BUCKET", "bucket-1")
    monkeypatch.setattr(media_store.settings, "MEDIA_REGION", "eu-west-1")
    url = media_store.presign_put("video/2026-10-04/a.mp4", "video/mp4")
    assert url.startswith("https://bucket-1.s3.eu-west-1.amazonaws.com/video/") and "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url


def test_media_links_become_direct_s3_links_for_modal(monkeypatch):
    from tools import media_store

    monkeypatch.setattr(media_store, "presigned", lambda key, expires=600: f"https://s3.example/{key}?e={expires}")
    link = "https://api.example/media/file/speech/2026-10-04/" + "a" * 32 + ".wav?exp=1&sig=x"
    assert media_store.direct(link) == "https://s3.example/speech/2026-10-04/" + "a" * 32 + ".wav?e=21600"
    assert media_store.direct("https://elsewhere.example/voice.wav") == "https://elsewhere.example/voice.wav"
