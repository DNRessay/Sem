"""
Modal function: a persistent git clone, callable over HTTP for read/search
against it — the whole point being "clone once, ask questions many times"
instead of re-fetching repo content on every single chat message.

Deploy:
    pip install modal
    modal setup
    modal deploy modal_app/repo_tool.py

Modal prints a URL — set MODAL_REPO_URL to it in the Lambda environment.

Unlike modal_app/embeddings.py, this endpoint can clone private repos (given
a token) and read arbitrary files out of them, so it needs real auth, not
just an unguessable URL. Before deploying, create a Modal secret:

    modal secret create semblance-repo-secret REPO_TOOL_SECRET=<any random string>

and set that same random string as MODAL_REPO_SECRET in the Lambda
environment — every request must carry it as `Authorization: Bearer <value>`.

Clones live on a Modal Volume, so they survive between calls (and between
different users' sessions, keyed by repo — a second person attaching the
same public repo reuses the existing clone rather than re-cloning it).
Free tier: $30/month credit; a personal-use clone/read/grep workload costs
a few cents a month at most.
"""
import hashlib
import os
import subprocess

import modal
from fastapi import Request

app = modal.App("semblance-repo-tool")

image = modal.Image.debian_slim(python_version="3.12").apt_install("git").pip_install("fastapi>=0.115.0")

volume = modal.Volume.from_name("semblance-repo-clones", create_if_missing=True)
REPOS_DIR = "/repos"

_MAX_READ_CHARS = 20_000  # this endpoint's own ceiling — callers apply their own tighter budget on top
_MAX_GREP_MATCHES = 50


def _slug(repo: str) -> str:
    return hashlib.sha256(repo.encode()).hexdigest()[:16]


def _repo_path(repo: str) -> str:
    return os.path.join(REPOS_DIR, _slug(repo))


def _clone_url(provider: str, repo: str, token: str | None) -> str:
    host = "github.com" if provider == "github" else "gitlab.com"
    if token:
        cred = f"x-access-token:{token}" if provider == "github" else f"oauth2:{token}"
        return f"https://{cred}@{host}/{repo}.git"
    return f"https://{host}/{repo}.git"


@app.cls(
    image=image,
    volumes={REPOS_DIR: volume},
    secrets=[modal.Secret.from_name("semblance-repo-secret")],
    scaledown_window=300,
)
class RepoTool:
    @modal.fastapi_endpoint(method="POST")
    def handle(self, body: dict, request: Request):
        expected = os.environ.get("REPO_TOOL_SECRET", "")
        if not expected or request.headers.get("authorization") != f"Bearer {expected}":
            return {"ok": False, "error": "unauthorized"}

        action = body.get("action")
        provider = body.get("provider", "github")
        repo = (body.get("repo") or "").strip()
        if not repo:
            return {"ok": False, "error": "repo required"}
        path = _repo_path(repo)

        if action == "clone_or_pull":
            return self._clone_or_pull(path, provider, repo, body.get("ref") or "", body.get("token"))

        if not os.path.isdir(path):
            return {"ok": False, "error": "repo not cloned yet — call clone_or_pull first"}

        if action == "read_file":
            return self._read_file(path, body.get("path") or "")
        if action == "grep":
            return self._grep(path, body.get("term") or "")
        return {"ok": False, "error": f"unknown action '{action}'"}

    def _clone_or_pull(self, path: str, provider: str, repo: str, ref: str, token: str | None) -> dict:
        if os.path.isdir(os.path.join(path, ".git")):
            result = subprocess.run(
                ["git", "-C", path, "pull", "--ff-only"], capture_output=True, text=True, timeout=60,
            )
            did = "pulled"
        else:
            os.makedirs(path, exist_ok=True)
            args = ["git", "clone", "--depth", "1"]
            if ref:
                args += ["--branch", ref]
            args += [_clone_url(provider, repo, token), path]
            result = subprocess.run(args, capture_output=True, text=True, timeout=120)
            did = "cloned"
        volume.commit()
        ok = result.returncode == 0
        return {"ok": ok, "action": did, "repo": repo, "error": None if ok else result.stderr[-500:]}

    def _read_file(self, repo_path: str, rel_path: str) -> dict:
        file_path = os.path.realpath(os.path.join(repo_path, rel_path.lstrip("/")))
        if not file_path.startswith(os.path.realpath(repo_path) + os.sep):
            return {"ok": False, "error": "invalid path"}
        if not os.path.isfile(file_path):
            return {"ok": False, "error": "file not found"}
        with open(file_path, errors="replace") as f:
            content = f.read(_MAX_READ_CHARS)
        return {"ok": True, "content": content, "path": rel_path}

    def _grep(self, repo_path: str, term: str) -> dict:
        if not term:
            return {"ok": False, "error": "term required"}
        result = subprocess.run(
            ["git", "-C", repo_path, "grep", "-n", "-I", "-i", term],
            capture_output=True, text=True, timeout=30,
        )
        matches = []
        for line in result.stdout.splitlines()[:_MAX_GREP_MATCHES]:
            parts = line.split(":", 2)
            if len(parts) == 3:
                matches.append({"path": parts[0], "line": parts[1], "text": parts[2]})
        return {"ok": True, "matches": matches}
