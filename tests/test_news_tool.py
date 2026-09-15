import httpx
import pytest
import respx

from tools.web.news_tool import NewsTool


@pytest.mark.asyncio
async def test_latest_returns_error_without_api_key(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "SERP_API_KEY", "")
    result = await NewsTool().latest("chess")
    assert result == [{"error": "SERP_API_KEY not set"}]


@pytest.mark.asyncio
async def test_latest_parses_news_results(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "SERP_API_KEY", "fake_key")

    with respx.mock:
        respx.get("https://serpapi.com/search").mock(
            return_value=httpx.Response(200, json={
                "news_results": [
                    {"title": "Load shedding update", "link": "https://a.example",
                     "date": "1 hour ago", "source": "News24"},
                ],
            })
        )
        result = await NewsTool().latest("load shedding")

    assert result == [{"title": "Load shedding update", "link": "https://a.example",
                        "date": "1 hour ago", "source": "News24"}]


@pytest.mark.asyncio
async def test_latest_surfaces_a_body_level_error_instead_of_looking_empty(monkeypatch):
    """Same failure mode as SerpTool.search_full — a rate-limit/quota
    failure comes back as HTTP 200 with an `error` field, not a raised
    exception, so it has to be checked explicitly or it looks identical
    to "no news_results for this topic."""
    from config import settings
    monkeypatch.setattr(settings, "SERP_API_KEY", "fake_key")

    with respx.mock:
        respx.get("https://serpapi.com/search").mock(
            return_value=httpx.Response(200, json={"error": "rate limited"})
        )
        result = await NewsTool().latest("load shedding")

    assert result == [{"error": "rate limited"}]


@pytest.mark.asyncio
async def test_latest_surfaces_a_network_failure_instead_of_raising(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "SERP_API_KEY", "fake_key")

    with respx.mock:
        respx.get("https://serpapi.com/search").mock(side_effect=httpx.ConnectError("connection reset"))
        result = await NewsTool().latest("load shedding")

    assert len(result) == 1 and "error" in result[0]


def test_news_tool_is_registered():
    from tools.registry import get_registry
    registry = get_registry()
    assert "news_tool" in registry.list_all()
