import pytest
from fastapi.testclient import TestClient

from config import settings
from gateway.auth import require_account
from main import app
from tools import tts, voice_client


@pytest.fixture
def client():
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app)
    app.dependency_overrides.pop(require_account, None)


def test_voice_url_is_derived_from_the_video_app(monkeypatch):
    monkeypatch.setattr(settings, "MODAL_VIDEO_URL", "https://me--semblance-video-api.modal.run/")
    monkeypatch.setattr(settings, "VOICE_URL", "")
    assert voice_client.url() == "https://me--semblance-voice-api.modal.run/"
    monkeypatch.setattr(settings, "VOICE_URL", "off")
    assert voice_client.url() == ""


async def test_kokoro_first_then_gemini(monkeypatch):
    async def kokoro(text, voice="Kore", timeout=12):
        return {"ok": True, "mime": "audio/wav", "base64": "UklG"}

    async def gemini(text, voice="Kore"):
        return {"ok": True, "mime": "audio/wav", "base64": "R0VN"}

    monkeypatch.setattr(tts.voice_client, "speak", kokoro)
    monkeypatch.setattr(tts.gemini_media, "speak", gemini)
    assert (await tts.speak("Hello"))["engine"] == "kokoro"

    async def down(text, voice="Kore", timeout=12):
        return {"ok": False, "error": "voice service unreachable"}

    monkeypatch.setattr(tts.voice_client, "speak", down)
    out = await tts.speak("Hello")
    assert out["engine"] == "gemini" and out["base64"] == "R0VN"


def test_transcribe_uses_whistle_then_groq(client, monkeypatch):
    async def whistle(audio, keywords=None, timeout=20):
        assert audio == "UklG" and keywords == ["Semblance"]
        return {"ok": True, "text": " hello sem ", "took": 0.02}

    monkeypatch.setattr("gateway.media_router.voice_client.transcribe", whistle)
    r = client.post("/media/transcribe", json={"audio": "UklG", "keywords": ["Semblance"]}).json()
    assert r == {"ok": True, "text": "hello sem", "engine": "whistle", "took": 0.02}

    async def down(audio, keywords=None, timeout=20):
        return {"ok": False, "error": "voice service unreachable"}

    async def groq(raw, name):
        return "hello from groq"

    monkeypatch.setattr("gateway.media_router.voice_client.transcribe", down)
    monkeypatch.setattr("gateway.media_router._groq_transcribe", groq)
    assert client.post("/media/transcribe", json={"audio": "UklG"}).json()["engine"] == "groq"
    assert client.post("/media/transcribe", json={}).status_code == 400
