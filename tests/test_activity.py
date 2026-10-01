import pytest

from pipeline import activity


class Store:
    def __init__(self):
        self.rows = []

    async def save_agent_event(self, session, agent, action):
        self.rows.append((session, agent, action))


@pytest.mark.asyncio
async def test_run_log_writes_readable_lines_per_chat(monkeypatch):
    store = Store()

    async def fake():
        return store

    monkeypatch.setattr(activity, "get_store", fake)
    session = activity.session_for("code", {"chat_id": "c123abc"})
    log = activity.RunLog(session, "code")
    await log.start("fix the tests", "bonsai", "act")
    await log.record({"type": "tool", "name": "mcp__clab__overview", "args": {}})
    await log.record({"type": "result", "name": "mcp__clab__overview", "ok": False, "output": "401"})
    await log.record({"type": "tool", "name": "set_secret", "args": {"name": "K", "value": "s3cret"}})
    await log.record({"type": "done", "steps": 3, "model": "gemini"})
    assert all(r[0] == "code:c123abc" for r in store.rows)
    assert store.rows[1][1] == "mcp:clab" and store.rows[2][2].startswith("blocked:")
    assert "s3cret" not in store.rows[3][2]
    assert "answered by gemini" in store.rows[4][2]


def test_bad_chat_ids_are_not_logged():
    assert activity.session_for("code", {"chat_id": "../x"}) is None
    assert activity.session_for("code", {}) is None
