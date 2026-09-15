import pytest

from agents.buddy import Buddy, BuddyAgent


class FakeStore:
    def __init__(self):
        self.data: dict[str, dict] = {}

    async def get_buddy(self, session_id):
        return self.data.get(session_id)

    async def save_buddy(self, session_id, data):
        self.data[session_id] = data


@pytest.mark.asyncio
async def test_status_creates_a_buddy_when_none_exists(monkeypatch):
    store = FakeStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    agent = BuddyAgent(session_id="s1")
    result = await agent.run({"session_id": "s1", "action": "status"})

    assert "name" in result
    assert store.data["s1"]["name"] == result["name"]


@pytest.mark.asyncio
async def test_buddy_persists_across_separate_agent_instances(monkeypatch):
    """The whole point of the fix: CablesMan.route() builds a fresh
    BuddyAgent per call, so persistence has to come from the DB, not
    instance state — this proves a second, brand-new BuddyAgent instance
    sees the first instance's changes."""
    store = FakeStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)

    agent1 = BuddyAgent(session_id="s1")
    await agent1.run({"session_id": "s1", "action": "new", "name": "Sparky"})

    agent2 = BuddyAgent(session_id="s1")
    fed = await agent2.run({"session_id": "s1", "action": "feed"})

    assert fed["status"]["name"] == "Sparky"
    assert fed["status"]["xp"] == 10


@pytest.mark.asyncio
async def test_different_sessions_get_independent_buddies(monkeypatch):
    store = FakeStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)

    agent = BuddyAgent()
    await agent.run({"session_id": "s1", "action": "new", "name": "A"})
    await agent.run({"session_id": "s2", "action": "new", "name": "B"})

    assert store.data["s1"]["name"] == "A"
    assert store.data["s2"]["name"] == "B"


@pytest.mark.asyncio
async def test_rename_persists(monkeypatch):
    store = FakeStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)

    agent = BuddyAgent()
    await agent.run({"session_id": "s1", "action": "new"})
    result = await agent.run({"session_id": "s1", "action": "rename", "name": "Newname"})

    assert result["message"] == "Renamed to Newname!"
    assert store.data["s1"]["name"] == "Newname"


@pytest.mark.asyncio
async def test_unknown_action_returns_error_without_writing(monkeypatch):
    store = FakeStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)

    agent = BuddyAgent()
    result = await agent.run({"session_id": "s1", "action": "explode"})

    assert "error" in result
    assert "s1" not in store.data


def test_buddy_to_dict_from_dict_round_trip_preserves_state():
    buddy = Buddy(species="Foxbyte", name="Rex")
    buddy.gain_xp(150)
    buddy.interact("pet")

    restored = Buddy.from_dict(buddy.to_dict())

    assert restored.name == buddy.name
    assert restored.species == buddy.species
    assert restored.level == buddy.level
    assert restored.xp == buddy.xp
    assert restored.xp_next == buddy.xp_next
    assert restored.hp == buddy.hp
    assert restored.stats == buddy.stats
