import httpx
import pytest
import respx

from tools.web.serp_tool import SerpTool


@pytest.mark.asyncio
async def test_search_full_returns_error_without_api_key(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "SERP_API_KEY", "")
    result = await SerpTool().search_full("test query")
    assert result == {"error": "SERP_API_KEY not set"}


@pytest.mark.asyncio
async def test_search_full_parses_organic_results_and_ai_overview(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "SERP_API_KEY", "fake_key")

    with respx.mock:
        respx.get("https://serpapi.com/search").mock(
            return_value=httpx.Response(200, json={
                "organic_results": [
                    {"title": "Result A", "link": "https://a.example", "snippet": "About A"},
                ],
                "ai_overview": {
                    "text_blocks": [
                        {"type": "paragraph", "snippet": "Google's synthesized answer."},
                        {"type": "paragraph", "snippet": "A second paragraph."},
                    ],
                },
            })
        )
        result = await SerpTool().search_full("test query")

    assert result["results"] == [{"title": "Result A", "link": "https://a.example", "snippet": "About A"}]
    assert result["ai_overview"] == "Google's synthesized answer.\nA second paragraph."


@pytest.mark.asyncio
async def test_search_full_ai_overview_is_none_when_absent(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "SERP_API_KEY", "fake_key")

    with respx.mock:
        respx.get("https://serpapi.com/search").mock(
            return_value=httpx.Response(200, json={"organic_results": []})
        )
        result = await SerpTool().search_full("test query")

    assert result["ai_overview"] is None


@pytest.mark.asyncio
async def test_search_full_ai_overview_is_none_when_only_a_page_token(monkeypatch):
    """Google sometimes truncates the overview behind a page_token needing a
    second, separately-billed call — that expansion is deliberately not
    fetched here, so this should come back empty rather than silently
    spending extra quota."""
    from config import settings
    monkeypatch.setattr(settings, "SERP_API_KEY", "fake_key")

    with respx.mock:
        respx.get("https://serpapi.com/search").mock(
            return_value=httpx.Response(200, json={
                "organic_results": [],
                "ai_overview": {"page_token": "abc123"},
            })
        )
        result = await SerpTool().search_full("test query")

    assert result["ai_overview"] is None


def test_web_search_full_is_registered():
    from tools.registry import get_registry
    registry = get_registry()
    assert "web_search_full" in registry.list_all()
