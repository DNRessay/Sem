import json
import time

import asyncpg

from config import settings

_EMBED_DIM = 384  # matches the Modal sentence-transformers model (all-MiniLM-L6-v2)


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

