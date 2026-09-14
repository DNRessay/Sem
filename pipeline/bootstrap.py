from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from cache.cache_ctrl import CacheController
from cache.conv_cache import ConvCache
from cache.sys_cache import SysCache
from config import settings
from memory.sem_retrieval import SEMRetrieval
from pipeline.ctx_assembly import CTXAssembly
from pipeline.ctx_pressure import CTXPressure
from pipeline.query_engine import QueryEngine
from storage.embeddings import embed_text
from storage.neon_store import get_store

_SAST = timezone(timedelta(hours=2))  # South Africa Standard Time — no DST

# `history` is the frontend's full accumulated conversation state, resent in
# full on every single turn with no windowing — a session with a few long
# exchanges (a big repo-overview reply, say) eventually blows this account's
# already-tight Groq ITPM (input tokens/minute) budget on history alone,
# even for a short unrelated follow-up. Keeps only the most recent turns
# that fit this char budget, dropping the oldest first.
_MAX_HISTORY_CHARS = 8_000


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

    async def run(
        self, query: str, session_id: str, history: list, images: list | None = None,
        display_query: str | None = None, assistant_prefix: str = "",
    ) -> AsyncIterator[str]:
        """`query` is what actually reaches the model — it may have
        attachments or fetched/searched web content folded into it.
        `display_query` (defaults to `query` when omitted) is what gets
        persisted as "what the user said" and embedded into long-term
        memory: callers that augment `query` should pass the original, clean
        text here so a search result dump doesn't get saved and later
        displayed as if the user had typed it. `assistant_prefix` is
        prepended only to the *persisted* assistant turn (not the streamed
        output) — used to carry a compact marker of which tool ran, so a
        reloaded session can still show it."""
        save_query = display_query if display_query is not None else query
        # Step 2 - CTX assembly
        ctx = self.sys_cache.read("system_prompt") or self.ctx_assembly.load_hierarchy()
        ctx = self.ctx_assembly.inject_tau_context(ctx, self.tau_context)
        ctx = self._inject_current_time(ctx)

        # Step 3 - memory load
        memories = await self.sem_retrieval.retrieve(query)
        memory_block = self._format_memories(memories)

        skills_block = await self._skills_context(query)

        # Step 6 - ctx pressure before we hit the LLM
        full_ctx = self.ctx_pressure.apply(f"{ctx}\n\n{memory_block}\n\n{skills_block}")

        # Step 4 - query engine: direct Groq call, cached, cost-tracked,
        # streamed token-by-token as Groq generates it
        messages = [{"role": "system", "content": full_ctx}]
        messages.extend(
            {"role": h.get("role", "user"), "content": h.get("content", "")}
            for h in self._trim_history(history)
        )

        if images:
            # GROQ_MODEL (Qwen/GPT-OSS) can't read images — only the vision
            # model accepts this OpenAI-style content-parts shape, so both
            # the message content and the model switch together.
            content_parts = [{"type": "text", "text": query}]
            for img in images:
                mime = img.get("mime") or "image/png"
                b64 = img.get("base64", "")
                content_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
            messages.append({"role": "user", "content": content_parts})
            model = settings.GROQ_VISION_MODEL
        else:
            messages.append({"role": "user", "content": query})
            model = settings.GROQ_MODEL

        reply_parts = []
        try:
            async for piece in self.query_engine.stream_llm(messages, session_id=session_id, model=model):
                reply_parts.append(piece)
                yield piece
        except Exception as e:
            # A Groq API failure (context length exceeded — easy to hit with
            # a big repo attach, rate limit, bad key, network blip) used to
            # propagate straight out of this generator and silently kill the
            # whole streamed response: nothing shown, nothing saved, no error
            # surfaced. Same failure shape as the earlier news-tool KeyError
            # bug, one level up — any LLM-call failure at all, not just one
            # tool's. Surface it as the reply instead of dying silently.
            error_msg = f"Something went wrong generating a reply — {str(e)[:300]}"
            reply_parts.append(error_msg)
            yield error_msg
        reply = "".join(reply_parts)

        db = await get_store()
        await db.save_turn(session_id, "user", save_query)
        await db.save_turn(session_id, "assistant", f"{assistant_prefix}{reply}")

        # Long-term memory: the system prompt has always claimed persistent
        # memory that "updates from every conversation", but nothing ever
        # actually wrote to the memories table SEMRetrieval reads from — this
        # closes that gap so later turns (and personalized news topics) have
        # real history to draw on instead of always retrieving nothing.
        embedding = await embed_text(save_query)
        await db.save_memory(session_id, save_query, embedding=embedding)

    async def _skills_context(self, query: str) -> str:
        """Two-tier skill disclosure, mirroring how Claude sees Skills: a
        lightweight catalog (name + description) for every enabled skill is
        shown on *every* turn so the model always knows what's available and
        is told to check it before responding — not just the ones a keyword
        happens to hit. Full skill content is then loaded only for skills
        whose trigger keywords actually match this query, the same
        two-stage shape as a skill's frontmatter description being always
        visible versus its full body being loaded on demand — done here via
        deterministic substring matching rather than a tool call, since
        Groq's function-calling reliability on the current models
        (Qwen3.8-27B, GPT-OSS-120B) isn't something to bet every message on."""
        db = await get_store()
        skills = await db.list_skills(enabled_only=True)
        if not skills:
            return ""

        catalog_lines = [
            "<available_skills>",
            "Before responding, check whether any of these skills apply to the "
            "current request. If one does, follow its full instructions (shown "
            "below under active_skills if already loaded, otherwise use your "
            "judgement from the description) as authoritative for how to proceed.",
        ]
        for s in skills:
            desc = s.get("description") or "(no description)"
            catalog_lines.append(f"- {s['name']}: {desc}")
        catalog_lines.append("</available_skills>")

        query_lower = query.lower()
        matched = [s for s in skills if any(t in query_lower for t in s["triggers"])]
        active_lines = []
        if matched:
            active_lines.append("<active_skills>")
            for s in matched:
                active_lines.append(f"  <skill name=\"{s['name']}\">\n{s['content']}\n  </skill>")
            active_lines.append("</active_skills>")

        return "\n".join(catalog_lines + active_lines)

    def _trim_history(self, history: list) -> list:
        """Keeps the most recent turns that fit `_MAX_HISTORY_CHARS`,
        dropping the oldest first. Always keeps at least the single most
        recent turn even if it alone exceeds the budget — trimming a turn's
        own content isn't this function's job, and an over-budget most-
        recent turn will surface as its own clear Groq error rather than a
        silently empty history."""
        kept = []
        total = 0
        for h in reversed(history):
            content_len = len(h.get("content", ""))
            if kept and total + content_len > _MAX_HISTORY_CHARS:
                break
            kept.append(h)
            total += content_len
        return list(reversed(kept))

    def _inject_current_time(self, ctx: str) -> str:
        # Computed fresh every call, never baked into the cached system
        # prompt (that's cached up to an hour) — a stale "current time"
        # would be worse than no answer at all.
        now = datetime.now(_SAST)
        return f"{ctx}\n\nCurrent date and time: {now.strftime('%A, %d %B %Y, %H:%M')} SAST (South Africa)."

    def _format_memories(self, memories: list) -> str:
        if not memories:
            return ""
        lines = ["<semblance_memory>"]
        for m in memories:
            lines.append(f"  - {m.get('content', '')}")
        lines.append("</semblance_memory>")
        return "\n".join(lines)
