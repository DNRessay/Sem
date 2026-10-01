import json

import pytest
from fastapi.testclient import TestClient

from gateway.auth import require_account
from main import app
from pipeline import code_tasks


class FakeStore:
    def __init__(self):
        self.connectors = {("owner", "github"): {"token": "gh-token"}}
        self.automations = []
        self.results = {}

    async def get_connector(self, account_id, provider):
        c = self.connectors.get((account_id, provider))
        return {"provider": provider, **c} if c else None

    async def list_code_automations(self, account_id):
        return [a for a in self.automations if a["account_id"] == account_id]

    async def create_code_automation(self, account_id, provider, repo, prompt, every_seconds, open_pr):
        row = {"id": len(self.automations) + 1, "account_id": account_id, "provider": provider, "repo": repo,
               "prompt": prompt, "every_seconds": every_seconds, "open_pr": open_pr, "enabled": True}
        self.automations.append(row)
        return row

    async def list_mcp_servers(self, account_id):
        return []

    async def claim_due_code_automation(self):
        return self.automations[0] if self.automations else None

    async def set_code_automation_result(self, automation_id, result):
        self.results[automation_id] = result


class FakeWorkspace:
    def __init__(self, provider="github", repo="me/app", files=None):
        self.provider, self.repo = provider, repo
        self.files = files if files is not None else {"app.py": "fixed\n"}
        self.log = []

    async def open(self, token, ref=""):
        self.log.append(("open", token))
        return {"ok": True}

    async def list_dir(self, path=""):
        return {"ok": True, "entries": ["app.py"]}

    async def changes(self):
        return {"ok": True, "files": self.files, "deleted": [], "stat": " app.py | 2 +-"}

    async def discard(self):
        self.log.append(("discard",))
        return {"ok": True}


class FakeWriter:
    calls = []

    async def get_default_branch(self, provider, repo, token):
        return "main"

    async def create_branch(self, provider, repo, branch, base, token):
        self.calls.append(("branch", branch, base, token))
        return {"ok": True}

    async def commit_file(self, provider, repo, branch, path, content, message, token):
        self.calls.append(("commit", path, content))
        return {"ok": True}

    async def create_pull_request(self, provider, repo, head, base, title, body, token):
        self.calls.append(("pr", head, base, title))
        return {"ok": True, "url": "https://github.com/me/app/pull/7", "number": 7}


@pytest.fixture
def store(monkeypatch):
    s = FakeStore()

    async def fake_get_store():
        return s

    monkeypatch.setattr("pipeline.code_tasks.get_store", fake_get_store)
    monkeypatch.setattr("gateway.code_router.get_store", fake_get_store)
    monkeypatch.setattr("pipeline.mcp_tools.get_store", fake_get_store)
    FakeWriter.calls = []
    monkeypatch.setattr("pipeline.code_tasks.RepoWriteTool", FakeWriter)
    return s


def test_valid_target():
    assert code_tasks.valid_target("github", "me/app")
    assert code_tasks.valid_target("gitlab", "group/sub/app")
    assert not code_tasks.valid_target("github", "app")
    assert not code_tasks.valid_target("bitbucket", "me/app")
    assert not code_tasks.valid_target("github", "me/app; rm -rf /")
    assert not code_tasks.valid_target("github", "../etc")
    assert not code_tasks.valid_target("github", "me/../../x")


@pytest.mark.asyncio
async def test_open_pr_commits_changes_to_a_new_branch(store):
    pr = await code_tasks.open_pr(FakeWorkspace(), "gh-token", "Fix add")
    assert pr["ok"] and pr["url"].endswith("/pull/7")
    kinds = [c[0] for c in FakeWriter.calls]
    assert kinds == ["branch", "commit", "pr"]
    assert FakeWriter.calls[0][1].startswith("sem-code/fix-add-") and FakeWriter.calls[0][2] == "main"


@pytest.mark.asyncio
async def test_open_pr_refuses_when_nothing_changed(store):
    pr = await code_tasks.open_pr(FakeWorkspace(files={}), "gh-token", "x")
    assert pr == {"ok": False, "error": "No changes to open a PR with."}
    assert FakeWriter.calls == []


@pytest.mark.asyncio
async def test_due_automation_runs_opens_a_pr_and_resets(store, monkeypatch):
    await store.create_code_automation("owner", "github", "me/app", "bump deps", 86400, True)
    ws = FakeWorkspace()
    monkeypatch.setattr("pipeline.code_tasks.CodeWorkspace", lambda provider, repo: ws)

    class FakeAgent:
        def __init__(self, *a, **k):
            pass

        async def run(self, task):
            yield {"type": "text", "text": "Bumped 2 deps, tests pass."}
            yield {"type": "done", "steps": 3}

    monkeypatch.setattr("pipeline.code_tasks.CodeAgent", FakeAgent)
    result = await code_tasks.run_due_automation()

    assert "pull/7" in result["result"] and "Bumped 2 deps" in result["result"]
    assert ws.log == [("discard",), ("open", "gh-token"), ("discard",)]
    assert "pull/7" in store.results[1]


@pytest.mark.asyncio
async def test_no_due_automation_is_a_no_op(store):
    assert await code_tasks.run_due_automation() is None


@pytest.fixture
def client(store, monkeypatch):
    ws = FakeWorkspace()
    monkeypatch.setattr("gateway.code_router.CodeWorkspace", lambda provider, repo: ws)
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app), ws
    app.dependency_overrides.pop(require_account, None)


def test_open_uses_the_connector_token(client):
    c, ws = client
    r = c.post("/code/open", json={"provider": "github", "repo": "me/app"})
    assert r.status_code == 200 and r.json()["entries"] == ["app.py"] and r.json()["can_open_pr"]
    assert ws.log == [("open", "gh-token")]


def test_bad_repo_is_rejected(client):
    c, _ = client
    assert c.post("/code/open", json={"provider": "github", "repo": "../etc"}).status_code == 400


def test_run_streams_agent_events(client, monkeypatch):
    c, _ = client

    class FakeAgent:
        def __init__(self, ws, mode="act", provider="auto", mcp=None):
            self.mode = mode

        async def run(self, message, history):
            yield {"type": "text", "text": f"{self.mode}:{message}"}
            yield {"type": "done", "steps": 1}

    monkeypatch.setattr("gateway.code_router.CodeAgent", FakeAgent)
    r = c.post("/code/run", json={"provider": "github", "repo": "me/app", "message": "hi", "mode": "plan"})
    lines = [line[6:] for line in r.text.split("\n") if line.startswith("data: ")]
    assert json.loads(lines[0]) == {"type": "text", "text": "plan:hi"}
    assert lines[-1] == "[DONE]"


def test_pr_endpoint_returns_the_url(client):
    c, _ = client
    r = c.post("/code/pr", json={"provider": "github", "repo": "me/app", "title": "Fix"})
    assert r.status_code == 200 and r.json()["url"].endswith("/pull/7")


def test_automation_create_validates_schedule(client):
    c, _ = client
    bad = c.post("/code/automations", json={"provider": "github", "repo": "me/app", "prompt": "x", "every": "minutely"})
    assert bad.status_code == 400
    ok = c.post("/code/automations", json={"provider": "github", "repo": "me/app", "prompt": "x", "every": "weekly"})
    assert ok.json()["automation"]["every_seconds"] == 7 * 86400
    assert len(c.get("/code/automations").json()["automations"]) == 1
