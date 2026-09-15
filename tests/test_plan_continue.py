import pytest

from pipeline.plan_continue import (
    continue_status_label,
    detect_continue_intent,
    format_continue_result,
    run_continue_intent,
)


def test_detect_continue_intent_matches_expected_phrasings():
    for msg in ["continue", "Continue", "continue.", "continue!", "continue the plan",
                "continue with the plan", "keep going", "keep going with the plan",
                "next step", "resume plan", "resume the plan"]:
        assert detect_continue_intent(msg) is True, msg


def test_detect_continue_intent_requires_the_whole_message_to_match():
    """Anchored on purpose — "let's continue" or "continue reading this for
    me" contain the trigger word but aren't the bare continue-shaped
    message this is meant to catch, the same false-positive shape already
    fixed once this session for the bash intent's bare "bash" trigger."""
    assert detect_continue_intent("let's continue") is False
    assert detect_continue_intent("continue reading this for me") is False
    assert detect_continue_intent("can you continue the essay") is False
    assert detect_continue_intent("hey, how's it going?") is False


def test_continue_status_label():
    assert continue_status_label() == "Continuing the plan…"


class FakeStore:
    def __init__(self, plan=None):
        self.plan = plan
        self.updates = []

    async def get_active_plan(self, session_id):
        return self.plan

    async def update_plan_step(self, session_id, step_n, status, result=""):
        self.updates.append((session_id, step_n, status, result))
        for s in self.plan["steps"]:
            if s["n"] == step_n:
                s["status"] = status


@pytest.mark.asyncio
async def test_run_continue_intent_with_no_active_plan(monkeypatch):
    store = FakeStore(plan=None)

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    result = await run_continue_intent("sess1")
    assert result == {"done": None}


@pytest.mark.asyncio
async def test_run_continue_intent_when_every_step_is_already_done(monkeypatch):
    store = FakeStore(plan={"goal": "ship it", "steps": [{"n": 1, "action": "x", "status": "done"}]})

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    result = await run_continue_intent("sess1")
    assert result == {"done": True, "goal": "ship it"}


class FakeQueryEngine:
    def __init__(self, content):
        self._content = content

    async def call_llm(self, messages, session_id=None, max_tokens=None, temperature=None):
        return {"content": self._content}


@pytest.mark.asyncio
async def test_run_continue_intent_executes_a_bash_step(monkeypatch):
    store = FakeStore(plan={
        "goal": "deploy the bot",
        "steps": [{"n": 1, "action": "list files", "tool": "bash", "status": "pending"},
                  {"n": 2, "action": "write docs", "tool": "general", "status": "pending"}],
    })

    async def fake_get_store():
        return store

    bash_calls = []

    async def fake_run_bash_intent(command, session_id):
        bash_calls.append((command, session_id))
        return {"blocked": False, "stdout": "a.py\nb.py\n", "stderr": "", "exit_code": 0}

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    monkeypatch.setattr("pipeline.query_engine.QueryEngine", lambda: FakeQueryEngine("ls -la"))
    monkeypatch.setattr("pipeline.bash_intent.run_bash_intent", fake_run_bash_intent)

    result = await run_continue_intent("sess1")

    assert bash_calls == [("ls -la", "sess1")]
    assert result["done"] is False
    assert result["step_n"] == 1
    assert result["command"] == "ls -la"
    assert "a.py" in result["outcome"]
    assert result["remaining"] == 1
    assert result["total"] == 2
    assert store.updates[0][1] == 1
    assert store.updates[0][2] == "done"


@pytest.mark.asyncio
async def test_run_continue_intent_treats_a_non_bash_step_as_narrative_only(monkeypatch):
    store = FakeStore(plan={
        "goal": "ship it",
        "steps": [{"n": 1, "action": "write the README", "tool": "general", "status": "pending"}],
    })

    async def fake_get_store():
        return store

    bash_calls = []

    async def fake_run_bash_intent(command, session_id):
        bash_calls.append(command)
        return {}

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    monkeypatch.setattr("pipeline.query_engine.QueryEngine", lambda: FakeQueryEngine("Wrote a short README summarizing the setup steps."))
    monkeypatch.setattr("pipeline.bash_intent.run_bash_intent", fake_run_bash_intent)

    result = await run_continue_intent("sess1")

    assert bash_calls == []
    assert result["command"] is None
    assert "README" in result["outcome"]
    assert result["remaining"] == 0


def test_format_continue_result_no_active_plan():
    assert "no active plan" in format_continue_result({"done": None}).lower()


def test_format_continue_result_plan_complete():
    out = format_continue_result({"done": True, "goal": "ship it"})
    assert "complete" in out.lower()
    assert "ship it" in out


def test_format_continue_result_shows_the_step_command_and_remaining_count():
    out = format_continue_result({
        "done": False, "step_n": 1, "action": "list files", "command": "ls -la",
        "outcome": "a.py\nb.py", "remaining": 2, "total": 3,
    })
    assert "Step 1 of 3" in out
    assert "ls -la" in out
    assert "a.py" in out
    assert "2 step(s) left" in out


def test_format_continue_result_notes_the_last_step():
    out = format_continue_result({
        "done": False, "step_n": 3, "action": "done", "command": None,
        "outcome": "finished", "remaining": 0, "total": 3,
    })
    assert "last step" in out.lower()
