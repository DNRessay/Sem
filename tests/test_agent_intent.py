import pytest

from pipeline.agent_intent import (
    detect_explore_intent,
    detect_plan_intent,
    explore_status_label,
    format_matches,
    format_plan,
    plan_status_label,
    run_explore_intent,
    run_plan_intent,
)


def test_detect_plan_intent_finds_planning_phrasings():
    assert detect_plan_intent("make a plan for launching the bot") is not None
    assert detect_plan_intent("help me plan the migration") is not None
    assert detect_plan_intent("plan out the deployment") is not None
    assert detect_plan_intent("what are the steps to ship this") is not None
    assert detect_plan_intent("steps to complete onboarding") is not None


def test_detect_plan_intent_returns_the_full_query_as_goal():
    q = "make a plan for launching the WhatsApp bot"
    assert detect_plan_intent(q) == q


def test_detect_plan_intent_returns_none_for_ordinary_chat():
    assert detect_plan_intent("hey, how's it going?") is None
    assert detect_plan_intent("what's the weather like") is None


def test_detect_explore_intent_finds_code_search_phrasing():
    assert detect_explore_intent("search the code for save_turn") == "save_turn"
    assert detect_explore_intent("grep the source for GROQ_MODEL") == "GROQ_MODEL"
    assert detect_explore_intent("find in the code: detect_web_intent") == "detect_web_intent"


def test_detect_explore_intent_does_not_collide_with_repo_grep_phrasing():
    """"search the codebase for X"/"search the repo for X" belongs to
    pipeline.repo_context's _GREP_RE (an externally attached repo) —
    detect_explore_intent must not also fire on the same phrasing, since
    router.py checks repo_intent first and explore_intent is only meant to
    cover the "code"/"source" wording repo_intent doesn't already own."""
    assert detect_explore_intent("search the codebase for TODO") is None
    assert detect_explore_intent("search the repo for TODO") is None


def test_detect_explore_intent_returns_none_for_ordinary_chat():
    assert detect_explore_intent("hey, how's it going?") is None


def test_status_labels():
    assert plan_status_label() == "Planning…"
    assert "TODO" in explore_status_label("TODO")


def test_format_plan_renders_steps_risks_and_success_criteria():
    plan = {
        "steps": [
            {"n": 1, "action": "Set up env vars", "tool": "bash"},
            {"n": 2, "action": "Deploy", "tool": None},
        ],
        "risks": ["Rate limit"],
        "success_criteria": "Bot responds to messages",
    }
    out = format_plan(plan)
    assert "1. Set up env vars _(tool: bash)_" in out
    assert "2. Deploy" in out
    assert "Rate limit" in out
    assert "Bot responds to messages" in out


def test_format_plan_returns_empty_string_for_empty_plan():
    assert format_plan({}) == ""
    assert format_plan({"steps": []}) == ""


def test_format_matches_lists_file_line_and_content():
    matches = [{"file": "pipeline/query_engine.py", "line": 25, "content": "_DEFAULT_MAX_TOKENS = 800"}]
    out = format_matches("_DEFAULT_MAX_TOKENS", matches)
    assert "pipeline/query_engine.py:25" in out
    assert "_DEFAULT_MAX_TOKENS = 800" in out


def test_format_matches_returns_empty_string_for_no_matches():
    assert format_matches("nothing", []) == ""


class _FakeStore:
    def __init__(self):
        self.saved = []

    async def save_plan(self, session_id, goal, steps):
        self.saved.append((session_id, goal, steps))


@pytest.mark.asyncio
async def test_run_plan_intent_routes_through_cables_man_and_returns_the_plan(monkeypatch):
    calls = []
    store = _FakeStore()

    class FakeCablesMan:
        async def route(self, task):
            calls.append(task)
            return {"status": "complete", "result": {}, "plan": {"steps": [{"n": 1, "action": "do it"}]}}

    async def fake_get_store():
        return store

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    result = await run_plan_intent("plan the launch", "sess1")
    assert result == {"steps": [{"n": 1, "action": "do it"}]}
    assert calls == [{"query": "plan the launch", "agent": "plan", "goal": "plan the launch", "session_id": "sess1"}]


@pytest.mark.asyncio
async def test_run_plan_intent_persists_the_plan_so_continue_can_find_it_later(monkeypatch):
    store = _FakeStore()

    class FakeCablesMan:
        async def route(self, task):
            return {"status": "complete", "plan": {"steps": [{"n": 1, "action": "do it"}]}}

    async def fake_get_store():
        return store

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    await run_plan_intent("plan the launch", "sess1")
    assert store.saved == [("sess1", "plan the launch", [{"n": 1, "action": "do it"}])]


@pytest.mark.asyncio
async def test_run_plan_intent_does_not_persist_when_there_are_no_steps(monkeypatch):
    store = _FakeStore()

    class FakeCablesMan:
        async def route(self, task):
            return {"status": "complete", "plan": {}}

    async def fake_get_store():
        return store

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    await run_plan_intent("plan the launch", "sess1")
    assert store.saved == []


@pytest.mark.asyncio
async def test_run_plan_intent_returns_empty_dict_on_error(monkeypatch):
    class FakeCablesMan:
        async def route(self, task):
            return {"error": "boom"}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    result = await run_plan_intent("plan the launch", "sess1")
    assert result == {}


@pytest.mark.asyncio
async def test_run_explore_intent_routes_through_cables_man_and_returns_matches(monkeypatch):
    calls = []

    class FakeCablesMan:
        async def route(self, task):
            calls.append(task)
            return {"results": {"code": [{"file": "a.py", "line": 1, "content": "x"}]}}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    result = await run_explore_intent("x", "sess1")
    assert result == [{"file": "a.py", "line": 1, "content": "x"}]
    assert calls == [{"query": "x", "agent": "explore", "scope": "code", "session_id": "sess1"}]


@pytest.mark.asyncio
async def test_run_explore_intent_returns_empty_list_on_failure(monkeypatch):
    class FakeCablesMan:
        async def route(self, task):
            return {"error": "boom"}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    result = await run_explore_intent("x", "sess1")
    assert result == []
