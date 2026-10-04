import json

import pytest

from pipeline import voice_stream


async def _lines(chunks):
    for c in chunks:
        yield f"data: {json.dumps({'chunk': c})}\n\n"
    yield f"data: {json.dumps({'title': 'T'})}\n\n"
    yield "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_sentences_are_spoken_in_order_inside_the_stream(monkeypatch):
    said = []

    async def fake_speak(text, voice="Kore"):
        said.append(text)
        return {"ok": True, "mime": "audio/wav", "base64": "UklG"}

    async def fake_save(data):
        return f"https://s3/{len(said)}.wav"

    monkeypatch.setattr(voice_stream.tts, "speak", fake_speak)
    monkeypatch.setattr(voice_stream.media_store, "save_speech", fake_save)
    chunks = ["Hello there, how are you today? ", "Here's **the** plan. " * 15, "```py\nx=1\n```", "Done"]
    out = [line async for line in voice_stream.with_speech(_lines(chunks))]
    events = [json.loads(line[6:]) for line in out if line.startswith("data: {")]
    speech = [e["speech"] for e in events if "speech" in e]
    assert [s["seq"] for s in speech] == list(range(1, len(speech) + 1))
    assert speech[0]["text"] == "Hello there, how are you today?" and speech[0]["url"].startswith("https://s3/")
    assert "**" not in " ".join(said) and "x=1" not in " ".join(said)
    assert events[-1] == {"speech_done": len(speech)} and out[-1] == "data: [DONE]\n\n"
    assert "".join(e.get("chunk", "") for e in events) == "".join(chunks)


@pytest.mark.asyncio
async def test_rate_limit_leaves_the_rest_to_the_phone_voice(monkeypatch):
    async def limited(text, voice="Kore"):
        return {"ok": False, "rate_limited": True, "error": "limit"}

    monkeypatch.setattr(voice_stream.tts, "speak", limited)
    out = [line async for line in voice_stream.with_speech(_lines(["One sentence here. ", "Another one. " * 30]))]
    speech = [json.loads(line[6:])["speech"] for line in out if '"speech"' in line]
    assert len(speech) >= 2 and all("url" not in s and "base64" not in s for s in speech)
