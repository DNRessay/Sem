import pytest

from pipeline.sub_agent_deleg import SubAgentDelegation


@pytest.mark.asyncio
async def test_fork_routes_each_agent_type_through_cables_man(monkeypatch):
    calls = []

    class FakeCablesMan:
        async def route(self, task):
            calls.append(task["agent"])
            return {"status": "complete", "agent": task["agent"]}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)

    deleg = SubAgentDelegation()
    results = await deleg.fork({"query": "audit the pipeline"}, ["plan", "explore"])

    assert sorted(calls) == ["explore", "plan"]
    assert {r["agent"] for r in results} == {"plan", "explore"}


@pytest.mark.asyncio
async def test_fork_keeps_going_when_one_agent_type_fails(monkeypatch):
    class FakeCablesMan:
        async def route(self, task):
            if task["agent"] == "plan":
                raise RuntimeError("boom")
            return {"status": "complete", "agent": task["agent"]}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)

    deleg = SubAgentDelegation()
    results = await deleg.fork({"query": "x"}, ["plan", "explore"])

    errors = [r for r in results if "error" in r]
    oks = [r for r in results if "error" not in r]
    assert len(errors) == 1
    assert len(oks) == 1


@pytest.mark.asyncio
async def test_teammate_returns_timeout_when_no_result_file_ever_appears(tmp_path, monkeypatch):
    """The mailbox model polls for up to 120s — a real end-to-end run isn't
    something a test suite should wait on, but the timeout path itself
    (no worker ever picks up the task) must resolve cleanly rather than
    hang forever."""
    monkeypatch.setattr(SubAgentDelegation, "MAILBOX_DIR", str(tmp_path))

    async def fast_sleep(_):
        pass

    monkeypatch.setattr("asyncio.sleep", fast_sleep)

    deleg = SubAgentDelegation()
    result = await deleg.teammate({"query": "x"}, "agent-1")
    assert result == {"status": "timeout", "agent": "agent-1"}


@pytest.mark.asyncio
async def test_worktree_creates_a_branch_and_reports_it(monkeypatch):
    import asyncio

    class FakeProc:
        async def wait(self):
            return 0

    async def fake_create_subprocess_shell(cmd, stdout=None, stderr=None):
        assert "git worktree add" in cmd
        assert "my-feature" in cmd
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_create_subprocess_shell)

    deleg = SubAgentDelegation()
    result = await deleg.worktree({"query": "add a feature"}, branch="my-feature")
    assert result == {"status": "worktree_created", "branch": "my-feature", "task": {"query": "add a feature"}}


@pytest.mark.asyncio
async def test_worktree_reports_the_error_instead_of_raising(monkeypatch):
    import asyncio

    async def fake_create_subprocess_shell(cmd, stdout=None, stderr=None):
        raise OSError("git not found")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_create_subprocess_shell)

    deleg = SubAgentDelegation()
    result = await deleg.worktree({"query": "x"}, branch="my-feature")
    assert "error" in result


@pytest.mark.asyncio
async def test_teammate_returns_the_result_once_the_mailbox_is_answered(tmp_path, monkeypatch):
    import asyncio
    import json as jsonlib

    monkeypatch.setattr(SubAgentDelegation, "MAILBOX_DIR", str(tmp_path))

    real_sleep = asyncio.sleep

    async def fake_sleep(_):
        # Simulate a worker answering the mailbox after the first poll.
        result_path = tmp_path / "agent-1_result.json"
        if not result_path.exists():
            result_path.write_text(jsonlib.dumps({"status": "complete", "result": "done"}))
        await real_sleep(0)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    deleg = SubAgentDelegation()
    result = await deleg.teammate({"query": "x"}, "agent-1")
    assert result == {"status": "complete", "result": "done"}
