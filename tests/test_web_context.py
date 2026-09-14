import pytest

from pipeline.web_context import _news_topic, _personalized_topic, detect_web_intent, run_web_intent, status_label


def test_detect_web_intent_finds_url():
    assert detect_web_intent("check out https://example.com/page for info") == ("fetch", "https://example.com/page")


def test_detect_web_intent_url_wins_over_search_phrase():
    kind, target = detect_web_intent("look up https://example.com")
    assert kind == "fetch"
    assert target == "https://example.com"


def test_detect_web_intent_finds_search_phrase():
    assert detect_web_intent("search the web for the latest AI news") == ("search", "search the web for the latest AI news")
    assert detect_web_intent("look up the weather in cape town")[0] == "search"
    assert detect_web_intent("google the current bitcoin price")[0] == "search"


def test_detect_web_intent_finds_weather_phrase_without_other_trigger_words():
    assert detect_web_intent("what's the weather like in Pretoria 2day")[0] == "search"
    assert detect_web_intent("weather forecast for durban")[0] == "search"
    assert detect_web_intent("weather in joburg")[0] == "search"


def test_detect_web_intent_finds_news_phrase():
    assert detect_web_intent("what's on the latest news")[0] == "news"
    assert detect_web_intent("any breaking news today?")[0] == "news"
    assert detect_web_intent("news about load shedding")[0] == "news"


def test_detect_web_intent_returns_none_for_ordinary_chat():
    assert detect_web_intent("hey, how's it going?") is None
    assert detect_web_intent("write me a python function") is None


def test_status_label_differs_by_kind():
    assert status_label("fetch", "https://example.com") == "Fetching https://example.com…"
    assert status_label("search", "anything") == "Searching the web…"
    assert status_label("news", "anything") == "Checking the latest news…"


@pytest.mark.asyncio
async def test_run_web_intent_fetch_returns_empty_block_on_tool_error(monkeypatch):
    class FakeRegistry:
        async def execute(self, tool_name, args):
            return {"error": "boom"}

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("fetch", "https://example.com")
    assert result == ""


@pytest.mark.asyncio
async def test_run_web_intent_fetch_wraps_content(monkeypatch):
    class FakeRegistry:
        async def execute(self, tool_name, args):
            return {"content": "hello world", "url": args["url"]}

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("fetch", "https://example.com")
    assert '<web_fetch url="https://example.com">' in result
    assert "hello world" in result


@pytest.mark.asyncio
async def test_run_web_intent_search_wraps_results(monkeypatch):
    class FakeRegistry:
        async def execute(self, tool_name, args):
            assert tool_name == "web_search_full"
            return {"results": [{"title": "A", "snippet": "B", "link": "https://a.example"}], "ai_overview": None}

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("search", "some query")
    assert "<web_search>" in result
    assert "A: B (https://a.example)" in result
    assert "<google_ai_overview" not in result


@pytest.mark.asyncio
async def test_run_web_intent_search_empty_on_missing_key(monkeypatch):
    class FakeRegistry:
        async def execute(self, tool_name, args):
            return {"error": "SERP_API_KEY not set"}

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("search", "some query")
    assert result == ""


@pytest.mark.asyncio
async def test_run_web_intent_search_includes_ai_overview_when_present(monkeypatch):
    class FakeRegistry:
        async def execute(self, tool_name, args):
            return {
                "results": [{"title": "A", "snippet": "B", "link": "https://a.example"}],
                "ai_overview": "Google says X is true.",
            }

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("search", "is X true")
    assert '<google_ai_overview query="is X true">' in result
    assert "Google says X is true." in result
    assert "<web_search>" in result  # organic results still included alongside it


@pytest.mark.asyncio
async def test_run_web_intent_search_includes_answer_box_for_weather(monkeypatch):
    class FakeRegistry:
        async def execute(self, tool_name, args):
            return {
                "results": [],
                "ai_overview": None,
                "answer_box": "24°C Sunny in Pretoria, South Africa",
            }

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("search", "what's the weather like in pretoria")
    assert '<google_answer query="what\'s the weather like in pretoria">' in result
    assert "24°C Sunny in Pretoria, South Africa" in result


@pytest.mark.asyncio
async def test_run_web_intent_search_costs_one_registry_call(monkeypatch):
    calls = []

    class FakeRegistry:
        async def execute(self, tool_name, args):
            calls.append(tool_name)
            return {"results": [], "ai_overview": "an answer"}

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    await run_web_intent("search", "some query")
    assert calls == ["web_search_full"]


def test_news_topic_strips_generic_filler_to_a_fallback():
    assert _news_topic("what's on the latest news") == "top stories"
    assert _news_topic("any breaking news today?") == "top stories"


def test_news_topic_keeps_the_actual_subject():
    assert _news_topic("news about load shedding") == "load shedding"
    assert _news_topic("what's the latest news on the springboks") == "springboks"


@pytest.mark.asyncio
async def test_run_web_intent_news_wraps_results(monkeypatch):
    class FakeRegistry:
        async def execute(self, tool_name, args):
            assert tool_name == "web_news"
            return [{"title": "A", "source": "News24", "date": "1 hour ago", "link": "https://a.example"}]

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("news", "what's on the latest news")
    assert '<web_news topic="top stories">' in result
    assert "A (News24, 1 hour ago): https://a.example" in result


@pytest.mark.asyncio
async def test_run_web_intent_news_passes_extracted_topic_not_raw_sentence(monkeypatch):
    captured = {}

    class FakeRegistry:
        async def execute(self, tool_name, args):
            captured["args"] = args
            return [{"title": "A", "source": "S", "date": "d", "link": "l"}]

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    await run_web_intent("news", "news about load shedding")
    assert captured["args"] == {"topic": "load shedding"}


@pytest.mark.asyncio
async def test_run_web_intent_news_empty_on_missing_key(monkeypatch):
    class FakeRegistry:
        async def execute(self, tool_name, args):
            return [{"error": "SERP_API_KEY not set"}]

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("news", "what's on the latest news")
    assert result == ""


@pytest.mark.asyncio
async def test_run_web_intent_news_survives_a_tool_exception(monkeypatch):
    """ToolsRegistry.execute catches any exception the underlying tool call
    raises (a SerpAPI quota/network failure, not just a missing key) and
    returns a plain {"error": ...} dict — a different shape than NewsTool's
    own list-based success/no-key paths. Indexing that dict with result[0]
    used to raise a KeyError that silently killed the whole /chat stream
    mid-response with nothing surfaced to the client."""
    class FakeRegistry:
        async def execute(self, tool_name, args):
            return {"error": "quota exceeded"}  # what ToolsRegistry.execute returns on an exception

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("news", "what's on the latest news")
    assert result == ""


@pytest.mark.asyncio
async def test_personalized_topic_returns_none_with_no_memories(monkeypatch):
    class FakeStore:
        async def semantic_search(self, embedding, top_k=5):
            return []

    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr("pipeline.web_context.get_store", fake_get_store)
    assert await _personalized_topic("sess1") is None


@pytest.mark.asyncio
async def test_personalized_topic_uses_top_memory(monkeypatch):
    class FakeStore:
        async def semantic_search(self, embedding, top_k=5):
            return [{"content": "how do I set up Modal for embeddings"}]

    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr("pipeline.web_context.get_store", fake_get_store)
    topic = await _personalized_topic("sess1")
    assert topic == "how do I set up Modal for embeddings"


@pytest.mark.asyncio
async def test_run_web_intent_news_blends_personal_topic_for_generic_ask(monkeypatch):
    calls = []

    class FakeRegistry:
        async def execute(self, tool_name, args):
            calls.append(args["topic"])
            return [{"title": "A", "source": "S", "date": "d", "link": "l"}]

    async def fake_personalized_topic(session_id):
        return "chess openings"

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    monkeypatch.setattr("pipeline.web_context._personalized_topic", fake_personalized_topic)

    result = await run_web_intent("news", "what's on the latest news", session_id="sess1")
    assert calls == ["top stories", "chess openings"]
    assert result.count("<web_news") == 2


@pytest.mark.asyncio
async def test_run_web_intent_news_does_not_blend_for_specific_topic(monkeypatch):
    calls = []

    class FakeRegistry:
        async def execute(self, tool_name, args):
            calls.append(args["topic"])
            return [{"title": "A", "source": "S", "date": "d", "link": "l"}]

    async def fake_personalized_topic(session_id):
        raise AssertionError("should not be called for a specific topic")

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    monkeypatch.setattr("pipeline.web_context._personalized_topic", fake_personalized_topic)

    await run_web_intent("news", "news about load shedding", session_id="sess1")
    assert calls == ["load shedding"]


@pytest.mark.asyncio
async def test_run_web_intent_news_without_session_id_skips_personalization(monkeypatch):
    calls = []

    class FakeRegistry:
        async def execute(self, tool_name, args):
            calls.append(args["topic"])
            return [{"title": "A", "source": "S", "date": "d", "link": "l"}]

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    await run_web_intent("news", "what's on the latest news")
    assert calls == ["top stories"]
