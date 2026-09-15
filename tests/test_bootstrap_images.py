import pytest

from config import settings
from pipeline.bootstrap import Bootstrap
from pipeline.query_engine import RateLimitError


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
    saved = []

    class RecordingStore(FakeStore):
        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            saved.append({"session_id": session_id, "content": content, "embedding": embedding})

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

    assert all(s["session_id"] == "sess1" for s in saved)
    assert any(s["content"] == "I love the Nimzo-Larsen opening" for s in saved)
    assert all(s["embedding"] is not None for s in saved)


@pytest.mark.asyncio
async def test_run_embeds_the_reply_too_not_just_the_query(monkeypatch):
    """Only the user's own message used to get embedded into the searchable
    memories table — the assistant's reply never did, even though it's
    often the actually valuable content (a detailed answer, say). Once a
    turn ages out of the live conversation window (_trim_history), nothing
    could find that content again unless it was independently embedded."""
    saved_contents = []

    class RecordingStore(FakeStore):
        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            saved_contents.append(content)

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        yield "the repo has a Gateway, Frontend, and Tests directory"

    bootstrap.query_engine.stream_llm = fake_stream_llm

    [piece async for piece in bootstrap.run("what's in the repo", "sess1", [])]

    assert "what's in the repo" in saved_contents
    assert "the repo has a Gateway, Frontend, and Tests directory" in saved_contents


@pytest.mark.asyncio
async def test_run_does_not_embed_tool_driven_replies(monkeypatch):
    """A reply built from a web search, news, fetch, or repo read/grep
    (assistant_prefix non-empty — see gateway/router.py) already has an
    authoritative source outside this app that can be re-fetched fresh on
    demand. Embedding a snapshot of it would duplicate that source, go
    stale the moment it changes, and pile up near-duplicate memory rows
    every time the same repo/page gets asked about again later. Only the
    user's own query should still be embedded in that case."""
    saved_contents = []

    class RecordingStore(FakeStore):
        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            saved_contents.append(content)

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        yield "index.html has a hero section, a stats bar, and a contact form"

    bootstrap.query_engine.stream_llm = fake_stream_llm

    [
        piece async for piece in bootstrap.run(
            "what's in index.html", "sess1", [],
            assistant_prefix="[[SEMBLANCE_TOOL:{\"kind\":\"read\"}]]\n",
        )
    ]

    assert saved_contents == ["what's in index.html"]  # the reply itself never got embedded


@pytest.mark.asyncio
async def test_run_persists_display_query_not_the_augmented_one(monkeypatch):
    """A caller that folds attachments/search results into `query` for the
    model must be able to keep the *clean* original text as what gets
    persisted and embedded — otherwise a large search-result dump ends up
    saved as "what the user said" and later rendered back to them as if
    they'd typed it themselves."""
    saved_turns = []
    saved_memory_contents = []

    class RecordingStore(FakeStore):
        async def save_turn(self, session_id, role, content):
            saved_turns.append((role, content))

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            saved_memory_contents.append(content)

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
    assert "what's on the latest news" in saved_memory_contents
    assert augmented not in saved_memory_contents  # the augmented dump itself is never embedded either


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
async def test_run_trims_old_history_to_fit_the_char_budget(monkeypatch):
    """`history` is the frontend's full accumulated conversation, resent on
    every turn with no windowing on its own — a session with a few long
    exchanges eventually blows this account's tight Groq ITPM budget on
    history alone, even for a short unrelated follow-up. Only the most
    recent turns that fit the budget should reach Groq."""
    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    monkeypatch.setattr("pipeline.bootstrap._MAX_HISTORY_CHARS", 15)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    captured = {}

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        captured["messages"] = messages
        yield "ok"

    bootstrap.query_engine.stream_llm = fake_stream_llm

    history = [
        {"role": "user", "content": "a" * 40},
        {"role": "assistant", "content": "b" * 40},
        {"role": "user", "content": "c" * 10},  # only this most-recent turn fits under 15 chars
    ]
    [piece async for piece in bootstrap.run("new question", "sess1", history)]

    history_in_request = captured["messages"][1:-1]  # system prompt first, new user query last
    assert history_in_request == [{"role": "user", "content": "c" * 10}]


@pytest.mark.asyncio
async def test_run_keeps_the_single_most_recent_turn_even_if_it_alone_exceeds_budget(monkeypatch):
    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    monkeypatch.setattr("pipeline.bootstrap._MAX_HISTORY_CHARS", 10)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    captured = {}

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        captured["messages"] = messages
        yield "ok"

    bootstrap.query_engine.stream_llm = fake_stream_llm

    history = [{"role": "assistant", "content": "x" * 500}]
    [piece async for piece in bootstrap.run("new question", "sess1", history)]

    history_in_request = captured["messages"][1:-1]
    assert history_in_request == [{"role": "assistant", "content": "x" * 500}]


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


@pytest.mark.asyncio
async def test_run_surfaces_a_daily_rate_limit_as_a_friendly_minutes_message(monkeypatch):
    """A real one dumped Groq's raw error JSON straight into the chat as
    the reply — this is the one LLM failure worth a distinct, readable
    message instead of that."""
    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        raise RateLimitError(429, "qwen/qwen3.8-27b", "TPD limit exceeded", retry_after=655.776)
        yield  # pragma: no cover — makes this an async generator

    bootstrap.query_engine.stream_llm = fake_stream_llm

    result = [piece async for piece in bootstrap.run("hello", "sess1", [])]
    reply = "".join(result)
    assert "Groq" not in reply and "TPD" not in reply  # no raw error text leaked into the reply
    assert "11 minute" in reply


@pytest.mark.asyncio
async def test_run_surfaces_a_short_rate_limit_as_a_friendly_seconds_message(monkeypatch):
    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        raise RateLimitError(429, "qwen/qwen3.8-27b", "ITPM limit exceeded", retry_after=13.86)
        yield  # pragma: no cover

    bootstrap.query_engine.stream_llm = fake_stream_llm

    result = [piece async for piece in bootstrap.run("hello", "sess1", [])]
    reply = "".join(result)
    assert "14s" in reply or "13s" in reply


@pytest.mark.asyncio
async def test_run_surfaces_a_rate_limit_with_no_known_wait(monkeypatch):
    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    async def fake_retrieve(query, top_k=5):
        return []

    bootstrap.sem_retrieval.retrieve = fake_retrieve

    async def fake_stream_llm(messages, model=None, session_id="default", **kwargs):
        raise RateLimitError(429, "qwen/qwen3.8-27b", "rate limited", retry_after=None)
        yield  # pragma: no cover

    bootstrap.query_engine.stream_llm = fake_stream_llm

    result = [piece async for piece in bootstrap.run("hello", "sess1", [])]
    assert "give it a moment" in "".join(result).lower()
