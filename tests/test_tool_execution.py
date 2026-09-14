import pytest

from pipeline.tool_execution import ToolExecution, get_tool_execution


class FakeRegistry:
    def __init__(self, result):
        self._result = result
        self.calls = []

    async def execute(self, tool_name, args, trust_mode="AUTO"):
        self.calls.append((tool_name, args, trust_mode))
        return self._result


class RecordingStore:
    def __init__(self):
        self.events = []

    async def save_agent_event(self, session_id, agent, action):
        self.events.append((session_id, agent, action))


@pytest.mark.asyncio
async def test_execute_routes_through_registry_with_trust_mode(monkeypatch):
    registry = FakeRegistry({"ok": True, "content": "hi"})
    monkeypatch.setattr("pipeline.tool_execution.get_registry", lambda: registry)

    execution = ToolExecution(trust_mode="BYPASS")
    result = await execution.execute("web_fetch", {"url": "https://example.com"}, session_id="s1")

    assert result == {"ok": True, "content": "hi"}
    assert registry.calls == [("web_fetch", {"url": "https://example.com"}, "BYPASS")]


@pytest.mark.asyncio
async def test_execute_appends_to_in_process_audit(monkeypatch):
    registry = FakeRegistry({"ok": True})
    monkeypatch.setattr("pipeline.tool_execution.get_registry", lambda: registry)

    execution = ToolExecution()
    await execution.execute("bash", {"command": "ls"}, session_id="s1")

    audit = execution.get_audit()
    assert len(audit) == 1
    assert audit[0]["tool"] == "bash"


@pytest.mark.asyncio
async def test_execute_persists_an_ok_event_to_the_db(monkeypatch):
    registry = FakeRegistry({"ok": True})
    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("pipeline.tool_execution.get_registry", lambda: registry)
    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)

    execution = ToolExecution()
    await execution.execute("web_search", {"query": "chess"}, session_id="s1")

    assert len(store.events) == 1
    session_id, agent, action = store.events[0]
    assert session_id == "s1"
    assert agent == "web_search"
    assert action.startswith("ok:")


@pytest.mark.asyncio
async def test_execute_persists_a_blocked_event_when_the_tool_reports_blocked(monkeypatch):
    registry = FakeRegistry({"blocked": True, "error": "nope"})
    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("pipeline.tool_execution.get_registry", lambda: registry)
    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)

    execution = ToolExecution()
    await execution.execute("bash", {"command": "rm -rf /"}, session_id="s1")

    assert store.events[0][2].startswith("blocked:")


@pytest.mark.asyncio
async def test_execute_survives_a_db_persistence_failure(monkeypatch):
    """A DB hiccup while writing the audit trail must never fail the tool
    call itself — the tool's actual result still has to come back."""
    registry = FakeRegistry({"ok": True, "content": "hi"})

    async def fake_get_store():
        raise RuntimeError("db is down")

    monkeypatch.setattr("pipeline.tool_execution.get_registry", lambda: registry)
    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)

    execution = ToolExecution()
    result = await execution.execute("web_fetch", {"url": "https://example.com"}, session_id="s1")
    assert result == {"ok": True, "content": "hi"}


def test_get_tool_execution_returns_a_shared_instance_for_the_same_trust_mode(monkeypatch):
    monkeypatch.setattr("pipeline.tool_execution._execution", None)
    first = get_tool_execution("AUTO")
    second = get_tool_execution("AUTO")
    assert first is second


def test_get_tool_execution_creates_a_new_instance_on_trust_mode_change(monkeypatch):
    monkeypatch.setattr("pipeline.tool_execution._execution", None)
    first = get_tool_execution("AUTO")
    second = get_tool_execution("BYPASS")
    assert first is not second
    assert second.trust_mode == "BYPASS"
