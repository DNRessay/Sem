import pytest

from pipeline import turn_router
from tools import laya_client


def _answers(repo, recall, remember):
    return {"repo": {"noul": repo}, "recall": {"noul": recall}, "remember": {"noul": remember}}


@pytest.mark.asyncio
async def test_laya_decides_what_the_reply_needs(monkeypatch):
    async def decide(state, questions, timeout=1.5):
        assert set(questions) == {"repo", "recall", "remember"}
        return _answers(0.1, 0.02, 0.9)

    monkeypatch.setattr(laya_client, "decide", decide)
    r = await turn_router.route("my kitten's name is Biscuit, keep that in your head")
    assert r == {"repo": False, "recall": False, "remember": True, "laya": True}


@pytest.mark.asyncio
async def test_laya_catches_code_questions_the_keywords_miss(monkeypatch):
    async def decide(state, questions, timeout=1.5):
        return _answers(0.8, 0.5, 0.1)

    monkeypatch.setattr(laya_client, "decide", decide)
    r = await turn_router.route("why does the login thing keep kicking me out?")
    assert r["repo"] and r["recall"] and not r["remember"]


@pytest.mark.asyncio
async def test_without_laya_the_old_behaviour_holds(monkeypatch):
    async def down(state, questions, timeout=1.5):
        return None

    monkeypatch.setattr(laya_client, "decide", down)
    assert await turn_router.route("what's the weather") == {"repo": False, "recall": True, "remember": False, "laya": False}
    r = await turn_router.route("remember that my sister is called Lindi")
    assert r["remember"] and r["recall"]
    assert (await turn_router.route("fix the bug in router.py"))["repo"]


def test_laya_url_follows_the_video_app(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "LAYA_URL", "")
    monkeypatch.setattr(settings, "MODAL_VIDEO_URL", "https://me--semblance-video-api.modal.run/")
    assert laya_client.url() == "https://me--semblance-laya-api.modal.run/"
    monkeypatch.setattr(settings, "LAYA_URL", "off")
    assert laya_client.url() == ""


@pytest.mark.asyncio
async def test_slow_or_broken_laya_never_holds_up_a_reply(monkeypatch):
    import httpx
    import respx

    from config import settings
    monkeypatch.setattr(settings, "LAYA_URL", "https://laya.test/")
    laya_client._cache.clear()
    with respx.mock:
        respx.post("https://laya.test/").mock(side_effect=httpx.ReadTimeout("slow"))
        assert await laya_client.decide("hi", {"q": {"type": "noul", "instructions": "?"}}) is None
        respx.post("https://laya.test/").respond(json={"ok": False, "error": "unauthorized"})
        assert await laya_client.decide("hi", {"q": {"type": "noul", "instructions": "?"}}) is None
        respx.post("https://laya.test/").respond(json={"ok": True, "answers": {"q": {"noul": 0.9}}})
        assert await laya_client.decide("hi", {"q": {"type": "noul", "instructions": "?"}}) == {"q": {"noul": 0.9}}


@pytest.mark.asyncio
async def test_remember_pins_a_fact_and_small_talk_skips_memory_search(monkeypatch):
    from pipeline import bootstrap as bootstrap_mod

    saved = []

    class Store:
        async def list_skills(self, enabled_only=False):
            return []

        async def save_turn(self, *a):
            pass

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            saved.append((content, salience))

        async def get_pinned_memories(self, limit=30):
            return [{"content": c} for c, s in saved if s >= 1.0]

    async def store():
        return Store()

    async def embed(text):
        return None

    async def decide(state, questions, timeout=1.5):
        return _answers(0.0, 0.01, 0.95 if "remember" in state else 0.01)

    monkeypatch.setattr(bootstrap_mod, "get_store", store)
    monkeypatch.setattr(bootstrap_mod, "embed_text", embed)
    monkeypatch.setattr(laya_client, "decide", decide)
    b = bootstrap_mod.Bootstrap()
    searched = []

    async def retrieve(query, top_k=5):
        searched.append(query)
        return []

    b.sem_retrieval.retrieve = retrieve
    prompts = []

    async def stream(messages, model=None, session_id="default", **kw):
        prompts.append(messages[0]["content"])
        yield "noted"

    b.query_engine.stream_llm = stream
    out = [p async for p in b.run("remember my kitten is called Biscuit", "s1", [])]
    assert {"tool": {"kind": "memory", "label": "Remembered", "detail": "remember my kitten is called Biscuit"}} in out
    assert ("remember my kitten is called Biscuit", 1.0) in saved
    [p async for p in b.run("thanks!", "s1", [])]
    assert searched == [] and "Biscuit" in prompts[-1]
