import json

import pytest

from agents.plan_agent import PlanAgent


def _fake(content=None, error=None):
    async def complete(choice, messages, tools=None, max_tokens=0, **kw):
        complete.calls.append((choice, max_tokens))
        return {"error": error} if error else {"role": "assistant", "content": content}
    complete.calls = []
    return complete


@pytest.mark.asyncio
async def test_run_returns_the_parsed_plan(monkeypatch):
    plan_obj = {"steps": [{"n": 1, "action": "do it", "tool": "bash", "expected_output": "done"}],
                "risks": [], "success_criteria": "it's done"}
    fake = _fake("Here you go:\n" + json.dumps(plan_obj))
    monkeypatch.setattr("agents.plan_agent.llm_providers.complete", fake)
    result = await PlanAgent(session_id="s1").run({"goal": "ship the feature", "depth": "deep"})
    assert result["status"] == "complete" and result["plan"] == plan_obj
    assert fake.calls == [("auto", 2400)]


@pytest.mark.asyncio
async def test_a_failure_is_reported_not_disguised_as_a_plan(monkeypatch):
    monkeypatch.setattr("agents.plan_agent.llm_providers.complete", _fake(error="rate limited"))
    result = await PlanAgent(session_id="s1").run({"goal": "ship it"})
    assert result["status"] == "error" and "plan" not in result
    monkeypatch.setattr("agents.plan_agent.llm_providers.complete", _fake("no json here"))
    assert (await PlanAgent(session_id="s1").run({"goal": "ship it"}))["status"] == "error"


@pytest.mark.asyncio
async def test_empty_goal():
    assert await PlanAgent(session_id="s1").run({"goal": ""}) == {"error": "No goal provided to PlanAgent"}
