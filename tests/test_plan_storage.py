import pytest

from storage.neon_store import NeonStore


class _FakeConn:
    """Simulates just enough of asyncpg's connection interface for the
    plans table: an in-memory dict keyed by session_id, since a real
    Postgres isn't available in this test environment (see the moto_cache_table
    fixture's own docstring for why other tests reach for a Postgres-shaped
    fake in the same spirit)."""

    def __init__(self, table):
        self.table = table

    async def execute(self, query, *args):
        if query.startswith("INSERT INTO plans"):
            session_id, goal, steps_json, now = args
            self.table[session_id] = {"goal": goal, "steps": steps_json, "updated_at": now}
        elif query.startswith("UPDATE plans SET steps"):
            steps_json, now, session_id = args
            if session_id in self.table:
                self.table[session_id]["steps"] = steps_json
                self.table[session_id]["updated_at"] = now

    async def fetchrow(self, query, *args):
        session_id = args[0]
        row = self.table.get(session_id)
        if not row:
            return None
        return {"goal": row["goal"], "steps": row["steps"]}


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self):
        self.table = {}
        self._conn = _FakeConn(self.table)

    def acquire(self):
        return _FakeAcquire(self._conn)


@pytest.fixture
def store():
    s = NeonStore()
    s._pool = _FakePool()
    return s


@pytest.mark.asyncio
async def test_save_plan_stamps_pending_status_on_every_step(store):
    await store.save_plan("sess1", "ship the bot", [{"n": 1, "action": "write code", "tool": "bash"}])
    plan = await store.get_active_plan("sess1")
    assert plan["goal"] == "ship the bot"
    assert plan["steps"] == [{"n": 1, "action": "write code", "tool": "bash", "status": "pending"}]


@pytest.mark.asyncio
async def test_save_plan_preserves_an_explicit_status_if_the_caller_set_one(store):
    await store.save_plan("sess1", "x", [{"n": 1, "action": "a", "status": "done"}])
    plan = await store.get_active_plan("sess1")
    assert plan["steps"][0]["status"] == "done"


@pytest.mark.asyncio
async def test_get_active_plan_returns_none_when_nothing_saved(store):
    assert await store.get_active_plan("sess1") is None


@pytest.mark.asyncio
async def test_save_plan_replaces_the_previous_plan_outright(store):
    await store.save_plan("sess1", "goal A", [{"n": 1, "action": "a"}])
    await store.save_plan("sess1", "goal B", [{"n": 1, "action": "b"}])
    plan = await store.get_active_plan("sess1")
    assert plan["goal"] == "goal B"
    assert plan["steps"][0]["action"] == "b"


@pytest.mark.asyncio
async def test_update_plan_step_marks_the_matching_step_done_with_a_result(store):
    await store.save_plan("sess1", "x", [
        {"n": 1, "action": "a"}, {"n": 2, "action": "b"},
    ])
    await store.update_plan_step("sess1", 1, "done", "output here")
    plan = await store.get_active_plan("sess1")
    assert plan["steps"][0]["status"] == "done"
    assert plan["steps"][0]["result"] == "output here"
    assert plan["steps"][1]["status"] == "pending"  # untouched


@pytest.mark.asyncio
async def test_update_plan_step_is_a_no_op_with_no_active_plan(store):
    await store.update_plan_step("sess1", 1, "done")  # must not raise
    assert await store.get_active_plan("sess1") is None
