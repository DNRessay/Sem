import json

import pytest
import respx
from httpx import Response

from agents.plan_agent import PlanAgent

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _groq_json_response(obj: dict):
    return Response(200, json={
        "choices": [{"message": {"content": json.dumps(obj)}, "finish_reason": "stop"}]
    })


@pytest.mark.asyncio
async def test_run_returns_the_parsed_plan(moto_cache_table):
    plan_obj = {"steps": [{"n": 1, "action": "do it", "tool": "bash", "expected_output": "done"}],
                "risks": [], "success_criteria": "it's done"}
    agent = PlanAgent(session_id="s1")
    with respx.mock:
        respx.post(GROQ_URL).mock(return_value=_groq_json_response(plan_obj))
        result = await agent.run({"goal": "ship the feature"})

    assert result["goal"] == "ship the feature"
    assert result["plan"] == plan_obj


@pytest.mark.asyncio
async def test_run_requests_json_response_format(moto_cache_table):
    agent = PlanAgent(session_id="s1")
    with respx.mock:
        route = respx.post(GROQ_URL).mock(return_value=_groq_json_response({"steps": []}))
        await agent.run({"goal": "ship it"})

    body = json.loads(route.calls[0].request.content)
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("depth,expected_tokens", [("quick", 400), ("medium", 800), ("deep", 800)])
@pytest.mark.asyncio
async def test_run_caps_max_tokens_by_depth_within_the_account_s_otpm_budget(moto_cache_table, depth, expected_tokens):
    """The previous depth->token map went up to 2048 for "deep" alone —
    more output tokens than this Groq tier allows in an entire minute (1000
    OTPM). Every depth must stay at or under QueryEngine's own safe ceiling."""
    agent = PlanAgent(session_id="s1")
    with respx.mock:
        route = respx.post(GROQ_URL).mock(return_value=_groq_json_response({"steps": []}))
        await agent.run({"goal": "ship it", "depth": depth})

    body = json.loads(route.calls[0].request.content)
    assert body["max_tokens"] == expected_tokens
    assert body["max_tokens"] <= 800


@pytest.mark.asyncio
async def test_run_returns_an_error_for_a_missing_goal(moto_cache_table):
    agent = PlanAgent(session_id="s1")
    result = await agent.run({})
    assert result == {"error": "No goal provided to PlanAgent"}


@pytest.mark.asyncio
async def test_run_falls_back_to_a_single_step_plan_on_llm_failure(moto_cache_table):
    agent = PlanAgent(session_id="s1")
    with respx.mock:
        respx.post(GROQ_URL).mock(return_value=Response(401, json={"error": {"message": "bad key"}}))
        result = await agent.run({"goal": "ship it"})

    assert result["plan"]["steps"] == [{"n": 1, "action": "ship it", "tool": "general", "expected_output": "completion"}]
    assert "error" in result["plan"]
