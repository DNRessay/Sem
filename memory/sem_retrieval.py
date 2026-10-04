from storage.embeddings import embed_text, embed_text_or_none
from storage.neon_store import get_store


class SEMRetrieval:
    """Semantic memory retrieval — pgvector cosine search over the memories table."""

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Closest memories first. "score" is similarity (1 = same meaning). Without a real embedding (the
        embeddings service is down or not set up) there's nothing meaningful to search with, so no results."""
        embedding = await embed_text_or_none(query)
        if embedding is None:
            return []
        store = await get_store()
        rows = await store.semantic_search(embedding, top_k=top_k)
        return [
            {
                "content": r.get("content", ""),
                "score": round(1 - float(r.get("distance", 1)), 4),  # pgvector <=> gives distance; lower = closer
                "metadata": {"session_id": r.get("session_id"), "salience": r.get("salience")},
            }
            for r in rows
        ]

    async def embed(self, text: str) -> list[float]:
        return await embed_text(text)
