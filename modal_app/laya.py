"""
Modal function: Laya (Convai Innovations, Apache 2.0) — a 421M ModernBERT decision model that answers
yes/no and multiple-choice questions about a text in one forward pass, with calibrated probabilities.
SEMBLANCE asks it a few questions about every message before replying (pipeline/turn_router.py): does it
need the attached repo, the web, past conversations, or is it something to remember?

CPU only (no GPU bill): one forward pass is a few hundred ms on 2 cores, and the container stays warm
for SCALEDOWN seconds after the last message.

Deploy (same secret as the video app — no new key):
    modal deploy modal_app/laya.py

The URL Modal prints is https://<workspace>--semblance-laya-api.modal.run; the Lambda's LAYA_URL
defaults to exactly that.
"""
import os

import modal
from fastapi import Request

app = modal.App("semblance-laya")
MODEL = os.environ.get("SEMBLANCE_LAYA_MODEL", "english")
SCALEDOWN = int(os.environ.get("SEMBLANCE_LAYA_SCALEDOWN", "600"))


def _download():
    from laya import Router
    Router(preload=True)


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch>=2.4", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install("laya>=0.3.24", "fastapi>=0.115.0")
    .run_function(_download)
)


@app.cls(image=image, cpu=2.0, memory=4096, scaledown_window=SCALEDOWN, max_containers=1,
         secrets=[modal.Secret.from_name("semblance-video-secret")])
@modal.concurrent(max_inputs=8)
class Laya:
    @modal.enter()
    def load(self):
        from laya import Router
        self.router = Router()
        self.router.predict("warm up", {"ok": {"type": "noul", "instructions": "Is this a test?"}}, model=MODEL)

    @modal.fastapi_endpoint(method="POST", label="semblance-laya-api")
    def api(self, body: dict, request: Request):
        expected = os.environ.get("VIDEO_SECRET", "")
        if not expected or request.headers.get("authorization") != f"Bearer {expected}":
            return {"ok": False, "error": "unauthorized"}
        state, questions = (body.get("state") or "")[:4000], body.get("questions") or {}
        if not state or not isinstance(questions, dict) or not questions:
            return {"ok": False, "error": "state and questions required"}
        try:
            result = self.router.predict(state, questions, model=MODEL)
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}
        return {"ok": True, "answers": result.get("answers", {})}
