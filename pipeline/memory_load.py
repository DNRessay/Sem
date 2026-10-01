from memory.sem_retrieval import SEMRetrieval
from storage.neon_store import get_store


class MemoryLoad:
    def __init__(self):
        self.sem = SEMRetrieval()

    async def coordinate(self, query: str, session_id: str = "default") -> dict:
        semantic = await self.sem.retrieve(query, top_k=5)
        raw = []
        try:
            db = await get_store()
            raw = await db.get_recent_memories(session_id=session_id, limit=20)
        except Exception:
            pass

        seen, merged = set(), []
        for m in semantic + raw:
            c = m.get("content", "")
            if c and c not in seen:
                seen.add(c)
                merged.append(m)

        return {"memories": merged}
