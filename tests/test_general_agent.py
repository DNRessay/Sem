import pytest
import respx
from httpx import Response

from agents.general_agent import GeneralAgent

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _groq_response(content: str):
    return Response(200, json={
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}]
    })


@pytest.mark.asyncio
async def test_run_makes_exactly_one_bounded_llm_call(moto_cache_table):
    """The previous implementation looped up to MAX_ITERATIONS=10 times,
    each with its own max_tokens budget, against a Groq tier capped at 1000
    output tokens/minute total — a single delegated task could blow the
    whole account's per-minute budget on its own. One call through the
    shared, rate-aware QueryEngine is what this account can sustain."""
    agent = GeneralAgent(session_id="s1")
    with respx.mock:
        route = respx.post(GROQ_URL).mock(return_value=_groq_response("here's the answer"))
        result = await agent.run({"query": "what's 2+2"})

    assert route.call_count == 1
    assert result == {"status": "complete", "result": "here's the answer", "iterations": 1}


@pytest.mark.asyncio
async def test_run_folds_context_in_as_a_system_message(moto_cache_table):
    agent = GeneralAgent(session_id="s1")
    with respx.mock:
        route = respx.post(GROQ_URL).mock(return_value=_groq_response("ok"))
        await agent.run({"query": "go", "context": "you are helpful"})

    import json
    body = json.loads(route.calls[0].request.content)
    assert body["messages"][0] == {"role": "system", "content": "you are helpful"}
    assert body["messages"][1] == {"role": "user", "content": "go"}


@pytest.mark.asyncio
async def test_run_returns_an_error_for_an_empty_query(moto_cache_table):
    agent = GeneralAgent(session_id="s1")
    result = await agent.run({"query": ""})
    assert result == {"error": "No query provided"}


@pytest.mark.asyncio
async def test_run_surfaces_a_groq_failure_instead_of_raising(moto_cache_table):
    agent = GeneralAgent(session_id="s1")
    with respx.mock:
        respx.post(GROQ_URL).mock(return_value=Response(401, json={"error": {"message": "Invalid API Key"}}))
        result = await agent.run({"query": "hi"})

    assert result["status"] == "error"
    assert "Invalid API Key" in result["result"]
