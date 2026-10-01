
import pytest
import respx
from httpx import Response

from tau import emotion_engine, pacific
from tau.emotion_engine import EMU, NatureSCIEngine
from tau.tau_engine import TAUEngine

EMB = "https://me--semblance-embeddings-embedder-embed.modal.run"
EMO = "https://me--semblance-embeddings-embedder-emotion.modal.run"


@pytest.fixture
def modal(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "MODAL_EMBEDDINGS_URL", EMB)
    monkeypatch.setattr(settings, "MODAL_EMOTION_URL", "")


def test_emotion_url_is_derived_from_the_embeddings_url(modal):
    assert emotion_engine.emotion_url() == EMO


@pytest.mark.asyncio
async def test_classify_uses_the_model(modal):
    with respx.mock:
        respx.post(EMO).mock(return_value=Response(200, json={"scores": {"anger": 0.91, "neutral": 0.05}}))
        emu = await NatureSCIEngine().classify("this deploy broke again")
    assert emu.label == "anger" and emu.confidence == 0.91 and emu.valence < 0
    assert "frustrated" in NatureSCIEngine.guidance(emu)


@pytest.mark.asyncio
async def test_classify_falls_back_to_the_word_list(modal):
    with respx.mock:
        respx.post(EMO).mock(return_value=Response(503))
        emu = await NatureSCIEngine().classify("I'm so worried about this")
    assert emu.label == "fear"


def test_no_guidance_for_neutral_or_unsure_readings():
    assert NatureSCIEngine.guidance(EMU("neutral", 0.99, 0, 0)) == ""
    assert NatureSCIEngine.guidance(EMU("anger", 0.3, -0.8, 0.9)) == ""


class Store:
    def __init__(self, memories=(), model=None):
        self.memories, self.models, self.state = list(memories), {"owner": model or {}}, {}

    async def get_user_model(self, key):
        return self.models.get(key)

    async def save_user_model(self, key, model):
        self.models[key] = model

    async def get_recent_memories(self, session_id=None, limit=50):
        return self.memories

    async def get_state(self, key):
        return self.state.get(key)

    async def set_state(self, key, value):
        self.state[key] = value


@pytest.mark.asyncio
async def test_tone_line_is_per_turn_and_saved_ocean_is_used(monkeypatch):
    store = Store(model={"name": "Le Roy", "ocean": {"O": 0.9, "C": 0.8, "E": 0.3, "A": 0.6, "N": 0.2},
                         "observed_style": "Short answers, no fluff."})

    async def fake_store():
        return store

    monkeypatch.setattr("tau.tau_engine.get_store", fake_store)
    cache = {}
    engine = TAUEngine()
    monkeypatch.setattr(engine.cache, "get", lambda k: cache.get(k))
    monkeypatch.setattr(engine.cache, "set", lambda k, v: cache.__setitem__(k, v))

    async def angry(text):
        return EMU("anger", 0.9, -0.8, 0.9)

    async def calm(text):
        return EMU("neutral", 0.9, 0, 0)

    monkeypatch.setattr(engine.emotion, "classify", angry)
    first = await engine.observe_and_inject("s1", "why is this broken", [])
    assert "O=0.90" in first and "Short answers, no fluff." in first and "frustrated" in first
    assert "frustrated" not in cache["s1"]  # tone isn't cached with the profile
    monkeypatch.setattr(engine.emotion, "classify", calm)
    assert "Tone for this reply" not in await engine.observe_and_inject("s1", "thanks", [])


@pytest.mark.asyncio
async def test_pacific_refresh_saves_clamped_traits_once_a_day(monkeypatch):
    store = Store(memories=[{"content": f"message {i}", "created_at": i} for i in range(20)])

    async def fake_store():
        return store

    seen = {}

    async def fake_complete(model, messages, **kw):
        seen["prompt"] = messages[0]["content"]
        return {"content": 'Here: {"O": 0.8, "C": 1.4, "E": 0.2, "A": 0.5, "N": -1, "style": "Direct, code first."}'}

    monkeypatch.setattr("storage.neon_store.get_store", fake_store)
    monkeypatch.setattr("pipeline.llm_providers.complete", fake_complete)
    result = await pacific.refresh_profile()
    assert result["ocean"] == {"O": 0.8, "C": 1.0, "E": 0.2, "A": 0.5, "N": 0.0}
    assert store.models["owner"]["observed_style"] == "Direct, code first."
    assert "message 19" in seen["prompt"]
    assert await pacific.refresh_profile() is None  # already ran today


@pytest.mark.asyncio
async def test_pacific_waits_for_enough_messages(monkeypatch):
    store = Store(memories=[{"content": "hi", "created_at": 1}])

    async def fake_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_store)
    assert await pacific.refresh_profile() is None
    assert "ocean" not in store.models["owner"]
