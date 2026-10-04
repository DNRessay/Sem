"""
Embedding generation client.

Real embeddings run on Modal (see modal_app/embeddings.py) — sentence-transformers
is a few hundred MB and slow to cold-start, so it stays off the Lambda and gets
called over HTTP instead. Modal's free tier ($30/month credit) covers this
comfortably for a single user.

If MODAL_EMBEDDINGS_URL isn't configured (local dev, tests), falls back to a
deterministic hash vector so the rest of the pipeline still runs — it just
won't be semantically meaningful.
"""
import hashlib
import logging

import httpx

from config import settings

_EMBED_DIM = 384
log = logging.getLogger("semblance.embeddings")


async def embed_text_or_none(text: str) -> list[float] | None:
    """The real embedding, or None when the service isn't set up or failed (logged)."""
    if not settings.MODAL_EMBEDDINGS_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(settings.MODAL_EMBEDDINGS_URL, json={"text": text})
            r.raise_for_status()
            return r.json()["embedding"]
    except Exception as e:
        log.warning("embedding failed (%s): memory search is skipped for this message", type(e).__name__)
        return None


async def embed_text(text: str) -> list[float]:
    """For storing: a real embedding when possible, else a deterministic placeholder so the row still saves
    (it just won't be found by meaning). Searching should use embed_text_or_none instead."""
    return await embed_text_or_none(text) or _fallback_vector(text)


def _fallback_vector(text: str) -> list[float]:
    out = []
    seed = text.encode()
    while len(out) < _EMBED_DIM:
        seed = hashlib.sha256(seed).digest()
        out.extend(b / 255.0 for b in seed)
    return out[:_EMBED_DIM]
