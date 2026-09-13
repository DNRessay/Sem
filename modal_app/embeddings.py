"""
Modal function: sentence-transformers embeddings as an HTTP endpoint.

Deploy:
    pip install modal
    modal setup
    modal deploy modal_app/embeddings.py

Modal prints a URL — set MODAL_EMBEDDINGS_URL to it in the Lambda environment.
Free tier: $30/month credit. This function scales to zero between calls, so a
single user's traffic costs a few cents a month at most.
"""
import modal

app = modal.App("semblance-embeddings")

image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "sentence-transformers>=3.0.0",
    "fastapi>=0.115.0",
)

with image.imports():
    from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim, matches storage/neon_store.py


@app.cls(image=image, scaledown_window=120)
class Embedder:
    @modal.enter()
    def load(self):
        self.model = SentenceTransformer(_MODEL_NAME)

    @modal.fastapi_endpoint(method="POST")
    def embed(self, body: dict):
        text = body.get("text", "")
        vector = self.model.encode(text, normalize_embeddings=True).tolist()
        return {"embedding": vector, "model": _MODEL_NAME}
