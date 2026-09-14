import httpx
import pytest
import respx

from tools.web.fetch_tool import FetchTool


def test_fetch_requires_a_url():
    import asyncio
    result = asyncio.run(FetchTool().fetch(""))
    assert result == {"error": "No URL provided"}


@pytest.mark.asyncio
async def test_fetch_strips_html_to_readable_text():
    html = "<html><head><style>body{color:red}</style></head><body><script>evil()</script><h1>Title</h1><p>Hello world.</p></body></html>"
    with respx.mock:
        respx.get("https://example.com/page").mock(
            return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
        )
        result = await FetchTool().fetch("https://example.com/page")

    assert result["status"] == 200
    assert "Title" in result["content"]
    assert "Hello world." in result["content"]
    assert "evil()" not in result["content"]
    assert "color:red" not in result["content"]


@pytest.mark.asyncio
async def test_fetch_returns_error_on_network_failure():
    with respx.mock:
        respx.get("https://example.com/down").mock(side_effect=httpx.ConnectError("nope"))
        result = await FetchTool().fetch("https://example.com/down")

    assert "error" in result
    assert result["url"] == "https://example.com/down"
