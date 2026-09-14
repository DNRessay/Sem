import pytest

from pipeline.bash_intent import (
    bash_status_label,
    detect_bash_intent,
    format_bash_result,
    run_bash_intent,
)


def test_detect_bash_intent_finds_explicit_trigger_phrasings():
    assert detect_bash_intent("run bash: echo hi") == "echo hi"
    assert detect_bash_intent("run command: ls -la") == "ls -la"
    assert detect_bash_intent("run this command pwd") == "pwd"
    assert detect_bash_intent("execute command: whoami") == "whoami"
    assert detect_bash_intent("bash: echo test") == "echo test"


def test_detect_bash_intent_returns_none_for_ordinary_run_execute_phrasing():
    """"run"/"execute" alone are common ordinary words ("run the numbers",
    "execute the plan") — must not fire without the explicit bash/command
    pairing."""
    assert detect_bash_intent("can you run the numbers on this") is None
    assert detect_bash_intent("let's execute the plan") is None
    assert detect_bash_intent("hey, how's it going?") is None


def test_bash_status_label():
    assert bash_status_label() == "Running…"


def test_format_bash_result_renders_stdout_and_exit_code():
    out = format_bash_result({"blocked": False, "stdout": "hello\n", "stderr": "", "exit_code": 0})
    assert "hello" in out
    assert "Exit code: 0" in out


def test_format_bash_result_renders_stderr_too():
    out = format_bash_result({"blocked": False, "stdout": "", "stderr": "oops\n", "exit_code": 1})
    assert "oops" in out
    assert "stderr" in out.lower()


def test_format_bash_result_notes_no_output():
    out = format_bash_result({"blocked": False, "stdout": "", "stderr": "", "exit_code": 0})
    assert "no output" in out.lower()


def test_format_bash_result_shows_the_blocked_reason():
    out = format_bash_result({
        "blocked": True, "failed_checks": ["no_rm_rf"], "error": "Command blocked by security gate: no_rm_rf",
    })
    assert "no_rm_rf" in out
    assert "security gate" in out.lower()


def test_format_bash_result_shows_confirmation_required():
    out = format_bash_result({"status": "confirmation_required"})
    assert "trust level" in out.lower()


def test_format_bash_result_shows_a_plain_error():
    out = format_bash_result({"blocked": False, "error": "timed out"})
    assert "timed out" in out


@pytest.mark.asyncio
async def test_run_bash_intent_executes_via_the_registry_with_bypass_trust(monkeypatch):
    """BYPASS here skips only the registry's soft write-heuristic, not
    BashTool's own 23 hardcoded checks (those run unconditionally inside
    BashTool.execute itself, regardless of trust_mode) — see the docstring
    in pipeline/bash_intent.py for the full reasoning."""
    calls = []

    class FakeRegistry:
        async def execute(self, tool_name, args, trust_mode="AUTO"):
            calls.append((tool_name, args, trust_mode))
            return {"blocked": False, "stdout": "ok\n", "stderr": "", "exit_code": 0}

    async def fake_get_store():
        class Store:
            async def save_agent_event(self, *a, **kw):
                pass
        return Store()

    monkeypatch.setattr("pipeline.tool_execution.get_registry", lambda: FakeRegistry())
    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    monkeypatch.setattr("pipeline.tool_execution._execution", None)

    result = await run_bash_intent("echo hi", "sess1")

    assert result == {"blocked": False, "stdout": "ok\n", "stderr": "", "exit_code": 0}
    assert calls == [("bash", {"command": "echo hi"}, "BYPASS")]
