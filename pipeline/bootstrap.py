from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from cache.cache_ctrl import CacheController
from cache.conv_cache import ConvCache
from cache.sys_cache import SysCache
from config import settings
from memory.sem_retrieval import SEMRetrieval
from pipeline.ctx_assembly import CTXAssembly
from pipeline.ctx_pressure import CTXPressure
from pipeline.query_engine import QueryEngine, RateLimitError
from storage.embeddings import embed_text
from storage.neon_store import get_store

_SAST = timezone(timedelta(hours=2))  # South Africa Standard Time — no DST

# `history` is the frontend's full accumulated conversation state, resent in
# full on every single turn with no windowing — a session with a few long
# exchanges (a big repo-overview reply, say) eventually blows this account's
# already-tight Groq ITPM (input tokens/minute) budget on history alone,
# even for a short unrelated follow-up. Keeps only the most recent turns
# that fit this char budget, dropping the oldest first. Lowered from 8000:
# ITPM (7000 tokens) is a rolling per-minute window shared across every
# request that minute, not a per-request cap, so a smaller history isn't
# just "safer for one big request" — it's a smaller bite out of the same
# shared budget every ordinary back-to-back turn takes, which is what
# actually determines how many turns fit in a minute before a 429.
_MAX_HISTORY_CHARS = 3_000

# See _skills_context below — caps the combined size of full skill content
# injected for whatever matched this turn, same ITPM-budget reasoning.
_MAX_SKILL_CONTENT_CHARS = 3_000


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
        except RateLimitError as e:
            # A real one dumped Groq's raw error JSON straight into the chat
            # ("Rate limit reached for model... on tokens per day (TPD):
            # Limit 200000, Used 197484... Please try again in 10m55.776s")
            # — technically accurate, completely unreadable. This is the
            # one LLM failure worth a distinct, human message: it's not a
            # bug, it's a quota, and the user can act on "try again in ~11
            # minutes" in a way they can't act on a raw JSON blob.
            error_msg = self._rate_limit_message(e.retry_after)
            reply_parts.append(error_msg)
            yield error_msg
        except Exception as e:
            # A Groq API failure (context length exceeded — easy to hit with
            # a big repo attach, bad key, network blip) used to
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
        # memory that "updates from every conversation" — but until recently
        # only the user's own message ever got embedded here, never the
        # assistant's reply, which for a genuine conversational answer (an
        # opinion, a decision, a fact about the user) is often the actually
        # valuable content to be able to find again later.
        #
        # A tool-driven reply (assistant_prefix non-empty — web search, news,
        # fetch, or a repo read/grep) is different: its content already has
        # an authoritative source of truth outside this app (the live web
        # page, the persistently cloned repo on Modal) that can be re-fetched
        # fresh on demand. Embedding a snapshot of it here would duplicate
        # that source, go stale the moment the source changes, and — for
        # something like "what's in this repo," asked again next month or
        # next year — pile up near-duplicate memory rows describing the same
        # repo at different points in time instead of just re-reading it.
        # So only genuine conversational replies get embedded, not tool
        # output; the user's own query is still always embedded either way.
        query_embedding = await embed_text(save_query)
        await db.save_memory(session_id, save_query, embedding=query_embedding)
        if reply and not assistant_prefix:
            reply_embedding = await embed_text(reply)
            await db.save_memory(session_id, reply, embedding=reply_embedding)

    def _rate_limit_message(self, retry_after: float | None) -> str:
        """Groq's own wording ranges from "13.86s" (a per-minute window)
        to "10m55.776s" (a daily quota) — round to whichever unit reads
        naturally instead of always saying seconds or always minutes."""
        if retry_after is None:
            return "I've hit a rate limit — give it a moment and try again."
        if retry_after >= 60:
            minutes = max(1, round(retry_after / 60))
            plural = "s" if minutes != 1 else ""
            return f"I've hit my message limit for today — try again in about {minutes} minute{plural}."
        seconds = max(1, round(retry_after))
        return f"I've hit a rate limit — try again in about {seconds}s."

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
            # A handful of the larger skill files run 5-8k chars each on
            # their own (see skills/*.md) — several matching one query
            # (plausible: broad trigger words like "prompt" or "write")
            # used to inject all of them uncapped, which alone could eat
            # most of ctx_pressure's whole system-prompt budget. Always
            # includes at least the first match even if it alone exceeds
            # the budget (same "keep at least one" principle as
            # _trim_history below), then stops adding more once over.
            total_chars = 0
            for i, s in enumerate(matched):
                content_len = len(s["content"])
                if i > 0 and total_chars + content_len > _MAX_SKILL_CONTENT_CHARS:
                    break
                active_lines.append(f"  <skill name=\"{s['name']}\">\n{s['content']}\n  </skill>")
                total_chars += content_len
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
