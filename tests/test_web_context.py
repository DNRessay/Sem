import pytest

from pipeline.web_context import detect_web_intent, run_web_intent, status_label


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
            return [{"title": "A", "snippet": "B", "link": "https://a.example"}]

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("search", "some query")
    assert "<web_search>" in result
    assert "A: B (https://a.example)" in result


@pytest.mark.asyncio
async def test_run_web_intent_search_empty_on_missing_key(monkeypatch):
    class FakeRegistry:
        async def execute(self, tool_name, args):
            return [{"error": "SERP_API_KEY not set"}]

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("search", "some query")
    assert result == ""


@pytest.mark.asyncio
async def test_run_web_intent_news_wraps_results(monkeypatch):
    class FakeRegistry:
        async def execute(self, tool_name, args):
            assert tool_name == "web_news"
            return [{"title": "A", "source": "News24", "date": "1 hour ago", "link": "https://a.example"}]

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("news", "what's on the latest news")
    assert "<web_news>" in result
    assert "A (News24, 1 hour ago): https://a.example" in result


@pytest.mark.asyncio
async def test_run_web_intent_news_empty_on_missing_key(monkeypatch):
    class FakeRegistry:
        async def execute(self, tool_name, args):
            return [{"error": "SERP_API_KEY not set"}]

    monkeypatch.setattr("pipeline.web_context.get_registry", lambda: FakeRegistry())
    result = await run_web_intent("news", "what's on the latest news")
    assert result == ""
