"""GitHub / GitLab repo management for Sem Code: pull/merge requests, CI runs
and logs, and repo secrets (CI variables on GitLab). One class, same method
names for both hosts. Reads are plain; the code agent routes merges, pushes,
workflow runs and secret changes through a one-tap approval first."""
import base64
from urllib.parse import quote

import httpx

_GITHUB = "https://api.github.com"
_GITLAB = "https://gitlab.com/api/v4"
_LOG_TAIL = 6000


class GitHostError(Exception):
    pass


class GitHost:
    def __init__(self, provider: str, repo: str, token: str):
        self.provider, self.repo, self.token = provider, repo, token
        self.gh = provider == "github"
        self._project = quote(repo, safe="")

    async def _req(self, method: str, path: str, **kw):
        base = f"{_GITHUB}/repos/{self.repo}" if self.gh else f"{_GITLAB}/projects/{self._project}"
        headers = ({"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"} if self.gh
                   else {"Authorization": f"Bearer {self.token}"})
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.request(method, base + path, headers=headers, **kw)
        if r.status_code >= 400:
            raise GitHostError(f"{self.provider} {r.status_code}: {r.text[:300]}")
        return r

    async def _json(self, method: str, path: str, **kw):
        r = await self._req(method, path, **kw)
        return r.json() if r.content else {}

    # ── Pull / merge requests ──────────────────────────────────────────

    async def list_prs(self, state: str = "open") -> list[dict]:
        if self.gh:
            data = await self._json("GET", "/pulls", params={"state": state, "per_page": 30})
            return [{"number": p["number"], "title": p["title"], "branch": p["head"]["ref"], "base": p["base"]["ref"],
                     "author": p["user"]["login"], "draft": p.get("draft"), "url": p["html_url"]} for p in data]
        gl_state = {"open": "opened", "closed": "closed", "all": "all"}.get(state, "opened")
        data = await self._json("GET", "/merge_requests", params={"state": gl_state, "per_page": 30})
        return [{"number": m["iid"], "title": m["title"], "branch": m["source_branch"], "base": m["target_branch"],
                 "author": m["author"]["username"], "draft": m.get("draft"), "url": m["web_url"]} for m in data]

    async def pr_status(self, number: int) -> dict:
        if self.gh:
            p = await self._json("GET", f"/pulls/{number}")
            checks = await self._json("GET", f"/commits/{p['head']['sha']}/check-runs", params={"per_page": 50})
            return {"number": number, "title": p["title"], "state": p["state"], "merged": p.get("merged"),
                    "mergeable": p.get("mergeable"), "mergeable_state": p.get("mergeable_state"), "url": p["html_url"],
                    "checks": [{"name": c["name"], "status": c["status"], "conclusion": c.get("conclusion")}
                               for c in checks.get("check_runs", [])]}
        m = await self._json("GET", f"/merge_requests/{number}")
        pipeline = m.get("head_pipeline") or {}
        return {"number": number, "title": m["title"], "state": m["state"], "merged": m["state"] == "merged",
                "mergeable": m.get("detailed_merge_status") == "mergeable",
                "mergeable_state": m.get("detailed_merge_status"), "url": m["web_url"],
                "checks": [{"name": "pipeline", "status": pipeline.get("status"), "url": pipeline.get("web_url")}]
                if pipeline else []}

    async def merge_pr(self, number: int, method: str = "merge") -> dict:
        method = method if method in ("merge", "squash", "rebase") else "merge"
        if self.gh:
            r = await self._json("PUT", f"/pulls/{number}/merge", json={"merge_method": method})
            return {"ok": bool(r.get("merged")), "sha": r.get("sha"), "message": r.get("message")}
        if method == "rebase":
            await self._req("PUT", f"/merge_requests/{number}/rebase")
            method = "merge"
        r = await self._json("PUT", f"/merge_requests/{number}/merge", json={"squash": method == "squash"})
        return {"ok": r.get("state") == "merged", "sha": r.get("merge_commit_sha"), "url": r.get("web_url")}

    # ── CI: GitHub Actions workflows / GitLab pipelines ────────────────

    async def list_workflows(self) -> list[dict]:
        if self.gh:
            data = await self._json("GET", "/actions/workflows", params={"per_page": 50})
            return [{"id": w["id"], "name": w["name"], "file": w["path"].rsplit("/", 1)[-1], "state": w["state"]}
                    for w in data.get("workflows", [])]
        return [{"name": ".gitlab-ci.yml", "note": "GitLab runs one pipeline per ref; trigger it with a ref"}]

    async def list_runs(self, limit: int = 10) -> list[dict]:
        limit = max(1, min(int(limit or 10), 30))
        if self.gh:
            data = await self._json("GET", "/actions/runs", params={"per_page": limit})
            return [{"id": r["id"], "workflow": r["name"], "branch": r["head_branch"], "event": r["event"],
                     "status": r["status"], "conclusion": r.get("conclusion"), "url": r["html_url"],
                     "created": r["created_at"]} for r in data.get("workflow_runs", [])]
        data = await self._json("GET", "/pipelines", params={"per_page": limit})
        return [{"id": p["id"], "branch": p["ref"], "event": p.get("source"), "status": p["status"],
                 "url": p["web_url"], "created": p["created_at"]} for p in data]

    async def run_logs(self, run_id: int) -> dict:
        """Log tails of the failed jobs (or all jobs if none failed)."""
        out = []
        if self.gh:
            jobs = (await self._json("GET", f"/actions/runs/{run_id}/jobs", params={"per_page": 50})).get("jobs", [])
            pick = [j for j in jobs if j.get("conclusion") == "failure"] or jobs
            for j in pick[:3]:
                text = (await self._req("GET", f"/actions/jobs/{j['id']}/logs")).text
                out.append({"job": j["name"], "conclusion": j.get("conclusion"), "log_tail": text[-_LOG_TAIL:]})
        else:
            jobs = await self._json("GET", f"/pipelines/{run_id}/jobs", params={"per_page": 50})
            pick = [j for j in jobs if j.get("status") == "failed"] or jobs
            for j in pick[:3]:
                text = (await self._req("GET", f"/jobs/{j['id']}/trace")).text
                out.append({"job": j["name"], "status": j.get("status"), "log_tail": text[-_LOG_TAIL:]})
        return {"run": run_id, "jobs": out}

    async def trigger(self, ref: str, workflow: str = "", inputs: dict | None = None) -> dict:
        if self.gh:
            if not workflow:
                raise GitHostError("workflow (file name like deploy.yml, or its id) is required on GitHub")
            await self._req("POST", f"/actions/workflows/{workflow}/dispatches",
                            json={"ref": ref, **({"inputs": inputs} if inputs else {})})
            return {"ok": True, "status": f"{workflow} started on {ref} — check list_runs in a few seconds"}
        variables = [{"key": k, "value": str(v)} for k, v in (inputs or {}).items()]
        p = await self._json("POST", "/pipeline", json={"ref": ref, **({"variables": variables} if variables else {})})
        return {"ok": True, "id": p.get("id"), "url": p.get("web_url")}

    async def rerun(self, run_id: int) -> dict:
        if self.gh:
            await self._req("POST", f"/actions/runs/{run_id}/rerun-failed-jobs")
            return {"ok": True, "status": f"re-running failed jobs of run {run_id}"}
        p = await self._json("POST", f"/pipelines/{run_id}/retry")
        return {"ok": True, "id": p.get("id"), "url": p.get("web_url")}

    # ── Secrets (Actions secrets / CI variables) — names out, values only in ──

    async def list_secrets(self) -> list[str]:
        if self.gh:
            data = await self._json("GET", "/actions/secrets", params={"per_page": 100})
            return [s["name"] for s in data.get("secrets", [])]
        data = await self._json("GET", "/variables", params={"per_page": 100})
        return [v["key"] for v in data]

    async def set_secret(self, name: str, value: str) -> dict:
        if not name or not value:
            raise GitHostError("name and value are required")
        if self.gh:
            from nacl import encoding, public
            key = await self._json("GET", "/actions/secrets/public-key")
            box = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder()))
            sealed = base64.b64encode(box.encrypt(value.encode())).decode()
            await self._req("PUT", f"/actions/secrets/{name}", json={"encrypted_value": sealed, "key_id": key["key_id"]})
            return {"ok": True, "status": f"secret {name} saved"}
        # GitLab can only mask values of 8+ chars without spaces; otherwise store unmasked.
        masked = len(value) >= 8 and " " not in value
        try:
            await self._req("PUT", f"/variables/{name}", json={"value": value, "masked": masked})
        except GitHostError:
            await self._req("POST", "/variables", json={"key": name, "value": value, "masked": masked})
        return {"ok": True, "status": f"CI variable {name} saved{' (masked)' if masked else ''}"}
