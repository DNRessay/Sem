from memory import fact_memory


def test_facts_are_parsed_cleaned_and_secrets_dropped():
    reply = ('<think>hmm</think>```json\n[{"kind": "fact", "text": "Lives in Soweto, Johannesburg."},'
             ' {"kind": "persona", "text": "Prefers short, direct answers."},'
             ' {"kind": "fact", "text": "lives in soweto, johannesburg."},'
             ' {"kind": "fact", "text": "Their bank PIN is 1234."},'
             ' {"kind": "opinion", "text": "Likes chess."},]\n```')
    assert fact_memory.parse_facts(reply) == [
        {"kind": "fact", "text": "Lives in Soweto, Johannesburg."},
        {"kind": "persona", "text": "Prefers short, direct answers."},
    ]
    assert fact_memory.parse_facts("nothing here") == []


class FakeStore:
    def __init__(self, turns):
        self.turns, self.facts = turns, []

    async def user_turns_after(self, after, limit=60):
        return [t for t in self.turns if t["id"] > after][:limit]

    async def upsert_fact(self, kind, content, embedding, session_id="", same=0.12):
        self.facts.append((kind, content))
        return len(self.facts)

    async def search_facts(self, embedding, kind, top_k=3):
        return [{"content": c} for k, c in self.facts if k == kind][:top_k]

    async def recent_facts(self, kind, limit=3):
        return await self.search_facts(None, kind, limit)


async def test_the_tick_learns_from_new_messages_once(monkeypatch, moto_cache_table):
    store = FakeStore([{"id": i, "session_id": "s1", "content": f"I run a bakery in Soweto number {i}"} for i in range(1, 4)])
    seen = []

    async def fake_store():
        return store

    async def fake_extract(messages):
        seen.append(len(messages))
        return [{"kind": "fact", "text": "Runs a bakery in Soweto."}]

    async def fake_embed(text):
        return [0.1] * 384

    monkeypatch.setattr(fact_memory, "get_store", fake_store)
    monkeypatch.setattr(fact_memory, "extract", fake_extract)
    monkeypatch.setattr(fact_memory, "embed_text_or_none", fake_embed)
    assert await fact_memory.learn_recent() == {"read": 3, "saved": 1}
    assert await fact_memory.learn_recent() == {"read": 0, "saved": 0}  # the cursor moved past them
    assert seen == [3]


async def test_messages_are_kept_for_later_when_no_model_answers(monkeypatch, moto_cache_table):
    store = FakeStore([{"id": 1, "session_id": "s1", "content": "My sister Anya lives in Durban"}])

    async def fake_store():
        return store

    async def down(messages):
        return None

    monkeypatch.setattr(fact_memory, "get_store", fake_store)
    monkeypatch.setattr(fact_memory, "extract", down)
    await fact_memory.learn_recent()
    assert len(await store.user_turns_after(int(fact_memory.ddb_backend.get(*fact_memory.CURSOR, fresh=True) or 0))) == 1


async def test_recall_gives_a_short_block_of_facts_and_preferences(monkeypatch):
    store = FakeStore([])
    store.facts = [("fact", "Runs Vicinic, a website builder."), ("persona", "Prefers short, direct answers."),
                   ("fact", "Lives in Soweto.")]

    async def fake_store():
        return store

    async def fake_embed(text):
        return [0.1] * 384

    monkeypatch.setattr(fact_memory, "get_store", fake_store)
    monkeypatch.setattr(fact_memory, "embed_text_or_none", fake_embed)
    block = await fact_memory.recall("what should I post today?")
    assert block.startswith("<about_user") and "Runs Vicinic" in block and "Lives in Soweto" in block
    assert "How they like things:" in block and "Prefers short, direct answers." in block
    store.facts = []
    assert await fact_memory.recall("hi") == ""
