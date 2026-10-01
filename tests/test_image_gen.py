import pytest

from tools import image_gen


@pytest.fixture
def flux(monkeypatch):
    calls = []

    async def fake_call(action, **kw):
        calls.append(action)
        if action == "image":
            return {"ok": True, "job_id": "j1"}
        return {"ok": True, "status": "done", "mime": "image/png", "base64": "RkxVWA=="}

    async def no_sleep(_):
        return None

    monkeypatch.setattr(image_gen, "video_call", fake_call)
    monkeypatch.setattr(image_gen.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(image_gen.settings, "MODAL_VIDEO_URL", "https://modal.example")
    return calls


def _gemini(monkeypatch, result):
    async def fake(prompt, aspect_ratio="1:1", references=None):
        return result
    monkeypatch.setattr(image_gen.gemini_media, "generate_image", fake)


@pytest.mark.asyncio
async def test_gemini_first(monkeypatch, flux):
    _gemini(monkeypatch, {"ok": True, "mime": "image/png", "base64": "R0VN"})
    out = await image_gen.generate_image("ad")
    assert out["engine"] == "gemini" and flux == []


@pytest.mark.asyncio
async def test_flux_when_gemini_is_out_of_quota(monkeypatch, flux):
    _gemini(monkeypatch, {"ok": False, "error": "Gemini free-tier limit reached — try again later", "rate_limited": True})
    out = await image_gen.generate_image("ad", "9:16")
    assert out == {"ok": True, "mime": "image/png", "base64": "RkxVWA==", "engine": "flux"}
    assert flux == ["image", "status"]


@pytest.mark.asyncio
async def test_no_fallback_without_modal_or_for_other_errors(monkeypatch, flux):
    _gemini(monkeypatch, {"ok": False, "error": "Gemini error 400: bad"})
    assert (await image_gen.generate_image("ad"))["ok"] is False and flux == []
    monkeypatch.setattr(image_gen.settings, "MODAL_VIDEO_URL", "")
    _gemini(monkeypatch, {"ok": False, "error": "limit", "rate_limited": True})
    out = await image_gen.generate_image("ad")
    assert out["rate_limited"] and flux == []
