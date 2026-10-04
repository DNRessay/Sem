"""
Modal function: short video ads with Wan 2.1 and, when Gemini's free image
quota runs out, ad images with FLUX.1-schnell (both open-source, Apache 2.0),
behind one hard monthly spend cap.

Deploy:
    modal secret create semblance-video-secret VIDEO_SECRET=<any random string> VIDEO_MONTHLY_CAP_USD=10
    HF_TOKEN=<token> modal deploy modal_app/video.py   # first deploy downloads the models into the image;
                                                        # accept FLUX.1-schnell's terms on Hugging Face first

Set MODAL_VIDEO_URL to the printed URL and MODAL_VIDEO_SECRET to the same
random string in the Lambda environment.

Images: POST {"action": "image", "prompt", "aspect_ratio"} returns a job_id the
same way (seconds once warm); poll it with "status".

Long videos: each 5-second scene is its own "submit"; "peek" says whether one is done without sending it back,
and {"action": "stitch", "job_ids": [...], "audio_url"} joins the finished scenes (plus a voiceover) on CPU.

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

# Deploy-time overrides, e.g. `SEMBLANCE_VIDEO_GPU=A10G SEMBLANCE_VIDEO_GPU_RATE=1.10 modal deploy modal_app/video.py`.
MODEL_ID = os.environ.get("SEMBLANCE_VIDEO_MODEL", "Wan-AI/Wan2.1-T2V-1.3B-Diffusers")
GPU = os.environ.get("SEMBLANCE_VIDEO_GPU", "L4")
# USD per GPU-hour used for the spend cap — Modal's L4 rate rounded up, so the cap stays conservative.
GPU_USD_PER_HOUR = float(os.environ.get("SEMBLANCE_VIDEO_GPU_RATE", "0.80"))
SIZES = {"9:16": (480, 832), "16:9": (832, 480), "1:1": (624, 624)}
FPS = 16
# Wan 2.1's own settings for the 1.3B model (its README: shift 8, guidance 6) and its official negative prompt, which
# the demos use; our old one-line negative and the default shift were a big part of the gap.
FLOW_SHIFT = float(os.environ.get("SEMBLANCE_VIDEO_SHIFT", "8.0"))
GUIDANCE = float(os.environ.get("SEMBLANCE_VIDEO_GUIDANCE", "6.0"))
STEPS = int(os.environ.get("SEMBLANCE_VIDEO_STEPS", "50"))
ENHANCE = os.environ.get("SEMBLANCE_VIDEO_ENHANCE", "1") == "1"
# Fast mode: CausVid, a step-distillation LoRA for Wan 2.1 1.3B (the same idea as PDMD/DMAD: a few denoising steps
# instead of 50, no classifier-free guidance). ~6 steps ≈ 1-2 min instead of ~10 per clip; motion can be a little
# weaker, so the app lets you switch it off per video. If the LoRA can't load, renders fall back to normal mode.
FAST_LORA_REPO = os.environ.get("SEMBLANCE_VIDEO_FAST_REPO", "Kijai/WanVideo_comfy")
FAST_LORA_FILE = os.environ.get("SEMBLANCE_VIDEO_FAST_FILE", "Wan21_CausVid_bidirect2_T2V_1_3B_lora_rank32.safetensors")
FAST_STEPS = int(os.environ.get("SEMBLANCE_VIDEO_FAST_STEPS", "6"))
_NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，"
             "残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，"
             "三条腿，背景人很多，倒着走, text, subtitles, letters, words, watermark, logo, blurry, low quality, deformed, "
             "overexposed, static frame, jpeg artifacts")
# A scene that asks for words in quotes ("VICINIC" on the screen) mustn't be told to avoid text at the same time.
_NEGATIVE_WITH_TEXT = _NEGATIVE.replace("字幕，", "").replace(" text, subtitles, letters, words, watermark, logo,", " watermark, misspelled text,")


def negative_for(prompt: str) -> str:
    import re

    return _NEGATIVE_WITH_TEXT if re.search(r'["“][^"”]{2,40}["”]', prompt or "") else _NEGATIVE


IMAGE_MODEL_ID = os.environ.get("SEMBLANCE_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
# FLUX needs ~33 GB in bf16, so a 48 GB L40S keeps it all on the GPU (a few seconds per image).
IMAGE_GPU = os.environ.get("SEMBLANCE_IMAGE_GPU", "L40S")
IMAGE_GPU_USD_PER_HOUR = float(os.environ.get("SEMBLANCE_IMAGE_GPU_RATE", "2.00"))
IMAGE_SIZES = {"1:1": (1024, 1024), "16:9": (1344, 768), "9:16": (768, 1344), "4:3": (1152, 864),
               "3:4": (864, 1152), "4:5": (896, 1120), "5:4": (1120, 896), "3:2": (1216, 816),
               "2:3": (816, 1216), "21:9": (1536, 656)}


def _download():
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL_ID)
    snapshot_download(IMAGE_MODEL_ID, ignore_patterns=["flux1-schnell.safetensors", "*.md"])


MUSIC_MODEL_ID = os.environ.get("SEMBLANCE_MUSIC_MODEL", "stabilityai/stable-audio-open-1.0")
MUSIC_MAX_SECONDS = 47  # the model's longest clip; longer videos loop it


def _download_music():
    # Gated on Hugging Face (accept its licence once, free under $1M revenue). If that's not done the deploy still
    # works; videos just come out without music.
    from huggingface_hub import snapshot_download
    try:
        snapshot_download(MUSIC_MODEL_ID, ignore_patterns=["*.ckpt", "*.md"])
    except Exception as e:
        print("Background music unavailable:", e)


gpu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .env({"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})
    .pip_install("torch>=2.4", "diffusers>=0.33", "transformers>=4.46", "accelerate", "ftfy", "sentencepiece",
                 "protobuf", "imageio[ffmpeg]", "huggingface_hub", "fastapi>=0.115.0")
    # FLUX.1-schnell is gated on Hugging Face (accept its terms once): the HF_TOKEN in the deploying
    # shell (e.g. Colab secrets) is passed to the build so the download can log in.
    .run_function(_download, secrets=[modal.Secret.from_dict({"HF_TOKEN": os.environ.get("HF_TOKEN", "")})])
    # Added last so the model downloads above stay cached: LoRA loading (fast mode) needs peft and a newer diffusers.
    .pip_install("peft>=0.15", "diffusers>=0.35")
    .pip_install("soundfile", "torchsde")
    .run_function(_download_music, secrets=[modal.Secret.from_dict({"HF_TOKEN": os.environ.get("HF_TOKEN", "")})])
)
api_image = modal.Image.debian_slim(python_version="3.12").pip_install("fastapi>=0.115.0")
# Every container imports this whole file, so each image needs fastapi (the import at the top), or the
# function dies before it starts: joins never ran at all without it.
stitch_image = modal.Image.debian_slim(python_version="3.12").apt_install("ffmpeg").pip_install("httpx", "fastapi>=0.115.0")
spend = modal.Dict.from_name("semblance-video-spend", create_if_missing=True)
# job_id -> {"started"} at submit, {"done", "ok"} when it ends. "Is it done?" reads this instead of asking Modal
# for the result with timeout=0, which never succeeded once finished videos got big (720p): fetching a large
# result takes longer than zero seconds, so every check said "rendering" forever.
jobs = modal.Dict.from_name("semblance-video-jobs", create_if_missing=True)
# Every finished scene is also written here as <job_id>.mp4, so the join reads files instead of fetching each
# scene's (big) result back from Modal, which is where joins hung.
clips = modal.Volume.from_name("semblance-video-clips", create_if_missing=True)
CLIPS = "/clips"


def _finished(ok: bool, callback: str = ""):
    """Notes the job as done in the jobs Dict and, when the app passed a callback URL, tells it right away, so
    the next step (joining the scenes, saving the video) happens even with nobody's app open."""
    job_id = ""
    try:
        job_id = modal.current_function_call_id()
        jobs[job_id] = {**(jobs.get(job_id) or {}), "done": time.time(), "ok": ok}
    except Exception:
        pass
    if callback and job_id:
        import json
        import urllib.request

        req = urllib.request.Request(callback, data=json.dumps({"job_id": job_id, "ok": ok}).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {os.environ.get('VIDEO_SECRET', '')}"})
        # AWS caps the app at a few Lambdas at once, so a burst of callbacks gets 429s: back off and try again
        # (the app's 15-minute check catches any that still don't get through).
        for wait in (3, 10, 30, 0):
            try:
                urllib.request.urlopen(req, timeout=20).read()
                return
            except Exception as e:
                print("callback failed:", e)
                if not wait or (getattr(e, "code", 500) < 500 and getattr(e, "code", 0) != 429):
                    return
                time.sleep(wait)


def _stage(stage: str, error: str = ""):
    """Where a join is ("fetching scene 2 of 3", "uploading"), readable with "peek" while it runs."""
    try:
        job_id = modal.current_function_call_id()
        jobs[job_id] = {**(jobs.get(job_id) or {}), "stage": stage, **({"error": error} if error else {})}
    except Exception:
        pass


def _upload(path: str, url: str, mime: str = "video/mp4") -> bool:
    """PUTs the finished video to the app's storage (a presigned S3 URL), so it never travels back through the
    API as one huge response — those timed out, and finished long videos never reached the app."""
    import urllib.request

    with open(path, "rb") as f:
        req = urllib.request.Request(url, data=f.read(), method="PUT", headers={"Content-Type": mime})
    try:
        urllib.request.urlopen(req, timeout=120).read()
        return True
    except Exception as e:
        detail = getattr(e, "read", lambda: b"")()[:200]
        print("upload failed:", e, detail)
        return False


def _month() -> str:
    return time.strftime("%Y-%m", time.gmtime())


@app.cls(gpu=GPU, image=gpu_image, timeout=1500, scaledown_window=120, max_containers=1,
         secrets=[modal.Secret.from_name("semblance-video-secret")], volumes={CLIPS: clips})
class Generator:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import AutoencoderKLWan, UniPCMultistepScheduler, WanPipeline

        vae = AutoencoderKLWan.from_pretrained(MODEL_ID, subfolder="vae", torch_dtype=torch.float32)
        self.pipe = WanPipeline.from_pretrained(MODEL_ID, vae=vae, torch_dtype=torch.bfloat16)
        self.pipe.scheduler = UniPCMultistepScheduler.from_config(self.pipe.scheduler.config, flow_shift=FLOW_SHIFT)
        # The 11 GB umt5 text encoder, the transformer and the fp32 VAE together fill the L4's 22 GB, and the
        # VAE decode (the last step, after ~10 min of denoising) ran out of memory. Offloading keeps only the
        # part that is running on the GPU, and tiling decodes the video in pieces.
        self.fast_error = ""
        try:
            from huggingface_hub import hf_hub_download

            lora = hf_hub_download(FAST_LORA_REPO, FAST_LORA_FILE)
            self.pipe.load_lora_weights(lora, adapter_name="fast")
            self.pipe.set_adapters(["fast"], [0.0])  # loaded but off until a fast render asks for it
        except Exception as e:
            self.fast_error = f"{type(e).__name__}: {e}"[:300]
            print("Fast mode unavailable:", self.fast_error)
        self.pipe.enable_model_cpu_offload()
        if hasattr(self.pipe.vae, "enable_tiling"):
            self.pipe.vae.enable_tiling()

    @modal.method()
    def generate(self, prompt: str, aspect_ratio: str = "9:16", seconds: int = 5, fast: bool = False,
                 callback: str = "") -> dict:
        from diffusers.utils import export_to_video

        started = time.monotonic()
        width, height = SIZES.get(aspect_ratio, SIZES["9:16"])
        frames = max(1, min(int(seconds), 5)) * FPS + 1  # Wan wants 4k+1 frames: 81 is the full 5 seconds
        fast = bool(fast) and not self.fast_error
        ok = False
        try:
            if not self.fast_error:
                self.pipe.set_adapters(["fast"], [1.0 if fast else 0.0])
            video = self.pipe(prompt=prompt, negative_prompt=negative_for(prompt), height=height, width=width, num_frames=frames,
                              guidance_scale=1.0 if fast else GUIDANCE,
                              num_inference_steps=FAST_STEPS if fast else STEPS).frames[0]
            path = f"/tmp/{int(time.time() * 1000)}.mp4"
            export_to_video(video, path, fps=FPS)
            path = _enhance(path) if ENHANCE else path
            with open(path, "rb") as f:
                raw = f.read()
            data = base64.b64encode(raw).decode()
            try:
                with open(f"{CLIPS}/{modal.current_function_call_id()}.mp4", "wb") as f:
                    f.write(raw)
                clips.commit()
            except Exception as e:
                print("couldn't keep the clip for joining:", e)
            ok = True
        finally:
            gpu_seconds = time.monotonic() - started
            _charge(gpu_seconds, GPU_USD_PER_HOUR)
            _finished(ok, callback)
        return {"mime": "video/mp4", "base64": data, "gpu_seconds": round(gpu_seconds), "fast": fast,
                **({"fast_error": self.fast_error} if self.fast_error else {})}


@app.cls(gpu=GPU, image=gpu_image, timeout=600, scaledown_window=60, max_containers=1, volumes={CLIPS: clips},
         secrets=[modal.Secret.from_name("semblance-video-secret")])
class Music:
    """Background music (Stable Audio Open, ~1B params): a few seconds of GPU per track, written to the clips
    Volume as <job_id>.wav for the join to mix under the voice."""
    @modal.enter()
    def load(self):
        import torch
        from diffusers import StableAudioPipeline

        self.pipe = StableAudioPipeline.from_pretrained(MUSIC_MODEL_ID, torch_dtype=torch.float16).to("cuda")

    @modal.method()
    def generate(self, prompt: str, seconds: int = 15, callback: str = "", upload_url: str = "") -> dict:
        import soundfile as sf
        import torch

        started = time.monotonic()
        ok = False
        try:
            audio = self.pipe(prompt=prompt, negative_prompt="Low quality, vocals, singing, speech.", num_inference_steps=100,
                              audio_end_in_s=float(max(5, min(int(seconds), MUSIC_MAX_SECONDS))),
                              generator=torch.Generator("cuda").manual_seed(int(time.time()) % 100000)).audios[0]
            path = f"{CLIPS}/{modal.current_function_call_id()}.wav"
            sf.write(path, audio.T.float().cpu().numpy(), self.pipe.vae.sampling_rate)
            clips.commit()
            if upload_url and not _upload(path, upload_url, "audio/wav"):  # a track for the Music tab
                raise RuntimeError("couldn't upload the track to storage")
            ok = True
        finally:
            gpu_seconds = time.monotonic() - started
            _charge(gpu_seconds, GPU_USD_PER_HOUR)
            _finished(ok, callback)
        return {"ok": True, "gpu_seconds": round(gpu_seconds)}


def _enhance(path: str) -> str:
    """Wan renders 480p at 16 fps. ffmpeg smooths it to 24 fps (motion-compensated in-between frames), scales it
    1.5x to 720p with lanczos and sharpens a little: a few seconds of CPU, much less soft and choppy."""
    import subprocess

    out = path.replace(".mp4", "-hd.mp4")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-vf",
                        "minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:vsbmc=1,scale=iw*1.5:ih*1.5:flags=lanczos,"
                        "unsharp=5:5:0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18",
                        out], check=True, timeout=240)
        return out
    except Exception:
        return path  # the raw render is still a video


def _charge(seconds: float, rate: float):
    key = _month()
    spend[key] = spend.get(key, 0.0) + seconds / 3600 * rate


@app.cls(gpu=IMAGE_GPU, image=gpu_image, timeout=600, scaledown_window=60, max_containers=1)
class ImageGenerator:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import FluxPipeline

        started = time.monotonic()
        self.pipe = FluxPipeline.from_pretrained(IMAGE_MODEL_ID, torch_dtype=torch.bfloat16).to("cuda")
        _charge(time.monotonic() - started, IMAGE_GPU_USD_PER_HOUR)  # cold starts count toward the cap too

    @modal.method()
    def generate(self, prompt: str, aspect_ratio: str = "1:1") -> dict:
        import io

        started = time.monotonic()
        width, height = IMAGE_SIZES.get(aspect_ratio, IMAGE_SIZES["1:1"])
        try:
            image = self.pipe(prompt, width=width, height=height, num_inference_steps=4, guidance_scale=0.0,
                              max_sequence_length=256).images[0]
            buf = io.BytesIO()
            image.save(buf, format="PNG")
        except Exception:
            _finished(False)
            raise
        finally:
            _charge(time.monotonic() - started, IMAGE_GPU_USD_PER_HOUR)
        _finished(True)
        return {"mime": "image/png", "base64": base64.b64encode(buf.getvalue()).decode()}


@app.function(image=stitch_image, cpu=2.0, memory=4096, timeout=600, volumes={CLIPS: clips},
              secrets=[modal.Secret.from_name("semblance-video-secret")])
def stitch(job_ids: list[str], audio_url: str = "", upload_url: str = "", callback: str = "", music_job: str = "") -> dict:
    """Long videos: the finished 5-second scenes joined in order, with the voiceover and background music (if any)
    mixed over them. CPU only, so it doesn't count toward the GPU cap."""
    try:
        result = _stitch(job_ids, audio_url, upload_url, music_job)
    except Exception as e:
        _stage("failed", f"{type(e).__name__}: {e}"[:300])
        _finished(False, callback)
        raise
    _finished(True, callback)
    return result


def _stitch(job_ids: list[str], audio_url: str, upload_url: str = "", music_job: str = "") -> dict:
    import subprocess
    import tempfile

    import httpx

    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        clips.reload()
        for i, job_id in enumerate(job_ids):
            kept = f"{CLIPS}/{job_id}.mp4"
            if os.path.exists(kept):
                parts.append(kept)
                continue
            _stage(f"fetching scene {i + 1} of {len(job_ids)}")  # rendered before clips were kept
            result = modal.FunctionCall.from_id(job_id).get(timeout=120)
            path = f"{tmp}/scene{i:02d}.mp4"
            with open(path, "wb") as f:
                f.write(base64.b64decode(result["base64"]))
            parts.append(path)
        _stage("joining")
        with open(f"{tmp}/list.txt", "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        joined = f"{tmp}/joined.mp4"
        # Re-encoding (rather than -c copy) keeps the joins clean whatever each clip's timestamps look like.
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{tmp}/list.txt",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20", joined], check=True)
        voice, voice_error = "", ""
        if audio_url:
            _stage("adding the voiceover")
            try:
                audio = httpx.get(audio_url, follow_redirects=True, timeout=60)
                audio.raise_for_status()
                voice = f"{tmp}/voice.wav"
                with open(voice, "wb") as f:
                    f.write(audio.content)
            except Exception as e:
                voice, voice_error = "", f"couldn't fetch the voiceover: {type(e).__name__}: {e}"[:200]
                print(voice_error)
        music = f"{CLIPS}/{music_job}.wav" if music_job else ""
        music = music if music and os.path.exists(music) else ""
        out = joined
        if voice or music:
            out = f"{tmp}/final.mp4"
            try:
                subprocess.run(mix_command(joined, voice, music, _duration(joined), out), check=True,
                               capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                voice_error = f"couldn't mix the audio: {(e.stderr or '')[-200:]}"
                print(voice_error)
                out = joined  # a silent video beats no video
        extra = {"voice": bool(voice) and out != joined, "music": bool(music) and out != joined,
                 **({"voice_error": voice_error} if voice_error else {})}
        if upload_url:
            _stage("uploading")
            for _ in range(3):
                if _upload(out, upload_url):
                    return {"mime": "video/mp4", "uploaded": True, **extra}
            _stage("upload failed", "couldn't upload the joined video to storage")
        with open(out, "rb") as f:
            return {"mime": "video/mp4", "base64": base64.b64encode(f.read()).decode(), **extra}


def _duration(path: str) -> float:
    import subprocess

    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def mix_command(video: str, voice: str, music: str, seconds: float, out: str) -> list[str]:
    """ffmpeg: the video as is, the voice at full volume, the music looped quietly under it (louder with no voice),
    fading out over the last 1.5 s. Everything is cut to the video's length."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video]
    graph, mixed = [], []
    if voice:
        cmd += ["-i", voice]
        graph.append("[1:a]aresample=44100,aformat=channel_layouts=stereo,apad[v]")
        mixed.append("[v]")
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        n = 2 if voice else 1
        fade = f",afade=t=out:st={max(seconds - 1.5, 0):.2f}:d=1.5" if seconds else ""
        graph.append(f"[{n}:a]aresample=44100,aformat=channel_layouts=stereo,volume={0.18 if voice else 0.6}{fade}[m]")
        mixed.append("[m]")
    if len(mixed) == 2:
        graph.append("[v][m]amix=inputs=2:duration=longest:normalize=0[a]")
        label = "[a]"
    else:
        label = mixed[0]
    cmd += ["-filter_complex", ";".join(graph), "-map", "0:v", "-map", label, "-c:v", "copy", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-t", f"{seconds:.3f}"] if seconds else ["-shortest"]
    return cmd + [out]


def _state(job_id: str) -> dict:
    """{"status": rendering | done | failed}. Jobs submitted since the jobs Dict existed are answered from it;
    older ones fall back to asking Modal, with time to fetch a large finished result."""
    entry = jobs.get(job_id)
    if entry is not None:
        extra = {k: entry[k] for k in ("stage",) if k in entry}
        if "done" not in entry:
            return {"status": "rendering", **extra}
        if entry.get("ok"):
            return {"status": "done", **extra}
        return {"status": "failed", "error": entry.get("error") or "the render failed on Modal", **extra}
    try:
        modal.FunctionCall.from_id(job_id).get(timeout=20)
    except (TimeoutError, modal.exception.TimeoutError):
        return {"status": "rendering"}
    except Exception as e:
        return {"status": "failed", "error": str(e)[:300]}
    return {"status": "done"}


def _spawned(call) -> str:
    try:
        if call.object_id not in jobs:  # a job that already finished keeps its "done"
            jobs[call.object_id] = {"started": time.time()}
    except Exception:
        pass
    return call.object_id


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
        call = Generator().generate.spawn(prompt[:1500], body.get("aspect_ratio") or "9:16", body.get("seconds") or 5,
                                          bool(body.get("fast")), body.get("callback") or "")
        return {"ok": True, "job_id": _spawned(call), "used_usd": used, "cap_usd": cap}
    if action == "image":
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt required"}
        if used >= cap:
            return {"ok": False, "error": f"Monthly Modal budget reached (${used:.2f} of ${cap:.2f})"}
        call = ImageGenerator().generate.spawn(prompt[:1500], body.get("aspect_ratio") or "1:1")
        return {"ok": True, "job_id": _spawned(call)}
    if action == "music":
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt required"}
        if used >= cap:
            return {"ok": False, "error": f"Monthly Modal budget reached (${used:.2f} of ${cap:.2f})"}
        call = Music().generate.spawn(prompt[:500], int(body.get("seconds") or 15), body.get("callback") or "",
                                      body.get("upload_url") or "")
        return {"ok": True, "job_id": _spawned(call)}
    if action == "peek":
        # Done or not, without the video itself (long videos check every scene often).
        state = _state(body.get("job_id") or "")
        return {"ok": state["status"] != "failed", **state}
    if action == "stitch":
        ids = [i for i in body.get("job_ids") or [] if isinstance(i, str)]
        if not ids:
            return {"ok": False, "error": "job_ids required"}
        call = stitch.spawn(ids[:12], body.get("audio_url") or "", body.get("upload_url") or "", body.get("callback") or "",
                            body.get("music_job") or "")
        return {"ok": True, "job_id": _spawned(call)}
    if action == "status":
        job_id = body.get("job_id") or ""
        state = _state(job_id)
        if state["status"] != "done":
            return {"ok": state["status"] != "failed", **state}
        try:
            result = modal.FunctionCall.from_id(job_id).get(timeout=120)  # done: time to fetch a big video
        except Exception as e:
            return {"ok": False, "status": "failed", "error": str(e)[:300]}
        return {"ok": True, "status": "done", **result}
    return {"ok": False, "error": f"unknown action {action!r}"}
