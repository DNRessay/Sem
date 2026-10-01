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

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "ripgrep")
    .pip_install("fastapi>=0.115.0", "ruff>=0.6.0", "pytest>=8.0")
)

volume = modal.Volume.from_name("semblance-repo-clones", create_if_missing=True)
REPOS_DIR = "/repos"

_MAX_READ_CHARS = 20_000  # this endpoint's own ceiling — callers apply their own tighter budget on top
_MAX_GREP_MATCHES = 50
_MAX_BASH_OUTPUT = 12_000
_MAX_BASH_TIMEOUT = 120
_MAX_LIST_ENTRIES = 300

# Model-written commands run here, so they get a bare environment: nothing
# from this container's own env (REPO_TOOL_SECRET above all) is visible.
_BASH_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def _slug(repo: str) -> str:
    return hashlib.sha256(repo.encode()).hexdigest()[:16]


def _repo_path(repo: str, namespace: str = "") -> str:
    # Code mode edits its clone, so it lives under its own namespace and
    # never dirties the read-only clone chat's "Add repo" uses.
    return os.path.join(REPOS_DIR, _slug(f"{namespace}:{repo}" if namespace else repo))


def _safe_join(repo_path: str, rel_path: str) -> str | None:
    full = os.path.realpath(os.path.join(repo_path, (rel_path or "").lstrip("/")))
    root = os.path.realpath(repo_path)
    if full != root and not full.startswith(root + os.sep):
        return None
    if os.path.relpath(full, root).split(os.sep)[0] == ".git":
        return None
    return full


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
        path = _repo_path(repo, body.get("namespace") or "")

        if action == "clone_or_pull":
            return self._clone_or_pull(path, provider, repo, body.get("ref") or "", body.get("token"))

        if not os.path.isdir(path):
            return {"ok": False, "error": "repo not cloned yet — call clone_or_pull first"}

        if action == "read_file":
            return self._read_file(path, body.get("path") or "")
        if action == "grep":
            return self._grep(path, body.get("term") or "")
        if action == "list_dir":
            return self._list_dir(path, body.get("path") or "")
        if action == "write_file":
            return self._commit_after(self._write_file(path, body.get("path") or "", body.get("content")))
        if action == "edit_file":
            return self._commit_after(self._edit_file(
                path, body.get("path") or "", body.get("old"), body.get("new"), bool(body.get("replace_all")),
            ))
        if action == "bash":
            return self._commit_after(self._bash(path, body.get("command") or "", body.get("timeout") or 60))
        if action == "changes":
            return self._changes(path)
        if action == "discard":
            return self._commit_after(self._discard(path))
        return {"ok": False, "error": f"unknown action '{action}'"}

    def _commit_after(self, result: dict) -> dict:
        volume.commit()
        return result

    def _clone_or_pull(self, path: str, provider: str, repo: str, ref: str, token: str | None) -> dict:
        # The token is passed on the command line only, never left in
        # .git/config — Code mode runs model-written shell commands in this
        # clone, and `git remote -v` must not print a live credential.
        url = _clone_url(provider, repo, token)
        if os.path.isdir(os.path.join(path, ".git")):
            args = ["git", "-C", path, "pull", "--ff-only", url]
            if ref:
                args.append(ref)
            result = subprocess.run(args, capture_output=True, text=True, timeout=60)
            did = "pulled"
        else:
            os.makedirs(path, exist_ok=True)
            args = ["git", "clone", "--depth", "1"]
            if ref:
                args += ["--branch", ref]
            args += [url, path]
            result = subprocess.run(args, capture_output=True, text=True, timeout=120)
            did = "cloned"
        if os.path.isdir(os.path.join(path, ".git")):
            subprocess.run(["git", "-C", path, "remote", "set-url", "origin", _clone_url(provider, repo, None)],
                           capture_output=True, timeout=10)
        volume.commit()
        ok = result.returncode == 0
        return {"ok": ok, "action": did, "repo": repo, "error": None if ok else result.stderr[-500:]}

    def _read_file(self, repo_path: str, rel_path: str) -> dict:
        file_path = _safe_join(repo_path, rel_path)
        if file_path is None:
            return {"ok": False, "error": "invalid path"}
        if not os.path.isfile(file_path):
            resolved = self._resolve_bare_filename(repo_path, rel_path)
            if resolved is None:
                return {"ok": False, "error": "file not found"}
            file_path, rel_path = resolved, os.path.relpath(resolved, repo_path)
        with open(file_path, errors="replace") as f:
            content = f.read(_MAX_READ_CHARS)
        return {"ok": True, "content": content, "path": rel_path}

    def _resolve_bare_filename(self, repo_path: str, name: str) -> str | None:
        """A user asking "what's in index" doesn't know or care that the
        real file is index.html — if the exact path isn't found and the
        given name has no directory component, look for exactly one file
        anywhere in the repo whose name matches with or without extension
        (case-insensitively, so "readme" finds README.md). Ambiguous (more
        than one match) or no match returns None rather than guessing."""
        if "/" in name:
            return None
        name_lower = name.lower()
        candidates = []
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d != ".git"]
            for f in files:
                stem = f.rsplit(".", 1)[0]
                if f.lower() == name_lower or stem.lower() == name_lower:
                    candidates.append(os.path.join(root, f))
        return candidates[0] if len(candidates) == 1 else None

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

    def _list_dir(self, repo_path: str, rel_path: str) -> dict:
        dir_path = _safe_join(repo_path, rel_path)
        if dir_path is None or not os.path.isdir(dir_path):
            return {"ok": False, "error": "not a directory"}
        entries = []
        for name in sorted(os.listdir(dir_path)):
            if name == ".git":
                continue
            full = os.path.join(dir_path, name)
            entries.append(name + "/" if os.path.isdir(full) else name)
        return {"ok": True, "path": rel_path or ".", "entries": entries[:_MAX_LIST_ENTRIES],
                "truncated": len(entries) > _MAX_LIST_ENTRIES}

    def _write_file(self, repo_path: str, rel_path: str, content) -> dict:
        file_path = _safe_join(repo_path, rel_path)
        if file_path is None or file_path == os.path.realpath(repo_path):
            return {"ok": False, "error": "invalid path"}
        if not isinstance(content, str):
            return {"ok": False, "error": "content must be a string"}
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)
        return {"ok": True, "path": rel_path, "bytes": len(content.encode())}

    def _edit_file(self, repo_path: str, rel_path: str, old, new, replace_all: bool) -> dict:
        file_path = _safe_join(repo_path, rel_path)
        if file_path is None or not os.path.isfile(file_path):
            return {"ok": False, "error": "file not found"}
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            return {"ok": False, "error": "old and new must be strings, old non-empty"}
        with open(file_path, errors="replace") as f:
            text = f.read()
        count = text.count(old)
        if count == 0:
            return {"ok": False, "error": "old text not found — read the file again and copy it exactly"}
        if count > 1 and not replace_all:
            return {"ok": False, "error": f"old text matches {count} places — include more context or set replace_all"}
        with open(file_path, "w") as f:
            f.write(text.replace(old, new) if replace_all else text.replace(old, new, 1))
        return {"ok": True, "path": rel_path, "replacements": count if replace_all else 1}

    def _bash(self, repo_path: str, command: str, timeout) -> dict:
        if not command.strip():
            return {"ok": False, "error": "command required"}
        try:
            timeout = max(1, min(int(timeout), _MAX_BASH_TIMEOUT))
        except (TypeError, ValueError):
            timeout = 60
        try:
            result = subprocess.run(
                ["bash", "-lc", command], cwd=repo_path, env=_BASH_ENV,
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            out = e.stdout if isinstance(e.stdout, str) else ""
            return {"ok": False, "exit_code": None, "output": out[-_MAX_BASH_OUTPUT:],
                    "error": f"timed out after {timeout}s"}
        output = result.stdout + (("\n" + result.stderr) if result.stderr else "")
        if len(output) > _MAX_BASH_OUTPUT:
            output = "…(truncated)\n" + output[-_MAX_BASH_OUTPUT:]
        return {"ok": result.returncode == 0, "exit_code": result.returncode, "output": output}

    def _changes(self, repo_path: str) -> dict:
        status = subprocess.run(
            ["git", "-C", repo_path, "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, timeout=30,
        )
        changed, deleted = {}, []
        for line in status.stdout.splitlines():
            code, rel = line[:2], line[3:]
            if " -> " in rel:
                rel = rel.split(" -> ", 1)[1]
            rel = rel.strip('"')
            if "D" in code:
                deleted.append(rel)
                continue
            full = _safe_join(repo_path, rel)
            if full and os.path.isfile(full):
                with open(full, errors="replace") as f:
                    changed[rel] = f.read()
        diff = subprocess.run(
            ["git", "-C", repo_path, "diff", "--stat"], capture_output=True, text=True, timeout=30,
        )
        return {"ok": True, "files": changed, "deleted": deleted, "stat": diff.stdout[-4000:]}

    def _discard(self, repo_path: str) -> dict:
        subprocess.run(["git", "-C", repo_path, "checkout", "--", "."], capture_output=True, timeout=30)
        subprocess.run(["git", "-C", repo_path, "clean", "-fd"], capture_output=True, timeout=30)
        return {"ok": True}
