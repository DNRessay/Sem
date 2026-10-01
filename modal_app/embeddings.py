"""
Modal function: sentence-transformers embeddings as an HTTP endpoint.

Deploy:
    pip install modal
    modal setup
    modal deploy modal_app/embeddings.py

Modal prints two URLs — set MODAL_EMBEDDINGS_URL to the "-embed" one. The
"-emotion" one (the emotion classifier, same container) is found automatically
from it; set MODAL_EMOTION_URL only if yours is named differently.
Free tier: $30/month credit. This function scales to zero between calls, so a
single user's traffic costs a few cents a month at most.
"""
import modal

app = modal.App("semblance-embeddings")

image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "sentence-transformers>=3.0.0",
    "transformers>=4.40",
    "fastapi>=0.115.0",
)

with image.imports():
    from sentence_transformers import SentenceTransformer
    from transformers import pipeline

_MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim, matches storage/neon_store.py
# Open-source DistilRoBERTa fine-tuned on six emotion datasets (Hartmann 2022):
# anger, disgust, fear, joy, neutral, sadness, surprise. Small enough for CPU.
_EMOTION_MODEL = "j-hartmann/emotion-english-distilroberta-base"


@app.cls(image=image, scaledown_window=120)
class Embedder:
    @modal.enter()
    def load(self):
        self.model = SentenceTransformer(_MODEL_NAME)
        self.emotions = pipeline("text-classification", model=_EMOTION_MODEL, top_k=None, truncation=True)

    @modal.fastapi_endpoint(method="POST")
    def embed(self, body: dict):
        text = body.get("text", "")
        vector = self.model.encode(text, normalize_embeddings=True).tolist()
        return {"embedding": vector, "model": _MODEL_NAME}

    @modal.fastapi_endpoint(method="POST")
    def emotion(self, body: dict):
        """{"scores": {"joy": 0.81, "neutral": 0.1, ...}} for the text."""
        text = (body.get("text") or "")[:2000]
        if not text.strip():
            return {"scores": {"neutral": 1.0}, "model": _EMOTION_MODEL}
        results = self.emotions(text)[0]
        return {"scores": {r["label"]: round(float(r["score"]), 4) for r in results}, "model": _EMOTION_MODEL}
