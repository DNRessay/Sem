import re
import time

from agents.base_agent import BaseAgent
from memory.salience_engine import SalienceEngine
from storage.embeddings import embed_text
from storage.neon_store import get_store
from tau.emotion_engine import NatureSCIEngine


class DreamAgent(BaseAgent):
    """
    Memory consolidation agent.
    3-gate trigger: 24hr + 5 sessions + lock.
    4 phases: Orient → Gather → Consolidate → Index.
    Nothing pruned — ever.

    The gate used to live on in-memory instance attributes
    (self._last_run/self._sessions), which reset on every Lambda
    invocation (AgentTool.spawn() constructs a fresh DreamAgent on every
    call) and were never actually incremented from anywhere in the live
    request path — the gate could never pass. It's now backed by Neon
    (storage.neon_store's dream_state table + a real distinct-session
    count from conversations), so it survives across invocations and
    reflects real activity. See tick_handler.py for the EventBridge
    schedule that actually calls run() periodically — Lambda has no
    persistent process for this to run on its own, and consolidation is
    deliberately not chat-triggerable: it iterates up to 500 memories and
    re-embeds them, a background maintenance job, not something a stray
    chat phrase should be able to kick off mid-conversation.
    """

    GATE_HOURS = 24
    GATE_SESSIONS = 5

    def __init__(self, tools_registry=None, cables_man_ref=None, **kwargs):
        super().__init__(tools_registry, cables_man_ref, **kwargs)
        self.salience = SalienceEngine()
        self.emotion = NatureSCIEngine()

    async def run(self, task: dict) -> dict:
        gate = await self.check_gates()
        if not gate["ready"]:
            return {"status": "gates_not_met", **gate}

        self.log_audit("dream:orient")
        orientation = self.phase_orient(gate)

        self.log_audit("dream:gather")
        raw = await self.phase_gather()

        self.log_audit(f"dream:consolidate:{len(raw)}:memories")
        consolidated = await self.phase_consolidate(raw)

        self.log_audit("dream:index")
        await self.phase_index(consolidated)

        db = await get_store()
        await db.set_dream_last_run(int(time.time()))

        return {
            "status": "complete",
            "consolidated": len(consolidated),
            "orientation": orientation,
        }

    async def check_gates(self) -> dict:
        """Real, Neon-backed gate check — returns the full state (not just
        a bool) so a caller (tick_handler, a future status surface) can
        show *why* it isn't ready yet, not just that it isn't."""
        db = await get_store()
        last_run = await db.get_dream_last_run()
        elapsed_hrs = (time.time() - last_run) / 3600
        sessions = await db.count_sessions_since(last_run)
        ready = elapsed_hrs >= self.GATE_HOURS and sessions >= self.GATE_SESSIONS
        return {"ready": ready, "hours_since_last": elapsed_hrs, "sessions_since_last": sessions}

    def phase_orient(self, gate: dict) -> dict:
        """Phase 1: Survey current memory state."""
        return {**gate, "status": "ready_to_consolidate"}

    async def phase_gather(self) -> list:
        """Phase 2: Pull raw memories from Neon."""
        try:
            db = await get_store()
            return await db.get_recent_memories(limit=500)
        except Exception:
            return []

    async def phase_consolidate(self, raw: list) -> list:
        """Phase 3: Score + rank. Never delete. Salience mixes recency, how
        emotionally charged the memory is (NATURE SCI word-list reading —
        cheap enough for hundreds of memories), and how novel its wording
        is against the rest (rare words = surprise)."""
        tokens = [set(re.findall(r"[a-z]{4,}", (m.get("content") or "").lower())) for m in raw]
        doc_freq: dict[str, int] = {}
        for words in tokens:
            for w in words:
                doc_freq[w] = doc_freq.get(w, 0) + 1
        rare_cutoff = max(1, len(raw) // 50)

        scored = []
        for m, words in zip(raw, tokens):
            emu = self.emotion.analyse_text(m.get("content") or "")
            emotion = {emu.label: emu.confidence} if emu.label != "neutral" else {}
            surprise = (sum(1 for w in words if doc_freq[w] <= rare_cutoff) / len(words)) if words else 0.0
            score = self.salience.score({"created_at": m.get("created_at", time.time())}, emotion, surprise)
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
