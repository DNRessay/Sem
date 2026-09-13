import asyncio
import time

from agents.base_agent import BaseAgent
from memory.salience_engine import SalienceEngine
from storage.embeddings import embed_text
from storage.neon_store import get_store


class DreamAgent(BaseAgent):
    """
    Memory consolidation agent.
    3-gate trigger: 24hr + 5 sessions + lock.
    4 phases: Orient → Gather → Consolidate → Index.
    Nothing pruned — ever.
    """

    GATE_HOURS = 24
    GATE_SESSIONS = 5

    def __init__(self, tools_registry=None, cables_man_ref=None):
        super().__init__(tools_registry, cables_man_ref)
        self.salience = SalienceEngine()
        self._lock = asyncio.Lock()
        self._last_run = 0.0
        self._sessions = 0

    async def run(self, task: dict) -> dict:
        if not self.check_gates():
            return {"status": "gates_not_met", "sessions": self._sessions,
                    "hours_since_last": (time.time() - self._last_run) / 3600}

        async with self._lock:
            self.log_audit("dream:orient")
            orientation = self.phase_orient()

            self.log_audit("dream:gather")
            raw = await self.phase_gather()

            self.log_audit(f"dream:consolidate:{len(raw)}:memories")
            consolidated = await self.phase_consolidate(raw)

            self.log_audit("dream:index")
            await self.phase_index(consolidated)

            self._last_run = time.time()
            self._sessions = 0

        return {
            "status": "complete",
            "consolidated": len(consolidated),
            "orientation": orientation,
        }

    def check_gates(self) -> bool:
        elapsed_hrs = (time.time() - self._last_run) / 3600
        return (elapsed_hrs >= self.GATE_HOURS
                and self._sessions >= self.GATE_SESSIONS
                and not self._lock.locked())

    def phase_orient(self) -> dict:
        """Phase 1: Survey current memory state."""
        return {
            "last_run": self._last_run,
            "sessions_since": self._sessions,
            "status": "ready_to_consolidate",
        }

    async def phase_gather(self) -> list:
        """Phase 2: Pull raw memories from Neon."""
        try:
            db = await get_store()
            return await db.get_recent_memories(limit=500)
        except Exception:
            return []

    async def phase_consolidate(self, raw: list) -> list:
        """Phase 3: Score + rank. Never delete."""
        scored = []
        for m in raw:
            score = self.salience.score(
                {"created_at": m.get("created_at", time.time())},
                {},
                0.0
            )
            scored.append({**m, "salience": score})
        return sorted(scored, key=lambda x: x["salience"], reverse=True)

    async def phase_index(self, consolidated: list):
        """Phase 4: Re-embed, re-score in place. Nothing pruned."""
        db = await get_store()
        for m in consolidated:
            try:
                embedding = await embed_text(m.get("content", ""))
                await db.update_memory_salience(m["id"], m.get("salience", 0.5), embedding)
            except Exception:
                continue

    def increment_session(self):
        self._sessions += 1
