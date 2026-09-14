import pytest

from config import settings
from pipeline.bootstrap import Bootstrap


class FakeStore:
    async def list_skills(self, enabled_only: bool = False):
        return []

    async def save_turn(self, session_id, role, content):
        pass


@pytest.mark.asyncio
async def test_run_uses_plain_text_content_and_default_model_without_images(monkeypatch):
    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    captured = {}

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        captured["messages"] = messages
        captured["model"] = model
        yield "ok"

    bootstrap.query_engine.stream_llm = fake_stream_llm

    result = [piece async for piece in bootstrap.run("hello", "sess1", [])]
    assert "".join(result) == "ok"
    assert captured["model"] == settings.GROQ_MODEL
    assert captured["messages"][-1] == {"role": "user", "content": "hello"}


@pytest.mark.asyncio
async def test_run_switches_to_vision_model_and_sends_image_content_parts(monkeypatch):
    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    captured = {}

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        captured["messages"] = messages
        captured["model"] = model
        yield "ok"

    bootstrap.query_engine.stream_llm = fake_stream_llm

    images = [{"name": "shot.png", "mime": "image/png", "base64": "Zm9v"}]
    result = [piece async for piece in bootstrap.run("what's in this image?", "sess1", [], images=images)]

    assert "".join(result) == "ok"
    assert captured["model"] == settings.GROQ_VISION_MODEL

    last_msg = captured["messages"][-1]
    assert last_msg["role"] == "user"
    assert last_msg["content"][0] == {"type": "text", "text": "what's in this image?"}
    assert last_msg["content"][1]["image_url"]["url"] == "data:image/png;base64,Zm9v"


@pytest.mark.asyncio
async def test_run_injects_current_date_into_system_prompt(monkeypatch):
    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    captured = {}

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        captured["messages"] = messages
        yield "ok"

    bootstrap.query_engine.stream_llm = fake_stream_llm

    [piece async for piece in bootstrap.run("what's today's date?", "sess1", [])]

    system_msg = captured["messages"][0]
    assert system_msg["role"] == "system"
    assert "Current date and time:" in system_msg["content"]
    assert "SAST" in system_msg["content"]
