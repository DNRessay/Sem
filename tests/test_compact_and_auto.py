import pytest
from fastapi.testclient import TestClient

from gateway.auth import require_account
from main import app


def test_compact_summarises_with_the_picked_model(monkeypatch):
    seen = {}

    async def fake_complete(choice, messages, tools=None, **kw):
        seen["choice"], seen["prompt"] = choice, messages[0]["content"]
        return {"role": "assistant", "content": "- wants a pricing page\n- branch sem/app-1"}

    monkeypatch.setattr("gateway.compact_router.llm_providers.complete", fake_complete)
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    try:
        c = TestClient(app)
        r = c.post("/compact", json={"model": "gemini", "messages": [
            {"role": "user", "content": "add a pricing page"}, {"role": "assistant", "content": "done on sem/app-1"}]})
        assert r.json()["summary"].startswith("- wants") and seen["choice"] == "gemini"
        assert "add a pricing page" in seen["prompt"]
        assert c.post("/compact", json={"messages": []}).status_code == 400
    finally:
        app.dependency_overrides.pop(require_account, None)


@pytest.mark.asyncio
async def test_auto_mode_pushes_its_own_branch_but_still_asks_to_merge(monkeypatch):
    from agents.code_agent import CodeAgent
    from tools.code_workspace import CodeWorkspace

    ran = []

    async def fake_action(ws, token, name, args):
        ran.append((name, args))
        return {"ok": True}

    monkeypatch.setattr("pipeline.code_tasks.run_code_action", fake_action)
    agent = CodeAgent(CodeWorkspace("github", "me/app"), mode="auto", pr_token="t", branch="sem/app-1")
    assert (await agent.dispatch("push_branch", {"message": "x"}))["ok"]
    assert ran == [("push_branch", {"message": "x", "branch": "sem/app-1"})]
    assert (await agent.dispatch("push_branch", {"branch": "main", "message": "x"}))["status"].startswith("waiting")
    assert (await agent.dispatch("merge_pr", {"number": 1}))["status"].startswith("waiting")
    act = CodeAgent(CodeWorkspace("github", "me/app"), mode="act", pr_token="t", branch="sem/app-1")
    assert (await act.dispatch("rerun_ci", {"run_id": 3}))["status"].startswith("waiting")
