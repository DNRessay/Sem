import json

import pytest

from agents import bridge


@pytest.fixture
def store(monkeypatch):
    data = {}
    monkeypatch.setattr(bridge.ddb_backend, "set", lambda ns, k, v, ttl=300: data.__setitem__((ns, k), v))
    monkeypatch.setattr(bridge.ddb_backend, "get", lambda ns, k: data.get((ns, k)))
    return data


@pytest.mark.asyncio
async def test_query_runs_now_and_result_can_be_fetched(store):
    class FakeCables:
        async def route(self, task):
            return {"answer": task["query"].upper()}

    agent = bridge.BridgeAgent(cables_man_ref=FakeCables(), session_id="s")
    out = await agent.run({"command": {"type": "query", "query": "hi"}})
    assert out["status"] == "complete" and out["result"] == {"answer": "HI"}
    again = await agent.run({"action": "result", "cmd_id": out["cmd_id"]})
    assert again["result"] == {"answer": "HI"}
    assert json.loads(store[("bridge_result", out["cmd_id"])]) == {"answer": "HI"}


@pytest.mark.asyncio
async def test_unknown_command_type_is_an_error(store):
    out = await bridge.BridgeAgent().run({"command": {"type": "teleport"}})
    assert "Unknown command type" in out["result"]["error"]


@pytest.mark.asyncio
async def test_missing_result_and_bad_action(store):
    agent = bridge.BridgeAgent()
    assert (await agent.run({"action": "result", "cmd_id": "nope"}))["status"] == "not_found"
    assert "Unknown action" in (await agent.run({"action": "dance"}))["error"]
