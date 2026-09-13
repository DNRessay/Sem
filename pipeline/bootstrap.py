from typing import AsyncIterator

from cache.cache_ctrl import CacheController
from cache.conv_cache import ConvCache
from cache.sys_cache import SysCache
from memory.sem_retrieval import SEMRetrieval
from pipeline.ctx_assembly import CTXAssembly
from pipeline.ctx_pressure import CTXPressure
from pipeline.query_engine import QueryEngine
from storage.neon_store import get_store


class Bootstrap:
    """
    Step 1 - 7-stage init. Assembles context (SEMBLANCE.md + TAU + memory),
    then hands the full conversation off to QueryEngine, which calls Groq
    directly (Qwen/GPT-OSS, whichever GROQ_MODEL is configured). No
    intermediate CLI, no third-party binary, no impersonation of any model
    the response didn't actually come from.
    """

    def __init__(self, trust_mode: str = "AUTO", tau_context: str = ""):
        self.trust_mode = trust_mode
        self.tau_context = tau_context
        self.sys_cache = SysCache()
        self.conv_cache = ConvCache()
        self.cache_ctrl = CacheController()
        self.sem_retrieval = SEMRetrieval()
        self.ctx_assembly = CTXAssembly()
        self.ctx_pressure = CTXPressure()
        self.query_engine = QueryEngine()

    async def run(self, query: str, session_id: str, history: list) -> AsyncIterator[str]:
        # Step 2 - CTX assembly
        ctx = self.sys_cache.read("system_prompt") or self.ctx_assembly.load_hierarchy()
        ctx = self.ctx_assembly.inject_tau_context(ctx, self.tau_context)

        # Step 3 - memory load
        memories = await self.sem_retrieval.retrieve(query)
        memory_block = self._format_memories(memories)

        # Step 6 - ctx pressure before we hit the LLM
        full_ctx = self.ctx_pressure.apply(f"{ctx}\n\n{memory_block}")

        # Step 4 - query engine: direct Groq call, cached, cost-tracked,
        # streamed token-by-token as Groq generates it
        messages = [{"role": "system", "content": full_ctx}]
        messages.extend({"role": h.get("role", "user"), "content": h.get("content", "")} for h in history)
        messages.append({"role": "user", "content": query})

        reply_parts = []
        async for piece in self.query_engine.stream_llm(messages, session_id=session_id):
            reply_parts.append(piece)
            yield piece
        reply = "".join(reply_parts)

        db = await get_store()
        await db.save_turn(session_id, "user", query)
        await db.save_turn(session_id, "assistant", reply)

    def _format_memories(self, memories: list) -> str:
        if not memories:
            return ""
        lines = ["<semblance_memory>"]
        for m in memories:
            lines.append(f"  - {m.get('content', '')}")
        lines.append("</semblance_memory>")
        return "\n".join(lines)
