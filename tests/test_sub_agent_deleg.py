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
