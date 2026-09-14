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

    async def fake_upsert_skill(skill_id, name, triggers, content, description=""):
        calls.append(skill_id)

    store.upsert_skill = fake_upsert_skill
    await store._seed_default_skills()

    assert calls == [s["id"] for s in _DEFAULT_SKILLS]


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
