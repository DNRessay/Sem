import pytest
import respx
from httpx import Response

from pipeline.query_engine import QueryEngine

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _groq_response(content: str):
    return Response(200, json={
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}]
    })


@pytest.mark.asyncio
async def test_call_llm_returns_content_and_hits_groq_on_first_call(moto_cache_table):
    engine = QueryEngine()
    with respx.mock:
        route = respx.post(GROQ_URL).mock(return_value=_groq_response("hello there"))
        result = await engine.call_llm([{"role": "user", "content": "hi"}], session_id="s1")

    assert result["content"] == "hello there"
    assert result["cached"] is False
    assert route.called


@pytest.mark.asyncio
async def test_call_llm_serves_second_identical_call_from_cache(moto_cache_table):
    engine = QueryEngine()
    messages = [{"role": "user", "content": "hi"}]
    with respx.mock:
        route = respx.post(GROQ_URL).mock(return_value=_groq_response("first"))
        first = await engine.call_llm(messages, session_id="s1")
        second = await engine.call_llm(messages, session_id="s1")

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["content"] == "first"
    assert route.call_count == 1  # second call served from DynamoDB cache, not Groq


def test_fire_break_invalidates_known_vector_only(moto_cache_table):
    engine = QueryEngine()
    engine.cache_ctrl.write("k", "v")
    engine.fire_break("not_a_vector")
    assert engine.cache_ctrl.read("k") == "v"
    engine.fire_break("model_switch")
    assert engine.cache_ctrl.check_break() is True
