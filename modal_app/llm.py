"""
Modal function: Ternary Bonsai 2 27B (PrismML) as a self-hosted,
OpenAI-compatible chat endpoint. One endpoint, two callers:

  - SEMBLANCE's overflow brain — pipeline/query_engine.py streams from it
    when Groq's daily/hourly quota is hit (before the Cohere trial key).
  - Your coding CLI (MiniMax Code, or anything that speaks
    /v1/chat/completions) — no Groq 1000-token/minute output cap here.

Bonsai 2 27B is built on the same Qwen3.8-27B base as GROQ_MODEL, so prompts
carry over. Ternary weights (~6.7 GB) + vision projector. Needs PrismML's
llama.cpp fork (stock llama.cpp/vLLM lack the ternary kernels) — the prebuilt
CUDA binary is baked into the image, so nothing compiles on cold start.

Deploy:
    modal secret create semblance-llm-secret LLM_API_KEY=<any random string>
    modal deploy modal_app/llm.py

Modal prints a URL — set LOCAL_LLM_URL to it and LOCAL_LLM_API_KEY to the
same random string in the Lambda environment.

Cost guardrails (the $30/month Modal credit is shared with embeddings):
  - L4 GPU, roughly $0.80/hour while awake — ~35 awake hours/month on $30.
  - Scales to zero after SCALEDOWN_SECONDS idle. Each wake bills at least that.
  - max_containers=1: never more than one GPU running, whatever the traffic.
  - Also set a hard workspace spend limit in Modal's billing settings.

Coding with MiniMax Code:
    mcode provider add --name bonsai --base-url <LOCAL_LLM_URL>/v1 \\
      --api-format openai-completions --model bonsai-2-27b \\
      --api-key-env BONSAI_API_KEY --use
"""
import os
import subprocess
import time
import urllib.request

import modal

app = modal.App("semblance-llm")

_RELEASE = "prism-b10743-adfffbe"  # pinned in PrismML-Eng/Bonsai-demo scripts/download_binaries.sh
_BINARY_URL = (
    f"https://github.com/PrismML-Eng/llama.cpp/releases/download/{_RELEASE}/"
    f"llama-{_RELEASE}-bin-linux-cuda-12.4-x64.tar.gz"
)
_HF_REPO = "prism-ml/Ternary-Bonsai-2-27B-gguf"
_MODEL_DIR = "/models"
_PORT = 8000

MODEL_ALIAS = "bonsai-2-27b"
SCALEDOWN_SECONDS = 300
# Two 32K slots — the configuration a 24 GB RTX 3090 Ti community benchmark
# ran Bonsai 2 27B with, so Sem and a coding session don't queue on each other.
CTX_SIZE = 65536
PARALLEL = 2


def _download_weights():
    from huggingface_hub import snapshot_download

    snapshot_download(
        _HF_REPO,
        local_dir=_MODEL_DIR,
        allow_patterns=["*-PQ2_0.gguf", "*mmproj-Q8_0.gguf"],
    )


image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-runtime-ubuntu22.04", add_python="3.12")
    .apt_install("curl", "ca-certificates", "libgomp1")
    .run_commands(
        "mkdir -p /opt/llama",
        f"curl -fsSL {_BINARY_URL} -o /tmp/llama.tar.gz",
        "tar -xzf /tmp/llama.tar.gz -C /opt/llama --strip-components=1 || tar -xzf /tmp/llama.tar.gz -C /opt/llama",
        "ln -sf $(find /opt/llama -name llama-server -type f | head -1) /usr/local/bin/llama-server",
        "rm /tmp/llama.tar.gz",
    )
    .pip_install("huggingface_hub>=0.24")
    .run_function(_download_weights)
)


def _find(suffix: str) -> str:
    for name in sorted(os.listdir(_MODEL_DIR)):
        if name.endswith(suffix):
            return os.path.join(_MODEL_DIR, name)
    raise FileNotFoundError(f"no *{suffix} in {_MODEL_DIR}")


@app.function(
    image=image,
    gpu="L4",
    scaledown_window=SCALEDOWN_SECONDS,
    max_containers=1,
    timeout=3600,
    secrets=[modal.Secret.from_name("semblance-llm-secret")],
)
@modal.concurrent(max_inputs=PARALLEL * 4)
@modal.web_server(port=_PORT, startup_timeout=300)
def serve():
    lib_dir = os.path.dirname(os.path.realpath("/usr/local/bin/llama-server"))
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{lib_dir}:{env.get('LD_LIBRARY_PATH', '')}"
    cmd = [
        "llama-server",
        "-m", _find("-PQ2_0.gguf"),
        "--mmproj", _find("mmproj-Q8_0.gguf"),
        "--alias", MODEL_ALIAS,
        "--host", "0.0.0.0", "--port", str(_PORT),
        "--api-key", os.environ["LLM_API_KEY"],
        "-ngl", "99", "-fa", "on",
        "-c", str(CTX_SIZE), "-np", str(PARALLEL),
        "--jinja",
        # Model card sampling for thinking mode.
        "--temp", "1.0", "--top-p", "0.95", "--top-k", "20", "--min-p", "0.05",
        # PrismML's recommended way to shorten thinking without losing accuracy;
        # the hard budget stops a runaway think from burning GPU time.
        "--chat-template-kwargs", '{"reasoning_effort":"medium"}',
        "--reasoning-budget", "4096",
    ]
    proc = subprocess.Popen(cmd, env=env)
    # llama-server opens its port before the weights are on the GPU and
    # answers 503 "Loading model" until then. Modal only waits for the port,
    # so block here until /health is 200 — otherwise the request that woke
    # the container gets the 503 instead of a reply.
    while True:
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server exited with code {proc.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/health", timeout=2) as r:
                if r.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1)
