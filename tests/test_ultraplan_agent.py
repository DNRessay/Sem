import pytest
import respx
from httpx import Response

from agents.ultraplan import UltraPlanAgent

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _groq_response(content: str):
    return Response(200, json={
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}]
    })


@pytest.mark.asyncio
async def test_run_returns_the_plan_text():
    agent = UltraPlanAgent(session_id="s1")
    with respx.mock:
        route = respx.post(GROQ_URL).mock(return_value=_groq_response("Step 1: do the thing."))
        result = await agent.run({"query": "ship the feature"})

    assert result == {"status": "complete", "goal": "ship the feature", "plan": "Step 1: do the thing."}
    assert route.called


@pytest.mark.asyncio
async def test_run_uses_the_free_chain_with_a_big_budget(monkeypatch):
    seen = {}

    async def fake_complete(choice, messages, tools=None, max_tokens=0, **kw):
        seen.update(choice=choice, max_tokens=max_tokens)
        return {"role": "assistant", "content": "plan"}

    monkeypatch.setattr("agents.ultraplan.llm_providers.complete", fake_complete)
    await UltraPlanAgent(session_id="s1").run({"query": "ship it"})
    assert seen == {"choice": "auto", "max_tokens": 4096}


@pytest.mark.asyncio
async def test_run_returns_an_error_for_a_missing_goal():
    agent = UltraPlanAgent(session_id="s1")
    result = await agent.run({})
    assert result == {"error": "No goal provided to UltraPlanAgent"}


@pytest.mark.asyncio
async def test_run_never_raises_and_never_blocks_on_a_groq_error():
    """The original design polled for up to 30 minutes on any failure —
    that alone would blow Lambda's 30s timeout. A single bad response must
    come back immediately as an error string, not raise or hang."""
    agent = UltraPlanAgent(session_id="s1")
    with respx.mock:
        respx.post(GROQ_URL).mock(return_value=Response(401, json={"error": {"message": "bad key"}}))
        result = await agent.run({"query": "ship it"})

    assert result["status"] == "complete"
    assert "Planning failed" in result["plan"]
    assert "bad key" in result["plan"] or "401" in result["plan"]


@pytest.mark.asyncio
async def test_run_survives_a_network_failure():
    import httpx
    agent = UltraPlanAgent(session_id="s1")
    with respx.mock:
        respx.post(GROQ_URL).mock(side_effect=httpx.ConnectError("connection refused"))
        result = await agent.run({"query": "ship it"})

    assert result["status"] == "complete"
    assert "Planning failed" in result["plan"]


def test_no_leftover_approval_state_or_dead_api():
    """The broken polling-approval flow (and its unreachable approve()/
    get_pending() surface) is gone entirely, not just unused."""
    agent = UltraPlanAgent(session_id="s1")
    assert not hasattr(agent, "approve")
    assert not hasattr(agent, "get_pending")
    assert not hasattr(agent, "_pending_approval")
