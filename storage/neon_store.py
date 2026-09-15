import json
import time

import asyncpg

from config import settings

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
                "SELECT id, passphrase_hash, role FROM accounts WHERE id=$1", account_id,
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

