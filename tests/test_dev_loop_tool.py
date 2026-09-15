import uuid

import pytest

from tools.dev_loop_tool import DevLoopTool


class FakeBash:
    def __init__(self, exit_code=0, stdout="", stderr="", blocked=False, error=None):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.blocked = blocked
        self.error = error
        self.calls: list[str] = []

    async def execute(self, command, timeout=15, cwd=None):
        self.calls.append(command)
        if self.blocked:
            return {"blocked": True, "failed_checks": ["no_sudo"], "command": command, "error": "blocked"}
        result = {"blocked": False, "stdout": self.stdout, "stderr": self.stderr, "exit_code": self.exit_code}
        if self.error is not None:
            result["error"] = self.error
        return result


class FakeRepoWrite:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls: list[dict] = []

    async def propose_fix(self, **kwargs):
        self.calls.append(kwargs)
        if self.ok:
            return {"ok": True, "url": "https://github.com/me/repo/pull/1", "version": "0.0.1", "branch": "fix/v0.0.1-x"}
        return {"ok": False, "error": "propose_fix failed"}


@pytest.mark.asyncio
async def test_lint_pass_reaches_propose_fix():
    bash = FakeBash(exit_code=0, stdout="All checks passed!")
    repo_write = FakeRepoWrite(ok=True)
    tool = DevLoopTool(bash=bash, repo_write=repo_write)

    result = await tool.check_and_propose_fix(
        provider="github", repo="me/repo", token="tok", level="patch",
        slug="fix bug", files={"agents/buddy.py": "print('hi')"}, commit_message="fix bug",
    )

    assert result["ok"] is True
    assert result["url"] == "https://github.com/me/repo/pull/1"
    assert len(repo_write.calls) == 1
    assert any("python -m ruff check" in c for c in bash.calls)


@pytest.mark.asyncio
async def test_lint_failure_blocks_propose_fix_entirely():
    bash = FakeBash(exit_code=1, stdout="agents/buddy.py:3:1: F401 unused import")
    repo_write = FakeRepoWrite(ok=True)
    tool = DevLoopTool(bash=bash, repo_write=repo_write)

    result = await tool.check_and_propose_fix(
        provider="github", repo="me/repo", token="tok", level="patch",
        slug="fix bug", files={"agents/buddy.py": "import os"}, commit_message="fix bug",
    )

    assert result["ok"] is False
    assert result["gate"] == "lint"
    assert "F401" in result["lint_output"]
    assert repo_write.calls == []  # never reached — the whole point of the gate


@pytest.mark.asyncio
async def test_bash_security_block_also_blocks_propose_fix():
    bash = FakeBash(blocked=True)
    repo_write = FakeRepoWrite(ok=True)
    tool = DevLoopTool(bash=bash, repo_write=repo_write)

    result = await tool.check_and_propose_fix(
        provider="github", repo="me/repo", token="tok", level="patch",
        slug="fix bug", files={"agents/buddy.py": "import os"}, commit_message="fix bug",
    )

    assert result["ok"] is False
    assert result["gate"] == "lint"
    assert repo_write.calls == []


@pytest.mark.asyncio
async def test_non_python_files_skip_the_lint_step_but_still_propose():
    bash = FakeBash(exit_code=0)
    repo_write = FakeRepoWrite(ok=True)
    tool = DevLoopTool(bash=bash, repo_write=repo_write)

    result = await tool.check_and_propose_fix(
        provider="github", repo="me/repo", token="tok", level="patch",
        slug="update docs", files={"README.md": "# hi"}, commit_message="update docs",
    )

    assert result["ok"] is True
    assert bash.calls == []  # nothing to lint, ruff never invoked
    assert len(repo_write.calls) == 1


@pytest.mark.asyncio
async def test_timeout_surfaces_the_error_as_lint_output():
    bash = FakeBash(exit_code=-1, stdout="", stderr="", error="Command timed out after 15s")
    repo_write = FakeRepoWrite(ok=True)
    tool = DevLoopTool(bash=bash, repo_write=repo_write)

    result = await tool.check_and_propose_fix(
        provider="github", repo="me/repo", token="tok", level="patch",
        slug="x", files={"x.py": "y = 1"}, commit_message="fix",
    )

    assert result["ok"] is False
    assert "timed out" in result["lint_output"]
    assert repo_write.calls == []


@pytest.mark.asyncio
async def test_writes_and_cleans_up_the_lint_workdir(monkeypatch):
    fixed_uuid = uuid.UUID("12345678123456781234567812345678")
    monkeypatch.setattr("tools.dev_loop_tool.uuid.uuid4", lambda: fixed_uuid)

    captured = {}

    class InspectingBash(FakeBash):
        async def execute(self, command, timeout=15, cwd=None):
            import os
            workdir = f"/tmp/lint-{fixed_uuid.hex[:8]}"
            nested_file = os.path.join(workdir, "agents", "buddy.py")
            captured["exists_during_run"] = os.path.exists(nested_file)
            captured["content_during_run"] = open(nested_file).read() if captured["exists_during_run"] else None
            captured["workdir"] = workdir
            return await super().execute(command, timeout, cwd)

    bash = InspectingBash(exit_code=0)
    tool = DevLoopTool(bash=bash, repo_write=FakeRepoWrite(ok=True))

    await tool.check_and_propose_fix(
        provider="github", repo="me/repo", token="tok", level="patch",
        slug="x", files={"agents/buddy.py": "x = 1"}, commit_message="fix",
    )

    import os
    assert captured["exists_during_run"] is True
    assert captured["content_during_run"] == "x = 1"
    assert not os.path.exists(captured["workdir"])  # cleaned up after
