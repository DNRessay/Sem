"""
Modal function: SEMBLANCE's own voice, on CPU (no GPU bill).

- Speaking: Kokoro-82M (hexgrad, Apache 2.0), an open TTS that sounds natural and runs several times faster than
  real time on a few CPU cores. It replaces Gemini TTS for voice mode (Gemini was slow and rate-limited; it stays
  as the fallback).
- Listening: Whistle (Cactus Compute, `pip install cactus-needle`), a 16.9 MB speech-to-text model that beats
  Whisper-base, for browsers that can't recognise speech themselves. 16 kHz mono WAV, up to 30 seconds.

Deploy (same secret as the video app — no new key):
    modal deploy modal_app/voice.py

The URL Modal prints is https://<workspace>--semblance-voice-api.modal.run; the Lambda derives it from
MODAL_VIDEO_URL (set VOICE_URL to override, or VOICE_URL=off to disable).
"""
import base64
import io
import os
import time
import wave

import modal
from fastapi import Request

app = modal.App("semblance-voice")
SCALEDOWN = int(os.environ.get("SEMBLANCE_VOICE_SCALEDOWN", "600"))
RATE = 24000  # Kokoro's sample rate
# Sem's voice names (Gemini's) → the closest Kokoro voice; Kokoro names work too.
VOICES = {"Kore": "af_heart", "Puck": "am_puck", "Charon": "am_onyx", "Aoede": "af_bella", "Fenrir": "am_fenrir",
          "Leda": "bf_emma"}


def _download():
    from kokoro import KPipeline

    for lang in ("a", "b"):
        pipe = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
        for voice in {v for v in VOICES.values() if v[0] == lang}:
            list(pipe("Hello.", voice=voice))
    try:
        import needle

        needle.Whistle()  # fetches Whistle's weights and engine into the image
    except Exception as e:
        print("Whistle preload skipped:", e)


image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("espeak-ng")
    .pip_install("torch>=2.4", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install("kokoro>=0.9.4", "soundfile", "numpy", "cactus-needle>=3.1", "fastapi>=0.115.0")
    .run_function(_download)
)


def _wav(samples, rate: int = RATE) -> bytes:
    import numpy as np

    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


@app.cls(image=image, cpu=4.0, memory=4096, scaledown_window=SCALEDOWN, max_containers=1,
         secrets=[modal.Secret.from_name("semblance-video-secret")])
@modal.concurrent(max_inputs=4)
class Voice:
    @modal.enter()
    def load(self):
        from kokoro import KPipeline

        self.pipes = {lang: KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M") for lang in ("a", "b")}
        list(self.pipes["a"]("Ready.", voice="af_heart"))  # warm up
        self.whistle_error = ""
        try:
            import needle

            self.whistle = needle.Whistle()
        except Exception as e:
            self.whistle, self.whistle_error = None, f"{type(e).__name__}: {e}"[:300]
            print("Whistle unavailable:", self.whistle_error)

    def speak(self, text: str, voice: str, speed: float) -> dict:
        import numpy as np

        voice = VOICES.get(voice, voice if voice in VOICES.values() or "_" in voice else "af_heart")
        pipe = self.pipes["b" if voice.startswith("b") else "a"]
        started = time.monotonic()
        parts = [np.asarray(audio) for _, _, audio in pipe(text[:5000], voice=voice, speed=speed) if audio is not None]
        if not parts:
            return {"ok": False, "error": "nothing to say"}
        samples = np.concatenate(parts)
        return {"ok": True, "mime": "audio/wav", "base64": base64.b64encode(_wav(samples)).decode(),
                "seconds": round(len(samples) / RATE, 2), "took": round(time.monotonic() - started, 2)}

    def transcribe(self, audio_b64: str, keywords: list[str]) -> dict:
        import needle

        if self.whistle is None and self.whistle_error:
            return {"ok": False, "error": f"Whistle unavailable: {self.whistle_error}"}
        path = f"/tmp/{time.time_ns()}.wav"
        with open(path, "wb") as f:
            f.write(base64.b64decode(audio_b64))
        started = time.monotonic()
        try:
            kw = {"keywords": keywords[:50]} if keywords else {}
            result = (self.whistle.transcribe(path, **kw) if hasattr(self.whistle, "transcribe")
                      else needle.transcribe(path, **kw))
        finally:
            os.remove(path)
        return {"ok": True, "text": (result.get("text") or "").strip(), "language": result.get("language", ""),
                "took": round(time.monotonic() - started, 3)}

    @modal.fastapi_endpoint(method="POST", label="semblance-voice-api")
    def api(self, body: dict, request: Request):
        expected = os.environ.get("VIDEO_SECRET", "")
        if not expected or request.headers.get("authorization") != f"Bearer {expected}":
            return {"ok": False, "error": "unauthorized"}
        action = body.get("action")
        try:
            if action == "warm":
                return {"ok": True, "whistle": not self.whistle_error}
            if action == "speak":
                text = (body.get("text") or "").strip()
                if not text:
                    return {"ok": False, "error": "text required"}
                return self.speak(text, body.get("voice") or "Kore", float(body.get("speed") or 1.0))
            if action == "transcribe":
                if not body.get("audio"):
                    return {"ok": False, "error": "audio required (16 kHz mono WAV, base64)"}
                return self.transcribe(body["audio"], [k for k in body.get("keywords") or [] if isinstance(k, str)])
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        return {"ok": False, "error": f"unknown action {action!r}"}
