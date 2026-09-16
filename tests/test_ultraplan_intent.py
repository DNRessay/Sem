import pytest

from pipeline.ultraplan_intent import (
    detect_ultraplan_intent,
    format_ultraplan_result,
    run_ultraplan_intent,
    ultraplan_status_label,
)


def test_detect_ultraplan_intent_finds_deep_planning_phrasings():
    assert detect_ultraplan_intent("deep plan for the migration") is not None
    assert detect_ultraplan_intent("ultraplan the launch") is not None
    assert detect_ultraplan_intent("think hard about how to scale this") is not None
    assert detect_ultraplan_intent("do a deep dive on the architecture") is not None
    assert detect_ultraplan_intent("really think through the tradeoffs") is not None


def test_detect_ultraplan_intent_returns_the_full_query():
    q = "deep plan for launching the WhatsApp bot"
    assert detect_ultraplan_intent(q) == q


def test_detect_ultraplan_intent_returns_none_for_ordinary_plan_requests():
    """Must not fire on plain "make a plan for X" — that stays PlanAgent's,
    the quicker/cheaper path."""
    assert detect_ultraplan_intent("make a plan for launching the bot") is None
    assert detect_ultraplan_intent("help me plan the migration") is None


def test_detect_ultraplan_intent_returns_none_for_ordinary_chat():
    assert detect_ultraplan_intent("hey, how's it going?") is None


def test_status_label():
    assert "GPT-OSS-120B" in ultraplan_status_label()


@pytest.mark.asyncio
async def test_run_ultraplan_intent_routes_through_cables_man(monkeypatch):
    calls = []

    class FakeCablesMan:
        async def route(self, task):
            calls.append(task)
            return {"status": "complete", "goal": task["query"], "plan": "the deep plan"}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    result = await run_ultraplan_intent("deep plan for X", "sess1")

    assert result == {"status": "complete", "goal": "deep plan for X", "plan": "the deep plan"}
    assert calls == [{"query": "deep plan for X", "agent": "ultraplan", "session_id": "sess1"}]


@pytest.mark.asyncio
async def test_run_ultraplan_intent_returns_empty_dict_on_error(monkeypatch):
    class FakeCablesMan:
        async def route(self, task):
            return {"error": "boom"}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    result = await run_ultraplan_intent("deep plan for X", "sess1")
    assert result == {}


def test_format_ultraplan_result_renders_the_plan():
    out = format_ultraplan_result({"plan": "1. Do X\n2. Do Y"})
    assert "Deep Plan" in out
    assert "1. Do X" in out


def test_format_ultraplan_result_empty_when_no_plan():
    assert format_ultraplan_result({}) == ""
    assert format_ultraplan_result({"plan": ""}) == ""
