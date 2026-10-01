"""
Modal function: short video ads with Wan 2.1 (open-source, Apache 2.0) on an
L4 GPU, behind a hard monthly spend cap.

Deploy:
    modal secret create semblance-video-secret VIDEO_SECRET=<any random string> VIDEO_MONTHLY_CAP_USD=10
    modal deploy modal_app/video.py      # first deploy downloads the ~15 GB model into the image

Set MODAL_VIDEO_URL to the printed URL and MODAL_VIDEO_SECRET to the same
random string in the Lambda environment.

Rendering takes minutes, so it's a job: POST {"action": "submit", ...} returns
a job_id right away; POST {"action": "status", "job_id": ...} until done.
Every finished render adds its GPU time (at GPU_USD_PER_HOUR) to this month's
total in a Modal Dict; once the total reaches VIDEO_MONTHLY_CAP_USD, new jobs
are refused until next month. One GPU at most (max_containers=1).
"""
import base64
import os
import time

import modal
from fastapi import Request

app = modal.App("semblance-video")

MODEL_ID = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
GPU = "L4"
GPU_USD_PER_HOUR = 0.80  # Modal's L4 rate, rounded up — keeps the cap conservative
SIZES = {"9:16": (480, 832), "16:9": (832, 480), "1:1": (624, 624)}
FPS = 16
_NEGATIVE = "blurry, low quality, distorted, deformed, watermark, text artifacts, static, worst quality"


def _download():
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL_ID)


gpu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install("torch>=2.4", "diffusers>=0.33", "transformers>=4.46", "accelerate", "ftfy",
                 "imageio[ffmpeg]", "huggingface_hub", "fastapi>=0.115.0")
    .run_function(_download)
)
api_image = modal.Image.debian_slim(python_version="3.12").pip_install("fastapi>=0.115.0")
spend = modal.Dict.from_name("semblance-video-spend", create_if_missing=True)


def _month() -> str:
    return time.strftime("%Y-%m", time.gmtime())


@app.cls(gpu=GPU, image=gpu_image, timeout=1500, scaledown_window=120, max_containers=1)
class Generator:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import AutoencoderKLWan, WanPipeline

        vae = AutoencoderKLWan.from_pretrained(MODEL_ID, subfolder="vae", torch_dtype=torch.float32)
        self.pipe = WanPipeline.from_pretrained(MODEL_ID, vae=vae, torch_dtype=torch.bfloat16).to("cuda")

    @modal.method()
    def generate(self, prompt: str, aspect_ratio: str = "9:16", seconds: int = 5) -> dict:
        from diffusers.utils import export_to_video

        started = time.monotonic()
        width, height = SIZES.get(aspect_ratio, SIZES["9:16"])
        frames = max(1, min(int(seconds), 5)) * FPS
        frames = frames - (frames - 1) % 4  # Wan wants 4k+1 frames
        try:
            video = self.pipe(prompt=prompt, negative_prompt=_NEGATIVE, height=height, width=width,
                              num_frames=frames, guidance_scale=5.0).frames[0]
            path = f"/tmp/{int(time.time() * 1000)}.mp4"
            export_to_video(video, path, fps=FPS)
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
        finally:
            gpu_seconds = time.monotonic() - started
            key = _month()
            spend[key] = spend.get(key, 0.0) + gpu_seconds / 3600 * GPU_USD_PER_HOUR
        return {"mime": "video/mp4", "base64": data, "gpu_seconds": round(gpu_seconds)}


@app.function(image=api_image, secrets=[modal.Secret.from_name("semblance-video-secret")])
@modal.fastapi_endpoint(method="POST")
def api(body: dict, request: Request):
    expected = os.environ.get("VIDEO_SECRET", "")
    if not expected or request.headers.get("authorization") != f"Bearer {expected}":
        return {"ok": False, "error": "unauthorized"}
    cap = float(os.environ.get("VIDEO_MONTHLY_CAP_USD", "10"))
    used = round(spend.get(_month(), 0.0), 2)

    action = body.get("action")
    if action == "budget":
        return {"ok": True, "used_usd": used, "cap_usd": cap}
    if action == "submit":
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt required"}
        if used >= cap:
            return {"ok": False, "error": f"Monthly video budget reached (${used:.2f} of ${cap:.2f}) — raise "
                                          "VIDEO_MONTHLY_CAP_USD in the Modal secret or wait for next month"}
        call = Generator().generate.spawn(prompt[:1500], body.get("aspect_ratio") or "9:16", body.get("seconds") or 5)
        return {"ok": True, "job_id": call.object_id, "used_usd": used, "cap_usd": cap}
    if action == "status":
        try:
            call = modal.FunctionCall.from_id(body.get("job_id") or "")
            result = call.get(timeout=0)
        except (TimeoutError, modal.exception.TimeoutError):
            return {"ok": True, "status": "rendering"}
        except Exception as e:
            return {"ok": False, "status": "failed", "error": str(e)[:300]}
        return {"ok": True, "status": "done", **result}
    return {"ok": False, "error": f"unknown action {action!r}"}
