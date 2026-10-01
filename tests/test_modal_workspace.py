import importlib
import subprocess
import sys
import types

import pytest


class _Chain:
    def __getattr__(self, _name):
        return lambda *a, **k: self


def _passthrough(*_a, **_k):
    return lambda obj: obj


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """modal_app/repo_tool.py's file/bash actions against a real git repo,
    with the `modal` package stubbed out (it isn't installed for tests)."""
    fake = types.ModuleType("modal")
    fake.App = lambda *a, **k: types.SimpleNamespace(cls=_passthrough)
    fake.Image = types.SimpleNamespace(debian_slim=lambda *a, **k: _Chain())
    fake.Volume = types.SimpleNamespace(from_name=lambda *a, **k: types.SimpleNamespace(commit=lambda: None))
    fake.Secret = types.SimpleNamespace(from_name=lambda *a, **k: None)
    fake.fastapi_endpoint = _passthrough
    monkeypatch.setitem(sys.modules, "modal", fake)
    sys.modules.pop("modal_app.repo_tool", None)
    mod = importlib.import_module("modal_app.repo_tool")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n")
    for cmd in (["init", "-q"], ["add", "."], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    yield mod.RepoTool(), str(repo)
    sys.modules.pop("modal_app.repo_tool", None)


def test_edit_then_changes_reports_the_new_content(workspace):
    tool, repo = workspace
    assert tool._edit_file(repo, "app.py", "a - b", "a + b", False)["ok"]
    changes = tool._changes(repo)
    assert changes["files"] == {"app.py": "def add(a, b):\n    return a + b\n"}


def test_edit_rejects_ambiguous_and_missing_text(workspace):
    tool, repo = workspace
    tool._write_file(repo, "x.txt", "same same")
    assert "2 places" in tool._edit_file(repo, "x.txt", "same", "diff", False)["error"]
    assert "not found" in tool._edit_file(repo, "x.txt", "nope", "diff", False)["error"]
    assert tool._edit_file(repo, "x.txt", "same", "diff", True)["replacements"] == 2


def test_paths_cannot_escape_the_repo_or_touch_git(workspace):
    tool, repo = workspace
    assert tool._write_file(repo, "../outside.txt", "x")["error"] == "invalid path"
    assert tool._write_file(repo, ".git/config", "x")["error"] == "invalid path"
    assert tool._read_file(repo, "../../etc/passwd")["error"] == "invalid path"


def test_bash_runs_in_the_repo_with_a_bare_environment(workspace, monkeypatch):
    tool, repo = workspace
    monkeypatch.setenv("REPO_TOOL_SECRET", "must-not-leak")
    result = tool._bash(repo, "ls && echo SECRET=${REPO_TOOL_SECRET:-unset}", 30)
    assert result["ok"]
    assert "app.py" in result["output"]
    assert "SECRET=unset" in result["output"]


def test_bash_reports_failure_and_timeout(workspace):
    tool, repo = workspace
    failed = tool._bash(repo, "exit 3", 30)
    assert failed["ok"] is False and failed["exit_code"] == 3
    slow = tool._bash(repo, "sleep 5", 1)
    assert "timed out" in slow["error"]


def test_discard_reverts_edits_and_new_files(workspace):
    tool, repo = workspace
    tool._edit_file(repo, "app.py", "a - b", "a + b", False)
    tool._write_file(repo, "new/file.py", "x = 1\n")
    tool._discard(repo)
    assert tool._changes(repo)["files"] == {}


def test_list_dir_hides_git(workspace):
    tool, repo = workspace
    tool._write_file(repo, "pkg/mod.py", "")
    entries = tool._list_dir(repo, "")["entries"]
    assert entries == ["app.py", "pkg/"]
