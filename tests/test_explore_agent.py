import pytest

from agents.explore import ExploreAgent


@pytest.mark.asyncio
async def test_run_code_scope_finds_a_real_match_in_this_deployed_source(tmp_path, monkeypatch):
    """No LLM call, no external service — a local grep over SEMBLANCE's own
    deployed source, always safe to run from a live chat message."""
    monkeypatch.chdir("/home/user/Sem")
    agent = ExploreAgent(session_id="s1")
    result = await agent.run({"query": "_DEFAULT_MAX_TOKENS", "scope": "code"})

    assert result["scope"] == "code"
    matches = result["results"]["code"]
    assert any("query_engine.py" in m["file"] for m in matches)
    assert "web" not in result["results"]
    assert "memory" not in result["results"]


@pytest.mark.asyncio
async def test_run_code_scope_returns_no_matches_for_a_nonsense_term(monkeypatch):
    monkeypatch.chdir("/home/user/Sem")
    agent = ExploreAgent(session_id="s1")
    result = await agent.run({"query": "xyzzy_not_a_real_symbol_anywhere", "scope": "code"})
    assert result["results"]["code"] == []


@pytest.mark.asyncio
async def test_run_code_scope_caps_at_20_matches(monkeypatch):
    monkeypatch.chdir("/home/user/Sem")
    agent = ExploreAgent(session_id="s1")
    # "def" appears far more than 20 times across pipeline/agents/tools/etc.
    result = await agent.run({"query": "def ", "scope": "code"})
    assert len(result["results"]["code"]) <= 20


@pytest.mark.asyncio
async def test_web_search_routes_through_call_tool_and_is_auditable(monkeypatch):
    """Step 5: a sub-agent's tool calls go through pipeline.tool_execution,
    not a tool instantiated and called directly — see agents/explore.py's
    _web_search."""
    calls = []

    class FakeRegistry:
        def get(self, name):
            return {"handler": None}

        async def execute(self, tool_name, args, trust_mode="AUTO"):
            calls.append((tool_name, args, trust_mode))
            return [{"title": "result 1"}]

    async def fake_get_store():
        class Store:
            async def save_agent_event(self, *a, **kw):
                pass
        return Store()

    monkeypatch.setattr("pipeline.tool_execution.get_registry", lambda: FakeRegistry())
    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    monkeypatch.setattr("pipeline.tool_execution._execution", None)

    agent = ExploreAgent(tools_registry=FakeRegistry(), session_id="s1")
    result = await agent.run({"query": "chess openings", "scope": "web"})

    assert result["results"]["web"] == [{"title": "result 1"}]
    assert calls == [("web_search", {"query": "chess openings", "num": 5}, "AUTO")]
