from storage.embeddings import embed_text
from storage.neon_store import get_store


class SEMRetrieval:
    """Semantic memory retrieval — pgvector cosine search over the memories table."""

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        embedding = await self.embed(query)
        store = await get_store()
        rows = await store.semantic_search(embedding, top_k=top_k)
        return [
            {
                "content": r.get("content", ""),
                "score": r.get("distance", 0),
                "metadata": {"session_id": r.get("session_id"), "salience": r.get("salience")},
            }
            for r in rows
        ]

    async def embed(self, text: str) -> list[float]:
        return await embed_text(text)
