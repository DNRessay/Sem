import time

from memory.salience_engine import SalienceEngine
from tau.tau_engine import TAUEngine, _joined


def test_salience_survives_missing_timestamps_and_stays_between_0_and_1():
    s = SalienceEngine()
    assert 0 <= s.score({"created_at": None}, {}, 0.5) <= 1
    assert s.score({"created_at": time.time() + 86400}, {}, 0) <= 1  # a future timestamp doesn't push it past 1
    assert s.score({"created_at": time.time()}, {}, -1.1) >= 0     # a negative surprise doesn't make it negative


def test_profile_lists_and_strings_both_read_well():
    assert _joined(["Python", "React"]) == "Python, React"
    assert _joined("Python") == "Python"  # used to come out as "P, y, t, h, o, n"
    assert _joined([1, "two"]) == "1, two"
    ctx = TAUEngine()._build_context({"skills": "Python", "projects": ["Sem", "C-Lab"]}, {})
    assert "Skills/stack: Python" in ctx and "Active projects: Sem, C-Lab" in ctx


async def test_memory_search_scores_similarity_and_skips_without_real_embeddings(monkeypatch):
    from memory import sem_retrieval

    class Store:
        async def semantic_search(self, embedding, top_k=5):
            return [{"content": "close", "distance": 0.1}, {"content": "far", "distance": 0.9}]

    async def store():
        return Store()

    async def real(text):
        return [0.1] * 384

    monkeypatch.setattr(sem_retrieval, "get_store", store)
    monkeypatch.setattr(sem_retrieval, "embed_text_or_none", real)
    rows = await sem_retrieval.SEMRetrieval().retrieve("x")
    assert [(r["content"], r["score"]) for r in rows] == [("close", 0.9), ("far", 0.1)]  # higher = closer

    async def down(text):
        return None

    monkeypatch.setattr(sem_retrieval, "embed_text_or_none", down)
    assert await sem_retrieval.SEMRetrieval().retrieve("x") == []
