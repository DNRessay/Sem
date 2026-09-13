from memory.sem_retrieval import SEMRetrieval
from storage.neon_store import get_store


class MemoryLoad:
    def __init__(self):
        self.sem = SEMRetrieval()

    async def coordinate(self, query: str, session_id: str = "default") -> dict:
        semantic = await self.sem.retrieve(query, top_k=5)
        raw = []
        try:
            db = await get_store()
            raw = await db.get_recent_memories(session_id=session_id, limit=20)
        except Exception:
            pass
        transcripts = self.grep_transcripts(query)

        seen, merged = set(), []
        for m in semantic + raw:
            c = m.get("content", "")
            if c and c not in seen:
                seen.add(c)
                merged.append(m)

        return {"memories": merged, "transcript_hits": transcripts}

    def grep_transcripts(self, query: str) -> list[dict]:
        import os
        import re
        hits = []
        pattern = re.compile(re.escape(query[:40]), re.IGNORECASE)
        transcript_dir = "./data/transcripts"
        if not os.path.isdir(transcript_dir):
            return hits
        for fname in os.listdir(transcript_dir)[:10]:
            fpath = os.path.join(transcript_dir, fname)
            try:
                with open(fpath, errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if pattern.search(line):
                            hits.append({"file": fname, "line": i, "content": line.strip()[:200]})
                            if len(hits) >= 10:
                                return hits
            except Exception:
                continue
        return hits