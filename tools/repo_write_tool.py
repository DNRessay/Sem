import base64
import re

import httpx

_GITHUB_API = "https://api.github.com"
_GITLAB_API = "https://gitlab.com/api/v4"

_BUMP_LEVELS = ("patch", "minor")


def bump_version(current: str, level: str) -> str:
    """Three-part MAJOR.MINOR.PATCH only — no deeper (1.2.3, never
    1.2.3.1). 'major' is deliberately not a valid level here: a wrong
    "this is a breaking whole-codebase change" call is high blast-radius
    and low value to automate, so a major bump is a human decision made
    by editing the repo's VERSION file directly, never something this
    loop chooses on its own."""
    if level not in _BUMP_LEVELS:
        raise ValueError(f"Unknown bump level: {level!r} (must be 'patch' or 'minor')")
    try:
        major, minor, patch = (int(p) for p in current.strip().split("."))
    except (ValueError, AttributeError):
        major, minor, patch = 0, 0, 0  # no valid VERSION file yet — start from 0.0.0
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:50] or "change"


def branch_name(level: str, new_version: str, slug: str) -> str:
    prefix = "feat" if level == "minor" else "fix"
    return f"{prefix}/v{new_version}-{slugify(slug)}"


class RepoWriteTool:
    """
    Write-capable GitHub/GitLab operations: create_branch, commit_file,
    create_pull_request, plus the SemVer VERSION-file bump/branch-naming
    helpers above. Every commit lands on a fresh branch off the repo's
    default branch — never the default branch itself — and the only way
    back is a PR, so a human always reviews before anything merges.
    Mirrors gateway/connectors.py's GitHub/GitLab calling conventions;
    unlike that module this doesn't look up stored tokens itself, callers
    pass one in (same shape as tools/repo_tool.py's clone_or_pull).
    """

    async def get_default_branch(self, provider: str, repo: str, token: str) -> str:
        if provider == "github":
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(f"{_GITHUB_API}/repos/{repo}", headers=_github_headers(token))
                r.raise_for_status()
                return r.json()["default_branch"]
        else:
            project_enc = repo.replace("/", "%2F")
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(f"{_GITLAB_API}/projects/{project_enc}", headers=_gitlab_headers(token))
                r.raise_for_status()
                return r.json()["default_branch"]

    async def create_branch(self, provider: str, repo: str, new_branch: str, base_branch: str, token: str) -> dict:
        try:
            if provider == "github":
                async with httpx.AsyncClient(timeout=20) as client:
                    ref = await client.get(
                        f"{_GITHUB_API}/repos/{repo}/git/ref/heads/{base_branch}", headers=_github_headers(token),
                    )
                    ref.raise_for_status()
                    base_sha = ref.json()["object"]["sha"]
                    r = await client.post(
                        f"{_GITHUB_API}/repos/{repo}/git/refs",
                        json={"ref": f"refs/heads/{new_branch}", "sha": base_sha},
                        headers=_github_headers(token),
                    )
                    r.raise_for_status()
            else:
                project_enc = repo.replace("/", "%2F")
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post(
                        f"{_GITLAB_API}/projects/{project_enc}/repository/branches",
                        params={"branch": new_branch, "ref": base_branch},
                        headers=_gitlab_headers(token),
                    )
                    r.raise_for_status()
            return {"ok": True, "branch": new_branch}
        except httpx.HTTPStatusError as e:
            return {"ok": False, "error": f"{provider} error creating branch: {e.response.status_code} {e.response.text[:300]}"}

    async def get_file(self, provider: str, repo: str, path: str, ref: str, token: str) -> dict | None:
        """Returns {"content": str, "sha": str | None} or None if the file
        doesn't exist yet on that ref (a brand-new file, e.g. a repo's
        first-ever VERSION file)."""
        try:
            if provider == "github":
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.get(
                        f"{_GITHUB_API}/repos/{repo}/contents/{path}",
                        params={"ref": ref}, headers=_github_headers(token),
                    )
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                data = r.json()
                return {"content": base64.b64decode(data["content"]).decode("utf-8", errors="replace"), "sha": data["sha"]}
            else:
                project_enc = repo.replace("/", "%2F")
                path_enc = path.replace("/", "%2F")
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.get(
                        f"{_GITLAB_API}/projects/{project_enc}/repository/files/{path_enc}/raw",
                        params={"ref": ref}, headers=_gitlab_headers(token),
                    )
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return {"content": r.text, "sha": None}  # GitLab's Files API needs no sha for updates
        except httpx.HTTPStatusError:
            return None

    async def commit_file(self, provider: str, repo: str, branch: str, path: str, content: str, message: str, token: str) -> dict:
        try:
            existing = await self.get_file(provider, repo, path, branch, token)
            if provider == "github":
                body = {
                    "message": message,
                    "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                    "branch": branch,
                }
                if existing:
                    body["sha"] = existing["sha"]
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.put(
                        f"{_GITHUB_API}/repos/{repo}/contents/{path}", json=body, headers=_github_headers(token),
                    )
                    r.raise_for_status()
            else:
                project_enc = repo.replace("/", "%2F")
                path_enc = path.replace("/", "%2F")
                verb = "put" if existing else "post"
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await getattr(client, verb)(
                        f"{_GITLAB_API}/projects/{project_enc}/repository/files/{path_enc}",
                        json={"branch": branch, "content": content, "commit_message": message},
                        headers=_gitlab_headers(token),
                    )
                    r.raise_for_status()
            return {"ok": True, "path": path}
        except httpx.HTTPStatusError as e:
            return {"ok": False, "error": f"{provider} error committing {path}: {e.response.status_code} {e.response.text[:300]}"}

    async def create_pull_request(self, provider: str, repo: str, head_branch: str, base_branch: str, title: str, body: str, token: str) -> dict:
        try:
            if provider == "github":
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post(
                        f"{_GITHUB_API}/repos/{repo}/pulls",
                        json={"title": title, "head": head_branch, "base": base_branch, "body": body},
                        headers=_github_headers(token),
                    )
                    r.raise_for_status()
                    data = r.json()
                return {"ok": True, "url": data["html_url"], "number": data["number"]}
            else:
                project_enc = repo.replace("/", "%2F")
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post(
                        f"{_GITLAB_API}/projects/{project_enc}/merge_requests",
                        json={"source_branch": head_branch, "target_branch": base_branch, "title": title, "description": body},
                        headers=_gitlab_headers(token),
                    )
                    r.raise_for_status()
                    data = r.json()
                return {"ok": True, "url": data["web_url"], "number": data["iid"]}
        except httpx.HTTPStatusError as e:
            return {"ok": False, "error": f"{provider} error opening PR: {e.response.status_code} {e.response.text[:300]}"}

    async def propose_fix(
        self, provider: str, repo: str, token: str,
        level: str, slug: str, files: dict, commit_message: str,
        pr_title: str = "", pr_body: str = "", base_branch: str = "",
    ) -> dict:
        """The single entry point to call once a fix is validated (lint/
        tests passed via BashTool) and ready to land. Reads the current
        VERSION, bumps it, names the branch off the result, branches off
        the repo's default branch, commits every file in `files` plus the
        bumped VERSION file to that new branch, and opens a PR back to
        the default branch. Never touches the default branch directly —
        only a human merging the PR does that."""
        if level not in _BUMP_LEVELS:
            return {"ok": False, "error": f"Unknown bump level: {level!r} (must be 'patch' or 'minor')"}
        if not files:
            return {"ok": False, "error": "No files to commit"}

        base = base_branch or await self.get_default_branch(provider, repo, token)
        current = await self.get_file(provider, repo, "VERSION", base, token)
        current_version = current["content"].strip() if current else "0.0.0"
        new_version = bump_version(current_version, level)
        new_branch = branch_name(level, new_version, slug)

        branch_result = await self.create_branch(provider, repo, new_branch, base, token)
        if not branch_result.get("ok"):
            return branch_result

        for path, content in {**files, "VERSION": new_version}.items():
            commit_result = await self.commit_file(provider, repo, new_branch, path, content, commit_message, token)
            if not commit_result.get("ok"):
                return commit_result

        pr_result = await self.create_pull_request(
            provider, repo, new_branch, base,
            pr_title or f"{commit_message} (v{new_version})", pr_body, token,
        )
        return {**pr_result, "version": new_version, "branch": new_branch}


def _github_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _gitlab_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
