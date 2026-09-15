import pytest

from storage.neon_store import _DEFAULT_SKILLS, NeonStore, _to_vector_literal


def test_to_vector_literal_none_and_empty_return_none():
    assert _to_vector_literal(None) is None
    assert _to_vector_literal([]) is None


def test_to_vector_literal_formats_pgvector_syntax():
    literal = _to_vector_literal([0.1, 0.2, -0.3])
    assert literal.startswith("[") and literal.endswith("]")
    assert literal == "[0.10000000,0.20000000,-0.30000000]"


class _FakeConn:
    def __init__(self, count):
        self._count = count

    async def fetchval(self, query):
        return self._count


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, count):
        self._conn = _FakeConn(count)

    def acquire(self):
        return _FakeAcquire(self._conn)


@pytest.mark.asyncio
async def test_seed_default_skills_inserts_every_starter_skill_into_an_empty_table():
    store = NeonStore()
    store._pool = _FakePool(count=0)
    calls = []

    async def fake_upsert_skill(skill_id, name, triggers, content, description="", source="manual"):
        calls.append((skill_id, source))

    store.upsert_skill = fake_upsert_skill
    await store._seed_default_skills()

    assert calls == [(s["id"], "seed") for s in _DEFAULT_SKILLS]


@pytest.mark.asyncio
async def test_seed_default_skills_does_nothing_when_the_table_already_has_rows():
    """A non-empty table means either the seed already ran, or the user has
    their own skills — either way this must never insert (or re-insert a
    seed skill the user deliberately deleted)."""
    store = NeonStore()
    store._pool = _FakePool(count=3)
    calls = []

    async def fake_upsert_skill(*a, **kw):
        calls.append(a)

    store.upsert_skill = fake_upsert_skill
    await store._seed_default_skills()

    assert calls == []


@pytest.mark.asyncio
async def test_sync_repo_skills_upserts_every_skill_file_with_repo_source(monkeypatch):
    store = NeonStore()
    calls = []

    async def fake_upsert_skill(skill_id, name, triggers, content, description="", source="manual"):
        calls.append((skill_id, source))

    store.upsert_skill = fake_upsert_skill
    monkeypatch.setattr("pipeline.skill_files.load_skill_files", lambda: [
        {"id": "repo-a", "name": "A", "description": "", "triggers": [], "content": "x"},
        {"id": "repo-b", "name": "B", "description": "", "triggers": [], "content": "y"},
    ])

    await store._sync_repo_skills()

    assert calls == [("repo-a", "repo"), ("repo-b", "repo")]


@pytest.mark.asyncio
async def test_sync_repo_skills_does_nothing_when_no_skill_files_exist(monkeypatch):
    store = NeonStore()
    calls = []
    store.upsert_skill = lambda *a, **kw: calls.append(a)
    monkeypatch.setattr("pipeline.skill_files.load_skill_files", lambda: [])

    await store._sync_repo_skills()

    assert calls == []


class _RecordingTxnConn:
    def __init__(self):
        self.executed: list[tuple] = []

    async def execute(self, query, *args):
        self.executed.append((query, args))

    def transaction(self):
        return _FakeAcquire(self)  # a no-op async context manager is enough here


@pytest.mark.asyncio
async def test_delete_session_removes_conversations_title_and_memories():
    conn = _RecordingTxnConn()
    store = NeonStore()
    store._pool = _FakePool.__new__(_FakePool)
    store._pool._conn = conn
    store._pool.acquire = lambda: _FakeAcquire(conn)

    await store.delete_session("sess1")

    tables_touched = [q.split("FROM")[1].split()[0] for q, _ in conn.executed]
    assert tables_touched == ["conversations", "session_titles", "memories"]
    assert all(args == ("sess1",) for _, args in conn.executed)
