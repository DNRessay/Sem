import pytest
import respx
from httpx import Response

from config import settings
from storage.embeddings import _EMBED_DIM, embed_text


@pytest.mark.asyncio
async def test_embed_text_falls_back_to_deterministic_vector_without_modal_url(monkeypatch):
    monkeypatch.setattr(settings, "MODAL_EMBEDDINGS_URL", "")
    vec1 = await embed_text("hello world")
    vec2 = await embed_text("hello world")
    vec3 = await embed_text("something else")

    assert len(vec1) == _EMBED_DIM
    assert vec1 == vec2  # deterministic
    assert vec1 != vec3


@pytest.mark.asyncio
async def test_embed_text_calls_modal_endpoint_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "MODAL_EMBEDDINGS_URL", "https://modal.example/embed")

    with respx.mock:
        respx.post("https://modal.example/embed").mock(
            return_value=Response(200, json={"embedding": [0.1, 0.2, 0.3]})
        )
        vec = await embed_text("hello")

    assert vec == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_embed_text_falls_back_when_modal_call_fails(monkeypatch):
    monkeypatch.setattr(settings, "MODAL_EMBEDDINGS_URL", "https://modal.example/embed")

    with respx.mock:
        respx.post("https://modal.example/embed").mock(return_value=Response(500))
        vec = await embed_text("hello")

    assert len(vec) == _EMBED_DIM
