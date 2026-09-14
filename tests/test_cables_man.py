import pytest

from core.cables_man import CablesMan


class RecordingStore:
    def __init__(self):
        self.events = []

    async def save_agent_event(self, session_id, agent, action):
        self.events.append((session_id, agent, action))


@pytest.fixture
def recording_store(monkeypatch):
    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    return store


def test_classify_routes_by_keyword():
    cables = CablesMan()
    assert cables._classify("help me plan the launch") == "plan"
    assert cables._classify("search the web for chess openings") == "explore"
    assert cables._classify("remind me to check email") == "proactive"
    assert cables._classify("just chatting") == "general"


@pytest.mark.asyncio
async def test_route_spawns_the_classified_agent_and_returns_its_result(monkeypatch, recording_store):
    class FakeAgentTool:
        def __init__(self, tools_registry=None, cables_man_ref=None):
            pass

        async def spawn(self, agent_type, task):
            assert agent_type == "plan"
            return {"status": "complete", "result": {"steps": []}}

    monkeypatch.setattr("tools.agent_tool.AgentTool", FakeAgentTool)

    cables = CablesMan()
    result = await cables.route({"query": "help me plan a launch", "session_id": "s1"})
    assert result == {"status": "complete", "result": {"steps": []}}


@pytest.mark.asyncio
async def test_route_honors_an_explicit_agent_override(monkeypatch, recording_store):
    captured = {}

    class FakeAgentTool:
        def __init__(self, tools_registry=None, cables_man_ref=None):
            pass

        async def spawn(self, agent_type, task):
            captured["agent_type"] = agent_type
            return {"status": "complete"}

    monkeypatch.setattr("tools.agent_tool.AgentTool", FakeAgentTool)

    cables = CablesMan()
    await cables.route({"query": "hello", "agent": "explore", "session_id": "s1"})
    assert captured["agent_type"] == "explore"


@pytest.mark.asyncio
async def test_route_clears_working_mem_only_on_complete(monkeypatch, recording_store):
    class FakeAgentTool:
        def __init__(self, tools_registry=None, cables_man_ref=None):
            pass

        async def spawn(self, agent_type, task):
            return {"status": "max_iterations"}

    monkeypatch.setattr("tools.agent_tool.AgentTool", FakeAgentTool)

    cables = CablesMan()
    await cables.route({"query": "hello", "session_id": "s1"})
    assert cables.working_mem.get("s1") != ""  # not cleared — status wasn't "complete"


@pytest.mark.asyncio
async def test_route_persists_a_routing_and_an_outcome_event(monkeypatch, recording_store):
    class FakeAgentTool:
        def __init__(self, tools_registry=None, cables_man_ref=None):
            pass

        async def spawn(self, agent_type, task):
            return {"status": "complete"}

    monkeypatch.setattr("tools.agent_tool.AgentTool", FakeAgentTool)

    cables = CablesMan()
    await cables.route({"query": "help me plan it", "session_id": "s1"})

    assert len(recording_store.events) == 2
    assert recording_store.events[0] == ("s1", "plan", "routing:help me plan it")
    assert recording_store.events[1] == ("s1", "plan", "complete")


@pytest.mark.asyncio
async def test_route_survives_a_db_persistence_failure(monkeypatch):
    async def fake_get_store():
        raise RuntimeError("db is down")

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)

    class FakeAgentTool:
        def __init__(self, tools_registry=None, cables_man_ref=None):
            pass

        async def spawn(self, agent_type, task):
            return {"status": "complete"}

    monkeypatch.setattr("tools.agent_tool.AgentTool", FakeAgentTool)

    cables = CablesMan()
    result = await cables.route({"query": "hello", "session_id": "s1"})
    assert result == {"status": "complete"}


@pytest.mark.asyncio
async def test_broadcast_fans_out_to_every_agent_type_and_keeps_going_on_one_failure(monkeypatch):
    class FakeAgentTool:
        def __init__(self, tools_registry=None, cables_man_ref=None):
            pass

        async def spawn(self, agent_type, task):
            if agent_type == "plan":
                raise RuntimeError("boom")
            return {"status": "complete", "agent": agent_type}

    monkeypatch.setattr("tools.agent_tool.AgentTool", FakeAgentTool)

    cables = CablesMan()
    results = await cables.broadcast({"query": "hello"}, ["plan", "explore"])

    assert results["explore"] == {"status": "complete", "agent": "explore"}
    assert "error" in results["plan"]
