import asyncio
import time

from memory.salience_engine import SalienceEngine
from storage.embeddings import embed_text
from storage.neon_store import get_store


class DREAMAgent:
    def __init__(self):
        self.salience = SalienceEngine()
        self._lock = asyncio.Lock()
        self._last_run: float = 0
        self._session_count: int = 0

    def increment_session(self):
        self._session_count += 1

    def check_gates(self) -> bool:
        elapsed = time.time() - self._last_run
        return elapsed >= 86400 and self._session_count >= 5 and not self._lock.locked()

    async def run(self):
        if not self.check_gates():
            return
        async with self._lock:
            raw = await self.phase_gather()
            consolidated = await self.phase_consolidate(raw)
            await self.phase_index(consolidated)
            self._last_run = time.time()
            self._session_count = 0

    async def phase_gather(self) -> list:
        db = await get_store()
        return await db.get_recent_memories(limit=500)

    async def phase_consolidate(self, raw: list) -> list:
        scored = []
        for m in raw:
            score = self.salience.score(m, {}, 0.0)
            scored.append({**m, "salience": score})
        return sorted(scored, key=lambda x: x["salience"], reverse=True)

    async def phase_index(self, consolidated: list):
        """Re-embed and re-score each memory in place. Nothing is ever deleted."""
        db = await get_store()
        for m in consolidated:
            embedding = await embed_text(m.get("content", ""))
            await db.update_memory_salience(m["id"], m.get("salience", 0.5), embedding)
