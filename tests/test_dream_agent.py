import time

import pytest

from agents.dream_agent import DreamAgent


class _FakeStore:
    def __init__(self, last_run=0, sessions_since=0, memories=None):
        self._last_run = last_run
        self._sessions_since = sessions_since
        self._memories = memories or []
        self.set_calls = []
        self.salience_updates = []

    async def get_dream_last_run(self):
        return self._last_run

    async def count_sessions_since(self, since_ts):
        return self._sessions_since

    async def set_dream_last_run(self, ts):
        self.set_calls.append(ts)

    async def get_recent_memories(self, limit=500):
        return self._memories

    async def update_memory_salience(self, memory_id, salience, embedding):
        self.salience_updates.append((memory_id, salience))


@pytest.mark.asyncio
async def test_check_gates_not_ready_when_recently_run(monkeypatch):
    store = _FakeStore(last_run=int(time.time()) - 3600, sessions_since=10)  # 1hr ago

    async def fake_get_store():
        return store

    monkeypatch.setattr("agents.dream_agent.get_store", fake_get_store)
    agent = DreamAgent(session_id="s1")
    gate = await agent.check_gates()

    assert gate["ready"] is False
    assert gate["hours_since_last"] < 24


@pytest.mark.asyncio
async def test_check_gates_not_ready_with_too_few_sessions(monkeypatch):
    store = _FakeStore(last_run=int(time.time()) - 30 * 3600, sessions_since=2)  # 30hr ago, only 2 sessions

    async def fake_get_store():
        return store

    monkeypatch.setattr("agents.dream_agent.get_store", fake_get_store)
    agent = DreamAgent(session_id="s1")
    gate = await agent.check_gates()

    assert gate["ready"] is False
    assert gate["sessions_since_last"] == 2


@pytest.mark.asyncio
async def test_check_gates_ready_when_both_conditions_met(monkeypatch):
    store = _FakeStore(last_run=int(time.time()) - 30 * 3600, sessions_since=5)

    async def fake_get_store():
        return store

    monkeypatch.setattr("agents.dream_agent.get_store", fake_get_store)
    agent = DreamAgent(session_id="s1")
    gate = await agent.check_gates()

    assert gate["ready"] is True


@pytest.mark.asyncio
async def test_check_gates_ready_when_dream_has_never_run(monkeypatch):
    """last_run_at == 0 (never run) counts as "24hr ago" for gate purposes."""
    store = _FakeStore(last_run=0, sessions_since=5)

    async def fake_get_store():
        return store

    monkeypatch.setattr("agents.dream_agent.get_store", fake_get_store)
    agent = DreamAgent(session_id="s1")
    gate = await agent.check_gates()

    assert gate["ready"] is True


@pytest.mark.asyncio
async def test_run_returns_gates_not_met_without_consolidating(monkeypatch):
    store = _FakeStore(last_run=int(time.time()), sessions_since=0)

    async def fake_get_store():
        return store

    monkeypatch.setattr("agents.dream_agent.get_store", fake_get_store)
    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    agent = DreamAgent(session_id="s1")
    result = await agent.run({})

    assert result["status"] == "gates_not_met"
    assert store.set_calls == []


@pytest.mark.asyncio
async def test_run_consolidates_and_persists_last_run_when_gate_passes(monkeypatch):
    memories = [
        {"id": 1, "content": "a", "created_at": time.time()},
        {"id": 2, "content": "b", "created_at": time.time()},
    ]
    store = _FakeStore(last_run=int(time.time()) - 30 * 3600, sessions_since=5, memories=memories)

    async def fake_get_store():
        return store

    monkeypatch.setattr("agents.dream_agent.get_store", fake_get_store)

    async def fake_embed_text(text):
        return [0.1, 0.2]

    monkeypatch.setattr("agents.dream_agent.embed_text", fake_embed_text)

    agent = DreamAgent(session_id="s1")
    result = await agent.run({})

    assert result["status"] == "complete"
    assert result["consolidated"] == 2
    assert len(store.set_calls) == 1  # last_run persisted exactly once
    assert len(store.salience_updates) == 2  # every memory re-scored, nothing pruned


@pytest.mark.asyncio
async def test_phase_gather_returns_empty_list_on_db_failure(monkeypatch):
    async def fake_get_store():
        raise ConnectionError("db down")

    monkeypatch.setattr("agents.dream_agent.get_store", fake_get_store)
    agent = DreamAgent(session_id="s1")
    assert await agent.phase_gather() == []


@pytest.mark.asyncio
async def test_consolidate_weights_emotion_and_novelty_not_just_recency():
    import time

    from agents.dream_agent import DreamAgent
    now = time.time()
    raw = [{"id": i, "content": "ok sounds good thanks", "created_at": now} for i in range(60)]
    raw.append({"id": 99, "content": "terrified the investor pulled funding for vicinic tonight", "created_at": now - 86400})
    ranked = await DreamAgent().phase_consolidate(raw)
    assert ranked[0]["id"] == 99  # a day older, but charged and novel
