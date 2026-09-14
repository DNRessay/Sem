import pytest
import respx
from httpx import Response

from pipeline.session_title import generate_title

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


@pytest.mark.asyncio
async def test_generate_title_returns_the_llms_short_reply(moto_cache_table):
    with respx.mock:
        respx.post(GROQ_URL).mock(
            return_value=Response(200, json={
                "choices": [{"message": {"content": '"Chess opening strategy"'}, "finish_reason": "stop"}],
            })
        )
        title = await generate_title("tell me about the Nimzo-Larsen", "It's a hypermodern opening...")

    assert title == "Chess opening strategy"  # surrounding quotes stripped


@pytest.mark.asyncio
async def test_generate_title_requests_a_tiny_max_tokens(moto_cache_table):
    """This account's Groq rate limit is tight enough that even a one-off
    title-generation call needs to stay cheap — must not reuse a normal
    reply's max_tokens budget."""
    captured = {}

    def handler(request):
        import json
        captured["payload"] = json.loads(request.content)
        return Response(200, json={"choices": [{"message": {"content": "A title"}, "finish_reason": "stop"}]})

    with respx.mock:
        respx.post(GROQ_URL).mock(side_effect=handler)
        await generate_title("hello", "hi there")

    assert captured["payload"]["max_tokens"] == 20


@pytest.mark.asyncio
async def test_generate_title_returns_empty_string_on_any_failure(moto_cache_table):
    """A title-generation hiccup (rate limit, bad key, network blip) must
    never break the actual reply — the caller treats "" as "skip it"."""
    with respx.mock:
        respx.post(GROQ_URL).mock(return_value=Response(401, json={"error": {"message": "bad key"}}))
        title = await generate_title("hello", "hi there")

    assert title == ""
