import json
import time

import asyncpg

from config import settings

PINNED_SALIENCE = 1.0  # facts the user asked Sem to remember (pipeline/turn_router.py)

_EMBED_DIM = 384  # matches the Modal sentence-transformers model (all-MiniLM-L6-v2)

# Starter skills seeded once into an empty skills table (see
# NeonStore._seed_default_skills) so a fresh deploy isn't a blank Skills
# panel — a rough parallel to the built-in skills this assistant itself has,
# adapted into the prompt-injected shape Bootstrap._skills_context uses
# (GROQ_MODEL has no real tool-calling to hang an actual PDF/code tool off
# of). Only inserted when the table is completely empty, so deleting or
# editing one of these later is never silently undone by a redeploy.
_DEFAULT_SKILLS = [
    {
        "id": "seed-code-help",
        "name": "Code Help",
        "description": "Write, debug, and review code — Python-first, minimal comments, no bloat.",
        "triggers": ["code", "bug", "debug", "function", "script", "error", "stack trace", "refactor", "write a script"],
        "content": (
            "When writing or fixing code: default to Python unless the user names another "
            "language. Match project size to framework — a quick script or simple app gets "
            "Flask, an API-focused app gets FastAPI, a multi-app project gets Django. Write "
            "minimal comments (only for non-obvious WHY, never WHAT), no docstrings unless "
            "asked, no speculative abstractions or error handling for cases that can't "
            "happen. Show the code in a fenced block with a language tag. If the ask is "
            "ambiguous (which file, which stack, what's already there), ask before guessing."
        ),
    },
    {
        "id": "seed-pdf-docs",
        "name": "Document & PDF Reading",
        "description": "Read attached PDFs, Word docs, and other files — their text is already extracted for you.",
        "triggers": ["pdf", "document", "docx", "extract", "attached file", "attachment", "attachments"],
        "content": (
            "Attached PDF and Word files have already had their text extracted server-side "
            "and folded into this message inside <attachments><file name=\"...\">...</file> "
            "blocks — never say you can't open or read PDFs/Word docs, the content is "
            "already right here in context. Read it directly and answer from it. If the "
            "extracted text looks empty, garbled, or truncated (common for a scanned/image-"
            "only PDF with no real text layer), say so plainly rather than guessing at "
            "content that isn't there."
        ),
    },
    {
        "id": "seed-writing",
        "name": "Writing & Editing",
        "description": "Draft or tighten text — direct, no filler, no fluff.",
        "triggers": ["write", "draft", "essay", "email", "summarize", "rewrite", "proofread", "edit this"],
        "content": (
            "Write directly — no throat-clearing intro, no "
            "\"I'd be happy to help\" preamble, no restating the request back. Say the "
            "thing. Keep it as short as the task allows; a two-sentence answer beats a "
            "five-paragraph one when two sentences cover it. When editing existing text, "
            "preserve the author's voice and only change what's actually wrong or unclear."
        ),
    },
    {
        "id": "seed-web-research",
        "name": "Web Research",
        "description": "Answer using live search/news results — cite what was actually found, never invent facts.",
        "triggers": ["research", "compare", "look up", "find out", "latest", "current"],
        "content": (
            "When web search or news results are already present in context (retrieved "
            "before you saw this message — see the system note next to them), answer only "
            "from what's actually there. Never invent or assume a specific fact (a date, a "
            "name, a number, a URL) that isn't literally present in the retrieved data, even "
            "if it seems like a safe guess. If the results don't answer the question, say "
            "that plainly instead of filling the gap from general knowledge."
        ),
    },
    {
        "id": "seed-data-finance",
        "name": "Financial & Data Analysis",
        "description": "Bank statements, forex/economic data, spreadsheets — check the actual structure before concluding.",
        "triggers": ["bank statement", "transaction", "forex", "csv", "spreadsheet", "financial data", "economic calendar"],
        "content": (
            "For bank statements, transaction data, or economic/forex datasets: check the "
            "actual column names, date formats, and currency before drawing conclusions — "
            "South African bank exports (Capitec, TymeBank) vary in layout and don't share a "
            "fixed schema. State assumptions about categorization explicitly rather than "
            "silently guessing a category. For time-series/indicator data (RSI, MACD, "
            "Bollinger Bands, economic calendar events), be precise about the timeframe and "
            "period used — an unlabeled indicator value is not useful."
        ),
    },
]


class NeonStore:
    """
    Single Postgres store (Neon, serverless) for everything MySQL + ChromaDB
    used to split across two services. pgvector holds the embedding for every
    memory row, so semantic search is just another query against the same table
    — no separate vector database to run or pay for.

    A module-level pool is reused across warm Lambda invocations; connect() is
    cheap to call repeatedly (no-op once the pool exists).
    """

    def __init__(self):
        self._pool: asyncpg.Pool | None = None

    async def connect(self, url: str):
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(url, min_size=0, max_size=5, command_timeout=10)
        await self._init_schema()
        await self._seed_default_skills()
        await self._sync_repo_skills()

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def _init_schema(self):
        async with self._pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS memories (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    salience REAL DEFAULT 0.5,
                    embedding vector({_EMBED_DIM}),
                    created_at BIGINT NOT NULL
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_session ON memories (session_id)")
            # Short facts about the user, pulled out of conversations (memory/fact_memory.py): kind "fact" (who,
            # what, where) or "persona" (feelings, preferences, style), searched separately.
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS user_facts (
                    id BIGSERIAL PRIMARY KEY,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector({_EMBED_DIM}),
                    session_id TEXT,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_facts_kind ON user_facts (kind)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_salience ON memories (salience DESC)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at BIGINT NOT NULL
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations (session_id)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_models (
                    session_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    passphrase_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'owner',
                    created_at BIGINT NOT NULL
                )
            """)
            # Bumped by a passphrase change; tokens carry it, so older ones stop working (gateway/auth.py).
            await conn.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS connectors (
                    provider TEXT PRIMARY KEY,
                    token TEXT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """)
            # refresh_token/expires_at: added for OAuth-issued tokens (GitLab's
            # OAuth access tokens expire in ~2h and need silent refresh; a
            # manually pasted PAT leaves these NULL and never expires here).
            # ALTER ... ADD COLUMN IF NOT EXISTS rather than folding into the
            # CREATE TABLE above, since that table already exists in any
            # environment that deployed before this column was added.
            await conn.execute("ALTER TABLE connectors ADD COLUMN IF NOT EXISTS refresh_token TEXT")
            await conn.execute("ALTER TABLE connectors ADD COLUMN IF NOT EXISTS expires_at BIGINT")
            # account_id + composite PK: connectors started out global-per-
            # provider, which meant a guest connecting their own GitHub would
            # silently overwrite the owner's. Existing rows (from before any
            # account scoping existed) are backfilled to 'owner', the only
            # account that could have created them. The named-constraint
            # check makes this idempotent — a plain DROP+ADD PRIMARY KEY
            # would error on every deploy after the first, since the second
            # attempt to add the already-composite key hits Postgres'
            # "multiple primary keys" restriction.
            await conn.execute("ALTER TABLE connectors ADD COLUMN IF NOT EXISTS account_id TEXT NOT NULL DEFAULT 'owner'")
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE table_name = 'connectors' AND constraint_type = 'PRIMARY KEY'
                        AND constraint_name = 'connectors_account_provider_pkey'
                    ) THEN
                        ALTER TABLE connectors DROP CONSTRAINT IF EXISTS connectors_pkey;
                        ALTER TABLE connectors ADD CONSTRAINT connectors_account_provider_pkey PRIMARY KEY (account_id, provider);
                    END IF;
                END $$;
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    triggers TEXT[] NOT NULL DEFAULT '{}',
                    content TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT true,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """)
            # description: a short "when to use this" summary, always shown to
            # the model alongside every other enabled skill's name+description
            # on every turn (see Bootstrap._skills_context) — same two-tier
            # shape as a Claude Skill's frontmatter name+description versus
            # its full body, so the model can consider a skill exists even
            # when the deterministic trigger keywords below don't fire.
            await conn.execute("ALTER TABLE skills ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''")
            # source distinguishes who owns a skill row: 'manual' (made in
            # the app's Skills panel), 'seed' (_seed_default_skills' starter
            # set), or 'repo' (synced from skills/*.md — see
            # pipeline/skill_files.py and _sync_repo_skills below). Only
            # matters for the UI (a 'repo' skill shows read-only, since
            # editing/deleting it there wouldn't survive the next sync) —
            # nothing here enforces it server-side.
            await conn.execute("ALTER TABLE skills ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual'")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS session_repos (
                    session_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    ref TEXT NOT NULL DEFAULT '',
                    updated_at BIGINT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS session_titles (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """)
            # CABLES MAN audit trail (Step 5 — tool execution, Step 7 —
            # sub-agent delegation): every routed task and every tool call it
            # makes gets one row here, keyed by session so /status/{id} can
            # show the real backing activity for AgentFeed.jsx instead of the
            # stub it was before. Append-only — matches the rest of this
            # app's "nothing dropped" storage policy.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_events (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at BIGINT NOT NULL
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_session ON agent_events (session_id, created_at DESC)")
            # Agent runs that outlive the browser connection (pipeline/runs.py): every SSE event a run
            # emits, so a phone that locked or switched apps can fetch what it missed. Kept a day.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    tab TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS run_events (
                    run_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    PRIMARY KEY (run_id, seq)
                )
            """)
            # One active plan per session (like session_repos) — a plan
            # PlanAgent generates now survives past the single reply that
            # showed it, so "continue" (see pipeline/plan_intent.py) can
            # come back later, in a different turn, and pick up the next
            # unfinished step instead of the plan just evaporating once
            # shown. steps is the same {n, action, tool, expected_output}
            # shape PlanAgent already produces, plus a "status" field
            # ("pending"/"done") this table is responsible for.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    session_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    steps JSONB NOT NULL,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """)
            # One buddy per session (same shape as plans) — BuddyAgent
            # (agents/buddy.py) used to keep its Buddy objects in an
            # in-memory dict, but CablesMan.route() builds a fresh
            # BuddyAgent on every call, so that dict reset on every turn.
            # The whole Buddy.to_dict() blob is stored as-is; it's a
            # handful of scalar fields plus one small stats dict, not
            # worth its own columns.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS buddies (
                    session_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """)
            # DREAM's 3-gate trigger (24hr + 5 sessions + lock) used to live
            # on DreamAgent's own instance attributes, which reset on every
            # Lambda invocation (a fresh DreamAgent is constructed on every
            # AgentTool.spawn() call) and were never actually incremented
            # from anywhere in the live request path — the gate could never
            # pass. One row, keyed by a fixed id since there's only ever one
            # DREAM cycle running across the whole app, not one per session.
            # Code tab automations: a saved prompt run against a repo on a
            # schedule by the EventBridge tick (tick_handler.py), optionally
            # opening a PR with whatever it changed.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS code_automations (
                    id BIGSERIAL PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    every_seconds BIGINT NOT NULL,
                    open_pr BOOLEAN NOT NULL DEFAULT TRUE,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    last_run_at BIGINT NOT NULL DEFAULT 0,
                    last_result TEXT NOT NULL DEFAULT '',
                    created_at BIGINT NOT NULL
                )
            """)
            # MCP servers added from the app's Connectors screen; their tools
            # show up in the Code/Co-work agents (pipeline/mcp_tools.py).
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS mcp_servers (
                    account_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    auth TEXT NOT NULL DEFAULT '',
                    require_approval BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at BIGINT NOT NULL,
                    PRIMARY KEY (account_id, name)
                )
            """)
            # Reminders (Co-work's set_reminder, ProactiveAgent) — sent by the
            # KAIROS tick once due, so they survive between Lambda invocations.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id BIGSERIAL PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    due_at BIGINT NOT NULL,
                    sent_at BIGINT,
                    created_at BIGINT NOT NULL
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders (due_at) WHERE sent_at IS NULL")
            # Small named values background jobs need to remember (e.g. the
            # date KAIROS last sent the morning brief).
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS kv_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at BIGINT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dream_state (
                    id TEXT PRIMARY KEY DEFAULT 'global',
                    last_run_at BIGINT NOT NULL DEFAULT 0
                )
            """)

    async def save_memory(self, session_id: str, content: str, salience: float = 0.5,
                           embedding: list[float] | None = None) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO memories (session_id, content, salience, embedding, created_at)
                   VALUES ($1, $2, $3, $4::vector, $5) RETURNING id""",
                session_id, content, salience,
                _to_vector_literal(embedding), int(time.time()),
            )
            return row["id"]

    async def get_recent_memories(self, session_id: str | None = None, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            if session_id:
                rows = await conn.fetch(
                    """SELECT id, session_id, content, salience, created_at FROM memories
                       WHERE session_id=$1 ORDER BY salience DESC, created_at DESC LIMIT $2""",
                    session_id, limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, session_id, content, salience, created_at FROM memories
                       ORDER BY salience DESC, created_at DESC LIMIT $1""",
                    limit,
                )
            return [dict(r) for r in rows]

    async def get_pinned_memories(self, limit: int = 30) -> list[dict]:
        """Facts the user asked Sem to remember (saved at salience 1.0) — shown in every chat."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, content, created_at FROM memories WHERE salience >= $1
                   ORDER BY created_at DESC LIMIT $2""",
                PINNED_SALIENCE, limit,
            )
            return [dict(r) for r in rows]

    async def search_memories(self, term: str = "", limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, session_id, content, salience, created_at FROM memories
                   WHERE $1 = '' OR content ILIKE '%' || $1 || '%'
                   ORDER BY created_at DESC LIMIT $2""",
                term.strip(), limit,
            )
            return [dict(r) for r in rows]

    async def delete_memory(self, memory_id: int) -> bool:
        async with self._pool.acquire() as conn:
            return (await conn.execute("DELETE FROM memories WHERE id=$1", memory_id)).endswith("1")

    async def count_memories(self) -> int:
        async with self._pool.acquire() as conn:
            return (await conn.fetchrow("SELECT COUNT(*) AS n FROM memories"))["n"]

    async def semantic_search(self, embedding: list[float], top_k: int = 5) -> list[dict]:
        """Cosine-distance nearest neighbours via pgvector's <=> operator."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, session_id, content, salience,
                          embedding <=> $1::vector AS distance
                   FROM memories
                   WHERE embedding IS NOT NULL
                   ORDER BY embedding <=> $1::vector
                   LIMIT $2""",
                _to_vector_literal(embedding), top_k,
            )
            return [dict(r) for r in rows]

    async def upsert_fact(self, kind: str, content: str, embedding: list[float] | None, session_id: str = "",
                          same: float = 0.12) -> int:
        """Saves a fact, or updates the one it restates (closer than `same` in cosine distance), so "I live in
        Soweto" said ten times is one fact, and "I moved to Durban" can replace it."""
        now = int(time.time())
        vec = _to_vector_literal(embedding)
        async with self._pool.acquire() as conn:
            if vec:
                near = await conn.fetchrow(
                    """SELECT id, embedding <=> $2::vector AS distance FROM user_facts
                       WHERE kind = $1 AND embedding IS NOT NULL ORDER BY embedding <=> $2::vector LIMIT 1""",
                    kind, vec)
                if near and float(near["distance"]) < same:
                    await conn.execute("UPDATE user_facts SET content=$2, embedding=$3::vector, updated_at=$4 WHERE id=$1",
                                       near["id"], content, vec, now)
                    return near["id"]
            row = await conn.fetchrow(
                """INSERT INTO user_facts (kind, content, embedding, session_id, created_at, updated_at)
                   VALUES ($1, $2, $3::vector, $4, $5, $5) RETURNING id""", kind, content, vec, session_id, now)
            return row["id"]

    async def search_facts(self, embedding: list[float], kind: str, top_k: int = 3) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, content, embedding <=> $1::vector AS distance FROM user_facts
                   WHERE kind = $2 AND embedding IS NOT NULL ORDER BY embedding <=> $1::vector LIMIT $3""",
                _to_vector_literal(embedding), kind, top_k)
            return [dict(r) for r in rows]

    async def recent_facts(self, kind: str, limit: int = 3) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, content FROM user_facts WHERE kind = $1 ORDER BY updated_at DESC LIMIT $2",
                                    kind, limit)
            return [dict(r) for r in rows]

    async def user_turns_after(self, after_id: int, limit: int = 60) -> list[dict]:
        """The user's own messages since `after_id` (oldest first), for learning facts from them."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, session_id, content FROM conversations WHERE id > $1 AND role = 'user'
                   ORDER BY id LIMIT $2""", after_id, limit)
            return [dict(r) for r in rows]

    async def save_turn(self, session_id: str, role: str, content: str):
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO conversations (session_id, role, content, created_at) VALUES ($1,$2,$3,$4)",
                session_id, role, content, int(time.time()),
            )

    async def list_sessions(self, limit: int = 50) -> list[dict]:
        """Distinct session_ids that have at least one turn, newest first,
        with a preview (the raw first message — kept as a fallback) and,
        once generated, a real short title (see pipeline/session_title.py)
        that the frontend prefers to show instead."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT c.session_id, MAX(c.created_at) AS last_at,
                          (ARRAY_AGG(c.content ORDER BY c.created_at ASC))[1] AS preview,
                          MAX(st.title) AS title
                   FROM conversations c
                   LEFT JOIN session_titles st ON st.session_id = c.session_id
                   GROUP BY c.session_id
                   ORDER BY last_at DESC
                   LIMIT $1""",
                limit,
            )
            return [dict(r) for r in rows]

    async def search_conversations(self, term: str, window_seconds: int | None = None, limit: int = 30) -> list[dict]:
        """Literal substring search across EVERY session's conversation
        history, not scoped to the current one — the deterministic,
        grounded alternative to letting the model answer "when did I say
        X" from whatever happens to be in its current context window. A
        real query hit this: asked "when did I ask about Mandela" in one
        session, the model confidently answered from its own session
        history even though the actual mention was in a different
        session entirely, 17 hours earlier. Joins session_titles so a
        result can show a readable name instead of a bare session id."""
        async with self._pool.acquire() as conn:
            if window_seconds is not None:
                cutoff = int(time.time()) - window_seconds
                rows = await conn.fetch(
                    """SELECT c.session_id, c.role, c.content, c.created_at, st.title
                       FROM conversations c
                       LEFT JOIN session_titles st ON st.session_id = c.session_id
                       WHERE c.content ILIKE '%' || $1 || '%' AND c.created_at >= $2
                       ORDER BY c.created_at DESC LIMIT $3""",
                    term, cutoff, limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT c.session_id, c.role, c.content, c.created_at, st.title
                       FROM conversations c
                       LEFT JOIN session_titles st ON st.session_id = c.session_id
                       WHERE c.content ILIKE '%' || $1 || '%'
                       ORDER BY c.created_at DESC LIMIT $2""",
                    term, limit,
                )
            return [dict(r) for r in rows]

    async def get_dream_last_run(self) -> int:
        """0 if DREAM has never run — that's a real "24hr ago" for gate
        purposes (GATE_HOURS is trivially satisfied), not a missing value
        to special-case."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT last_run_at FROM dream_state WHERE id='global'")
            return row["last_run_at"] if row else 0

    async def set_dream_last_run(self, ts: int):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO dream_state (id, last_run_at) VALUES ('global', $1)
                   ON CONFLICT (id) DO UPDATE SET last_run_at=$1""",
                ts,
            )

    async def count_sessions_since(self, since_ts: int) -> int:
        """Distinct sessions with at least one turn since `since_ts` —
        DREAM's "5 sessions" gate, computed from real conversation
        activity instead of an in-memory counter that reset every Lambda
        invocation and was never actually incremented anywhere."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(DISTINCT session_id) AS n FROM conversations WHERE created_at >= $1",
                since_ts,
            )
            return row["n"] if row else 0

    async def delete_session(self, session_id: str):
        """Removes a session's chat history entirely — conversations,
        title, and its embedded memories. Deliberately leaves session_repos/
        plans/buddies/agent_events alone: those are keyed the same way but
        represent separate state (an attached repo, an in-progress plan, a
        buddy) a user deleting a chat transcript likely doesn't mean to
        wipe too, and none of them are shown anywhere the deleted session
        would still be visible."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM conversations WHERE session_id=$1", session_id)
                await conn.execute("DELETE FROM session_titles WHERE session_id=$1", session_id)
                await conn.execute("DELETE FROM memories WHERE session_id=$1", session_id)

    async def get_conversation(self, session_id: str, limit: int = 200) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT role, content, created_at FROM conversations
                   WHERE session_id=$1 ORDER BY created_at ASC LIMIT $2""",
                session_id, limit,
            )
            return [dict(r) for r in rows]

    async def get_account(self, account_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, passphrase_hash, role, token_version FROM accounts WHERE id=$1", account_id,
            )
            return dict(row) if row else None

    async def upsert_account(self, account_id: str, passphrase_hash: str, role: str = "owner"):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO accounts (id, passphrase_hash, role, created_at)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (id) DO UPDATE SET passphrase_hash=$2, role=$3""",
                account_id, passphrase_hash, role, int(time.time()),
            )

    async def get_token_version(self, account_id: str) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT token_version FROM accounts WHERE id=$1", account_id) or 0

    async def set_passphrase(self, account_id: str, passphrase_hash: str) -> int:
        """New passphrase hash; bumps token_version so every existing token and MCP key is signed out."""
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "UPDATE accounts SET passphrase_hash=$2, token_version=token_version+1 WHERE id=$1 RETURNING token_version",
                account_id, passphrase_hash,
            )

    async def get_connector(self, account_id: str, provider: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT provider, token, refresh_token, expires_at FROM connectors WHERE account_id=$1 AND provider=$2",
                account_id, provider,
            )
            return dict(row) if row else None

    async def list_connectors(self, account_id: str) -> list[str]:
        """Provider names only, for this account — never the token."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT provider FROM connectors WHERE account_id=$1 ORDER BY provider", account_id,
            )
            return [r["provider"] for r in rows]

    async def upsert_connector(self, account_id: str, provider: str, token: str,
                                refresh_token: str | None = None, expires_at: int | None = None):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO connectors (account_id, provider, token, refresh_token, expires_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (account_id, provider) DO UPDATE SET token=$3, refresh_token=$4, expires_at=$5, updated_at=$6""",
                account_id, provider, token, refresh_token, expires_at, int(time.time()),
            )

    async def delete_connector(self, account_id: str, provider: str):
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM connectors WHERE account_id=$1 AND provider=$2", account_id, provider)

    async def get_session_title(self, session_id: str) -> str | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT title FROM session_titles WHERE session_id=$1", session_id,
            )

    async def set_session_title(self, session_id: str, title: str):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_titles (session_id, title, updated_at)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (session_id) DO UPDATE SET title=$2, updated_at=$3""",
                session_id, title, int(time.time()),
            )

    async def save_agent_event(self, session_id: str, agent: str, action: str):
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO agent_events (session_id, agent, action, created_at) VALUES ($1,$2,$3,$4)",
                session_id, agent, action, int(time.time()),
            )

    async def start_run(self, run_id: str, account_id: str, tab: str, keep_seconds: int = 86400):
        now = int(time.time())
        async with self._pool.acquire() as conn:
            old = [r["run_id"] for r in await conn.fetch("SELECT run_id FROM runs WHERE updated_at < $1", now - keep_seconds)]
            if old:
                await conn.execute("DELETE FROM run_events WHERE run_id = ANY($1::text[])", old)
                await conn.execute("DELETE FROM runs WHERE run_id = ANY($1::text[])", old)
            await conn.execute(
                "INSERT INTO runs (run_id, account_id, tab, status, created_at, updated_at) VALUES ($1,$2,$3,'running',$4,$4) "
                "ON CONFLICT (run_id) DO NOTHING", run_id, account_id, tab, now,
            )

    async def add_run_events(self, run_id: str, events: list[tuple[int, str]]) -> str:
        """Appends (seq, data) rows and returns the run's status, so the runner sees a cancel."""
        async with self._pool.acquire() as conn:
            if events:
                await conn.executemany(
                    "INSERT INTO run_events (run_id, seq, data) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                    [(run_id, seq, data) for seq, data in events],
                )
            return await conn.fetchval(
                "UPDATE runs SET updated_at=$2 WHERE run_id=$1 RETURNING status", run_id, int(time.time()),
            ) or ""

    async def set_run_status(self, run_id: str, status: str, account_id: str | None = None) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE runs SET status=$2, updated_at=$3 WHERE run_id=$1 AND ($4::text IS NULL OR account_id=$4)",
                run_id, status, int(time.time()), account_id,
            )
            return result.endswith(" 1")

    async def get_run(self, run_id: str, account_id: str, after: int = 0, limit: int = 100) -> dict | None:
        async with self._pool.acquire() as conn:
            run = await conn.fetchrow(
                "SELECT status, updated_at FROM runs WHERE run_id=$1 AND account_id=$2", run_id, account_id,
            )
            if not run:
                return None
            rows = await conn.fetch(
                "SELECT seq, data FROM run_events WHERE run_id=$1 AND seq > $2 ORDER BY seq LIMIT $3", run_id, after, limit,
            )
            return {"status": run["status"], "updated_at": run["updated_at"], "events": [dict(r) for r in rows]}

    async def get_latest_agent_event(self, session_id: str) -> dict | None:
        """Most recent CABLES MAN activity for this session — what
        AgentFeed.jsx polls every few seconds via /status/{session_id}."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT agent, action, created_at AS ts FROM agent_events "
                "WHERE session_id=$1 ORDER BY created_at DESC LIMIT 1",
                session_id,
            )
            return dict(row) if row else None

    async def get_recent_agent_events(self, session_id: str, since_id: int = 0, limit: int = 30) -> list[dict]:
        """Every event for this session with id > since_id, oldest first —
        what AgentFeed.jsx polls, unlike get_latest_agent_event's single
        row, so a burst of several tool calls within one turn (a memory
        search followed by a web search, say) doesn't lose all but the
        last one to a 3s poll interval. Ordered by id (BIGSERIAL), not
        created_at — that column is whole-second precision, so several
        events landing in the same second can't be ordered by it alone."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, agent, action, created_at AS ts FROM agent_events "
                "WHERE session_id=$1 AND id > $2 ORDER BY id ASC LIMIT $3",
                session_id, since_id, limit,
            )
            return [dict(r) for r in rows]

    async def get_active_repo(self, session_id: str) -> dict | None:
        """The repo this session last cloned via "Add repo" — lets a
        follow-up question like "what's in the readme" resolve against a
        specific repo without the user repeating owner/repo every time."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT provider, repo, ref FROM session_repos WHERE session_id=$1", session_id,
            )
            return dict(row) if row else None

    async def set_active_repo(self, session_id: str, provider: str, repo: str, ref: str = ""):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO session_repos (session_id, provider, repo, ref, updated_at)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (session_id) DO UPDATE SET provider=$2, repo=$3, ref=$4, updated_at=$5""",
                session_id, provider, repo, ref, int(time.time()),
            )

    async def save_plan(self, session_id: str, goal: str, steps: list[dict]):
        """One active plan per session — a new plan (asking to plan
        something else) replaces the old one outright, same as
        set_active_repo. Each step gets status="pending" if the caller
        didn't already set one (PlanAgent's own steps never do)."""
        stamped = [{**s, "status": s.get("status", "pending")} for s in steps]
        async with self._pool.acquire() as conn:
            now = int(time.time())
            await conn.execute(
                """INSERT INTO plans (session_id, goal, steps, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $4)
                   ON CONFLICT (session_id) DO UPDATE SET goal=$2, steps=$3, updated_at=$4""",
                session_id, goal, json.dumps(stamped), now,
            )

    async def get_active_plan(self, session_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT goal, steps FROM plans WHERE session_id=$1", session_id,
            )
            if not row:
                return None
            return {"goal": row["goal"], "steps": json.loads(row["steps"])}

    async def add_reminder(self, account_id: str, message: str, due_at: int) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO reminders (account_id, message, due_at, created_at) VALUES ($1, $2, $3, $4) RETURNING *",
                account_id, message, due_at, int(time.time()),
            )
            return dict(row)

    async def list_reminders(self, account_id: str, include_sent: bool = False) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM reminders WHERE account_id=$1 AND ($2 OR sent_at IS NULL) ORDER BY due_at LIMIT 100",
                account_id, include_sent,
            )
            return [dict(r) for r in rows]

    async def delete_reminder(self, account_id: str, reminder_id: int) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM reminders WHERE id=$1 AND account_id=$2", reminder_id, account_id)
            return result.endswith("1")

    async def claim_due_reminders(self, limit: int = 20) -> list[dict]:
        """Marks due reminders sent in the same statement that returns them,
        so overlapping ticks can't deliver one twice."""
        now = int(time.time())
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """UPDATE reminders SET sent_at=$1 WHERE id IN (
                       SELECT id FROM reminders WHERE sent_at IS NULL AND due_at <= $1
                       ORDER BY due_at LIMIT $2 FOR UPDATE SKIP LOCKED
                   ) RETURNING *""",
                now, limit,
            )
            return [dict(r) for r in rows]

    async def get_state(self, key: str) -> str | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT value FROM kv_state WHERE key=$1", key)

    async def set_state(self, key: str, value: str):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO kv_state (key, value, updated_at) VALUES ($1, $2, $3)
                   ON CONFLICT (key) DO UPDATE SET value=$2, updated_at=$3""",
                key, value, int(time.time()),
            )

    async def list_mcp_servers(self, account_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name, url, auth, require_approval FROM mcp_servers WHERE account_id=$1 ORDER BY name",
                account_id,
            )
            return [dict(r) for r in rows]

    async def upsert_mcp_server(self, account_id: str, name: str, url: str, auth: str, require_approval: bool):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO mcp_servers (account_id, name, url, auth, require_approval, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (account_id, name) DO UPDATE SET url=$3, auth=$4, require_approval=$5""",
                account_id, name, url, auth, require_approval, int(time.time()),
            )

    async def delete_mcp_server(self, account_id: str, name: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM mcp_servers WHERE account_id=$1 AND name=$2", account_id, name)
            return result.endswith("1")

    async def list_code_automations(self, account_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM code_automations WHERE account_id=$1 ORDER BY id", account_id,
            )
            return [dict(r) for r in rows]

    async def create_code_automation(self, account_id: str, provider: str, repo: str, prompt: str,
                                     every_seconds: int, open_pr: bool) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO code_automations (account_id, provider, repo, prompt, every_seconds, open_pr, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""",
                account_id, provider, repo, prompt, every_seconds, open_pr, int(time.time()),
            )
            return dict(row)

    async def set_code_automation_enabled(self, account_id: str, automation_id: int, enabled: bool) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE code_automations SET enabled=$1 WHERE id=$2 AND account_id=$3",
                enabled, automation_id, account_id,
            )
            return result.endswith("1")

    async def delete_code_automation(self, account_id: str, automation_id: int) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM code_automations WHERE id=$1 AND account_id=$2", automation_id, account_id,
            )
            return result.endswith("1")

    async def claim_due_code_automation(self) -> dict | None:
        """The oldest-due enabled automation, with last_run_at bumped to now
        in the same statement so an overlapping tick can't run it twice."""
        now = int(time.time())
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE code_automations SET last_run_at=$1
                   WHERE id = (
                       SELECT id FROM code_automations
                       WHERE enabled AND last_run_at + every_seconds <= $1
                       ORDER BY last_run_at LIMIT 1 FOR UPDATE SKIP LOCKED
                   ) RETURNING *""",
                now,
            )
            return dict(row) if row else None

    async def set_code_automation_result(self, automation_id: int, result: str):
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE code_automations SET last_result=$1 WHERE id=$2", result[:2000], automation_id,
            )

    async def get_buddy(self, session_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM buddies WHERE session_id=$1", session_id,
            )
            return json.loads(row["data"]) if row else None

    async def save_buddy(self, session_id: str, data: dict):
        async with self._pool.acquire() as conn:
            now = int(time.time())
            await conn.execute(
                """INSERT INTO buddies (session_id, data, updated_at)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (session_id) DO UPDATE SET data=$2, updated_at=$3""",
                session_id, json.dumps(data), now,
            )

    async def update_plan_step(self, session_id: str, step_n, status: str, result: str = ""):
        """Marks one step done (or whatever status) in place. Steps are a
        handful of items in one small JSONB column — reading the whole
        plan, mutating the one step, and writing it back whole is simpler
        and plenty fast at this size, versus reaching for Postgres's own
        jsonb_set path-update functions for a table this small."""
        plan = await self.get_active_plan(session_id)
        if not plan:
            return
        for step in plan["steps"]:
            if step.get("n") == step_n:
                step["status"] = status
                if result:
                    step["result"] = result
                break
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE plans SET steps=$1, updated_at=$2 WHERE session_id=$3",
                json.dumps(plan["steps"]), int(time.time()), session_id,
            )

    async def list_skills(self, enabled_only: bool = False) -> list[dict]:
        async with self._pool.acquire() as conn:
            query = "SELECT id, name, description, triggers, content, enabled, created_at, source FROM skills"
            if enabled_only:
                query += " WHERE enabled = true"
            query += " ORDER BY created_at ASC"
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def upsert_skill(self, skill_id: str, name: str, triggers: list[str], content: str,
                            description: str = "", enabled: bool = True, source: str = "manual"):
        async with self._pool.acquire() as conn:
            now = int(time.time())
            await conn.execute(
                """INSERT INTO skills (id, name, description, triggers, content, enabled, source, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
                   ON CONFLICT (id) DO UPDATE SET name=$2, description=$3, triggers=$4, content=$5, enabled=$6, source=$7, updated_at=$8""",
                skill_id, name, description, triggers, content, enabled, source, now,
            )

    async def _seed_default_skills(self):
        """Populates a genuinely empty skills table with _DEFAULT_SKILLS, once.
        Checked with a plain COUNT rather than per-id ON CONFLICT DO NOTHING —
        the latter would silently re-add a seed skill the user deliberately
        deleted, every time this Lambda environment cold-starts. An empty
        table only ever happens once (a fresh deploy, or the user having
        never added a skill), so this never overwrites their own edits."""
        async with self._pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM skills")
            if count:
                return
        for skill in _DEFAULT_SKILLS:
            await self.upsert_skill(
                skill["id"], skill["name"], skill["triggers"], skill["content"],
                description=skill["description"], source="seed",
            )

    async def _sync_repo_skills(self):
        """Repo-authored skill .md files (skills/*.md — see
        skills/README.md and pipeline/skill_files.py) sync into the DB on
        every connect, i.e. shortly after every deploy, since that's when
        a fresh Lambda container cold-starts. Unlike _seed_default_skills,
        this always upserts, never gated on an empty-table check — the
        file is the actual source of truth for its own skill, so a pushed
        edit should always win. Every id this writes is prefixed 'repo-'
        (see skill_files.parse_skill_file), so it can never collide with
        or overwrite a manually-created or seeded skill."""
        from pipeline.skill_files import load_skill_files
        for skill in load_skill_files():
            await self.upsert_skill(
                skill["id"], skill["name"], skill["triggers"], skill["content"],
                description=skill["description"], source="repo",
            )

    async def delete_skill(self, skill_id: str):
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM skills WHERE id=$1", skill_id)

    async def get_user_model(self, session_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM user_models WHERE session_id=$1", session_id)
            return json.loads(row["data"]) if row else None

    async def save_user_model(self, session_id: str, model: dict):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO user_models (session_id, data, updated_at) VALUES ($1, $2, $3)
                   ON CONFLICT (session_id) DO UPDATE SET data=$2, updated_at=$3""",
                session_id, json.dumps(model), int(time.time()),
            )

    async def update_memory_salience(self, memory_id: int, salience: float,
                                      embedding: list[float] | None = None):
        """Used by DREAM consolidation — re-scores/re-embeds a row in place, never inserts a duplicate."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE memories SET salience=$1, embedding=$2::vector WHERE id=$3",
                salience, _to_vector_literal(embedding), memory_id,
            )

    async def write_memory_index(self, memories: list[dict]):
        for m in memories:
            await self.save_memory(
                m.get("session_id", "global"),
                m.get("content", ""),
                m.get("salience", 0.5),
                m.get("embedding"),
            )


def _to_vector_literal(embedding: list[float] | None) -> str | None:
    if not embedding:
        return None
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


# ─── Warm-start singleton ────────────────────────────────────────────────────
# One pool per Lambda execution environment, reused across invocations while warm.

_store: NeonStore | None = None


async def get_store() -> NeonStore:
    global _store
    if _store is None:
        _store = NeonStore()
    await _store.connect(settings.NEON_DATABASE_URL)  # no-op if already connected
    return _store

