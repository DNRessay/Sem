import base64
import io
import json
import wave

import pytest
import respx
from httpx import Response

from tools import gemini_media

IMG = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent"
TTS = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent"


@pytest.fixture(autouse=True)
def key(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gk")


def _parts(*parts):
    return Response(200, json={"candidates": [{"content": {"parts": list(parts)}}]})


@pytest.mark.asyncio
async def test_image_returns_the_inline_data_and_sends_the_aspect_ratio():
    with respx.mock:
        route = respx.post(IMG).mock(return_value=_parts({"text": "here"}, {"inlineData": {"mimeType": "image/png", "data": "QUJD"}}))
        result = await gemini_media.generate_image("a poster", "9:16")
    assert result == {"ok": True, "mime": "image/png", "base64": "QUJD"}
    sent = json.loads(route.calls[0].request.content)
    assert sent["generationConfig"]["imageConfig"]["aspectRatio"] == "9:16"
    assert route.calls[0].request.headers["x-goog-api-key"] == "gk"


@pytest.mark.asyncio
async def test_image_without_image_parts_is_an_error():
    with respx.mock:
        respx.post(IMG).mock(return_value=_parts({"text": "I can't make that"}))
        result = await gemini_media.generate_image("x")
    assert result["ok"] is False and "no image" in result["error"]


@pytest.mark.asyncio
async def test_rate_limit_is_flagged():
    with respx.mock:
        respx.post(IMG).mock(return_value=Response(429, json={}))
        result = await gemini_media.generate_image("x")
    assert result["rate_limited"]


@pytest.mark.asyncio
async def test_speech_wraps_raw_pcm_in_a_wav():
    pcm = b"\x00\x01" * 2400
    with respx.mock:
        respx.post(TTS).mock(return_value=_parts(
            {"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}))
        result = await gemini_media.speak("hello", "Puck")
    wav = wave.open(io.BytesIO(base64.b64decode(result["base64"])))
    assert result["mime"] == "audio/wav" and wav.getframerate() == 24000 and wav.readframes(10_000) == pcm


@pytest.mark.asyncio
async def test_missing_key_is_a_clear_error(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    assert "GEMINI_API_KEY" in (await gemini_media.speak("hi"))["error"]
