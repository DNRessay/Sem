import json

import pytest

from pipeline import bootstrap as bootstrap_mod
from pipeline import chat_tools


@pytest.mark.asyncio
async def test_chat_model_calls_a_tool_then_answers(monkeypatch):
    replies = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "search_memory", "arguments": json.dumps({"term": "ams"})}}]},
        {"role": "assistant", "content": "You told me AMS is Abel Motshoane Secondary."},
    ]
    seen = []

    async def fake_complete(provider, messages, tools=None, **kw):
        seen.append((provider, [t["function"]["name"] for t in tools or []], messages[-1]))
        return replies.pop(0)

    async def fake_available(session_id, query="", recent=None, repo=None):
        return chat_tools.BASE, None

    async def fake_run(name, args, session_id, active):
        return {"matches": [{"text": "ams is abel motshoane"}]}

    monkeypatch.setattr(bootstrap_mod.llm_providers, "complete", fake_complete)
    monkeypatch.setattr(chat_tools, "available", fake_available)
    monkeypatch.setattr(chat_tools, "run", fake_run)

    b = bootstrap_mod.Bootstrap.__new__(bootstrap_mod.Bootstrap)
    out = [p async for p in b._tool_reply([{"role": "user", "content": "do you remember ams"}], "s1", "bonsai") if not (isinstance(p, dict) and "usage" in p)]

    assert out[0]["tool"]["kind"] == "memory" and "ams" in out[0]["tool"]["label"]
    assert out[1] == "You told me AMS is Abel Motshoane Secondary."
    assert "search_memory" in seen[0][1] and seen[0][0] == "bonsai"
    assert seen[1][2]["role"] == "tool" and seen[1][2]["tool_call_id"] == "c1"


@pytest.mark.asyncio
async def test_repo_tools_only_with_an_attached_repo(monkeypatch):
    class Store:
        def __init__(self, active):
            self.active = active

        async def get_active_repo(self, session_id):
            return self.active

    async def none_store():
        return Store(None)

    monkeypatch.setattr(chat_tools, "get_store", none_store)
    tools, _ = await chat_tools.available("s")
    assert "repo_read" not in [t["function"]["name"] for t in tools]
    result = await chat_tools.run("repo_read", {"path": "README.md"}, "s", None)
    assert "attach" in result["error"]


@pytest.mark.asyncio
async def test_deep_research_tool_returns_the_cited_answer(monkeypatch):
    from agents import research_agent

    async def fake_run(self, task, history=None):
        assert self.max_steps == 8
        yield {"type": "tool", "id": "1", "name": "fetch_url", "args": {"url": "https://a"}}
        yield {"type": "text", "text": "Answer [1]"}
        yield {"type": "done", "steps": 2, "model": "bonsai"}

    monkeypatch.setattr(research_agent.ResearchAgent, "run", fake_run)
    assert "deep_research" in [t["function"]["name"] for t in chat_tools.BASE]
    out = await chat_tools.run("deep_research", {"question": "best x?"}, "s1", None)
    assert out == {"ok": True, "answer": "Answer [1]", "pages_read": ["https://a"]}
    assert (await research_agent.deep_research("  "))["ok"] is False


@pytest.mark.asyncio
async def test_chat_reports_tokens_used(monkeypatch):
    async def fake_complete(provider, messages, tools=None, **kw):
        return {"role": "assistant", "content": "hi", "_tokens": 120}

    async def fake_available(session_id, query="", recent=None, repo=None):
        return chat_tools.BASE, None

    monkeypatch.setattr(bootstrap_mod.llm_providers, "complete", fake_complete)
    monkeypatch.setattr(chat_tools, "available", fake_available)
    b = bootstrap_mod.Bootstrap.__new__(bootstrap_mod.Bootstrap)
    out = [p async for p in b._tool_reply([{"role": "user", "content": "hi"}], "s1", "bonsai")]
    assert out == [{"usage": 120}, "hi"]


def test_token_estimate_when_provider_is_silent():
    from pipeline import llm_providers
    assert llm_providers.estimate_tokens([{"content": "a" * 400}], {"content": "b" * 40}) == 110


@pytest.mark.asyncio
async def test_repo_tools_join_only_when_the_turn_is_about_code(monkeypatch):
    class Store:
        async def get_active_repo(self, session_id):
            return {"provider": "github", "repo": "o/r"}

    async def store():
        return Store()

    monkeypatch.setattr(chat_tools, "get_store", store)
    names = lambda tools: [t["function"]["name"] for t in tools]  # noqa: E731
    assert "repo_read" not in names((await chat_tools.available("s", "plan my weekend"))[0])
    assert "repo_read" in names((await chat_tools.available("s", "what does main.py do?"))[0])
