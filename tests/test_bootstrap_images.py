import pytest

from config import settings
from pipeline.bootstrap import Bootstrap


class FakeStore:
    async def list_skills(self, enabled_only: bool = False):
        return []

    async def save_turn(self, session_id, role, content):
        pass

    async def save_memory(self, session_id, content, salience=0.5, embedding=None):
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


@pytest.mark.asyncio
async def test_run_writes_the_query_to_long_term_memory(monkeypatch):
    saved = {}

    class RecordingStore(FakeStore):
        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            saved["session_id"] = session_id
            saved["content"] = content
            saved["embedding"] = embedding

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        yield "ok"

    bootstrap.query_engine.stream_llm = fake_stream_llm

    [piece async for piece in bootstrap.run("I love the Nimzo-Larsen opening", "sess1", [])]

    assert saved["session_id"] == "sess1"
    assert saved["content"] == "I love the Nimzo-Larsen opening"
    assert saved["embedding"] is not None


@pytest.mark.asyncio
async def test_run_persists_display_query_not_the_augmented_one(monkeypatch):
    """A caller that folds attachments/search results into `query` for the
    model must be able to keep the *clean* original text as what gets
    persisted and embedded — otherwise a large search-result dump ends up
    saved as "what the user said" and later rendered back to them as if
    they'd typed it themselves."""
    saved_turns = []
    saved_memory = {}

    class RecordingStore(FakeStore):
        async def save_turn(self, session_id, role, content):
            saved_turns.append((role, content))

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            saved_memory["content"] = content

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        yield "here's what I found"

    bootstrap.query_engine.stream_llm = fake_stream_llm

    augmented = "what's on the latest news\n\n<web_news>huge dump of results...</web_news>"
    result = [
        piece async for piece in bootstrap.run(
            augmented, "sess1", [], display_query="what's on the latest news",
        )
    ]

    assert "".join(result) == "here's what I found"
    assert ("user", "what's on the latest news") in saved_turns
    assert ("user", augmented) not in saved_turns
    assert saved_memory["content"] == "what's on the latest news"


@pytest.mark.asyncio
async def test_run_surfaces_llm_errors_instead_of_dying_silently(monkeypatch):
    """A Groq API failure (context length exceeded — easy to hit with a big
    repo attach, rate limit, bad key, network blip) used to propagate
    straight out of this generator and silently kill the whole streamed
    response: nothing shown, nothing saved, no error surfaced to the client.
    Same failure shape as the earlier news-tool KeyError bug, one level up —
    any LLM-call failure at all, not just one tool's."""
    saved_turns = []

    class RecordingStore(FakeStore):
        async def save_turn(self, session_id, role, content):
            saved_turns.append((role, content))

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        raise RuntimeError("Groq API error (status 400) for model 'x': context_length_exceeded")
        yield  # pragma: no cover - unreachable, keeps this an async generator function

    bootstrap.query_engine.stream_llm = fake_stream_llm

    result = [piece async for piece in bootstrap.run("hello", "sess1", [])]
    reply = "".join(result)
    assert reply  # something was yielded, not a silent dead stream
    assert "context_length_exceeded" in reply
    assert ("assistant", reply) in saved_turns  # still persisted, not dropped


@pytest.mark.asyncio
async def test_run_prepends_assistant_prefix_only_to_persisted_content(monkeypatch):
    saved_turns = []

    class RecordingStore(FakeStore):
        async def save_turn(self, session_id, role, content):
            saved_turns.append((role, content))

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        yield "the reply"

    bootstrap.query_engine.stream_llm = fake_stream_llm

    streamed = [
        piece async for piece in bootstrap.run(
            "hello", "sess1", [], assistant_prefix="[[SEMBLANCE_TOOL:{\"kind\":\"news\"}]]\n",
        )
    ]

    assert "".join(streamed) == "the reply"  # marker never appears in what's actually streamed
    assert ("assistant", "[[SEMBLANCE_TOOL:{\"kind\":\"news\"}]]\nthe reply") in saved_turns
