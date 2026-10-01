import re
import time

from agents.code_agent import CodeAgent
from config import settings
from gateway.connectors import _ensure_fresh_gitlab_token
from storage.neon_store import get_store
from tools.code_workspace import CodeWorkspace
from tools.repo_write_tool import RepoWriteTool, slugify

PROVIDERS = ("github", "gitlab")
_REPO_RE = re.compile(r"^[\w.-]+(/[\w.-]+)+$")
EVERY_SECONDS = {"hourly": 3600, "daily": 86400, "weekly": 7 * 86400}


def valid_target(provider: str, repo: str) -> bool:
    if provider not in PROVIDERS or not _REPO_RE.fullmatch(repo or ""):
        return False
    return all(part not in (".", "..") for part in repo.split("/"))


async def connector_token(account_id: str, provider: str) -> str | None:
    db = await get_store()
    connector = await db.get_connector(account_id, provider)
    if not connector:
        return None
    if provider == "gitlab":
        return await _ensure_fresh_gitlab_token(account_id, connector, db)
    return connector["token"]


async def open_pr(ws: CodeWorkspace, token: str, title: str, body: str = "", branch: str = "") -> dict:
    """Commits every changed file in the workspace to a branch and opens a
    PR/MR back to the default branch — the only way Code mode's work reaches
    the repo, so a human reviews it first. With `branch` (one per Code chat)
    later calls keep committing to that same branch and reuse its open PR."""
    changes = await ws.changes()
    if not changes.get("ok"):
        return changes
    files = changes.get("files") or {}
    if not files:
        return {"ok": False, "error": "No changes to open a PR with."}

    writer = RepoWriteTool()
    title = title.strip() or "Changes from Sem Code"
    base = await writer.get_default_branch(ws.provider, ws.repo, token)
    branch = branch.strip() or f"sem-code/{slugify(title)}-{int(time.time())}"
    if branch == base:
        return {"ok": False, "error": f"{branch} is the default branch — use push_branch to commit there"}
    created = await writer.create_branch(ws.provider, ws.repo, branch, base, token)
    if not created.get("ok") and "exist" not in created.get("error", "").lower():
        return created
    for path, content in files.items():
        committed = await writer.commit_file(ws.provider, ws.repo, branch, path, content, f"{title}: {path}", token)
        if not committed.get("ok"):
            return committed

    from tools.git_host import GitHost, GitHostError
    try:
        existing = next((p for p in await GitHost(ws.provider, ws.repo, token).list_prs("open") if p["branch"] == branch), None)
    except GitHostError:
        existing = None
    if existing:
        return {"ok": True, "url": existing["url"], "number": existing["number"], "branch": branch,
                "files": sorted(files), "updated": True}

    deleted = changes.get("deleted") or []
    if deleted:
        body += "\n\nNot included (file deletions aren't supported yet): " + ", ".join(deleted)
    pr = await writer.create_pull_request(ws.provider, ws.repo, branch, base, title, body.strip(), token)
    return {**pr, "branch": branch, "files": sorted(files)}


async def push_branch(ws: CodeWorkspace, token: str, branch: str, message: str) -> dict:
    """Commits every changed file in the workspace straight to `branch`
    (created off the default branch if it doesn't exist) — no PR."""
    changes = await ws.changes()
    if not changes.get("ok"):
        return changes
    files = changes.get("files") or {}
    if not files:
        return {"ok": False, "error": "No changes to push."}
    writer = RepoWriteTool()
    base = await writer.get_default_branch(ws.provider, ws.repo, token)
    branch = (branch or "").strip() or base
    if branch != base:
        created = await writer.create_branch(ws.provider, ws.repo, branch, base, token)
        if not created.get("ok") and "exist" not in created.get("error", "").lower():
            return created
    message = message.strip() or "Changes from Sem Code"
    for path, content in files.items():
        committed = await writer.commit_file(ws.provider, ws.repo, branch, path, content, f"{message}: {path}", token)
        if not committed.get("ok"):
            return committed
    return {"ok": True, "branch": branch, "files": sorted(files), "default_branch": branch == base}


async def run_code_action(ws: CodeWorkspace, token: str, name: str, args: dict) -> dict:
    from tools.git_host import GitHost, GitHostError
    host = GitHost(ws.provider, ws.repo, token)
    try:
        if name == "merge_pr":
            return await host.merge_pr(int(args.get("number")), args.get("method") or "merge")
        if name == "push_branch":
            return await push_branch(ws, token, args.get("branch", ""), args.get("message", ""))
        if name == "run_workflow":
            return await host.trigger(args.get("ref") or "main", args.get("workflow", ""), args.get("inputs") or None)
        if name == "rerun_ci":
            return await host.rerun(int(args.get("run_id")))
        if name == "set_secret":
            return await host.set_secret(args.get("name", ""), args.get("value", ""))
    except (GitHostError, ValueError, TypeError) as e:
        return {"ok": False, "error": str(e)[:400]}
    return {"ok": False, "error": f"{name} isn't an approvable action"}


async def run_due_automation() -> dict | None:
    """Runs at most one due automation per tick: fresh pull, agent run, PR if
    it changed anything (and the automation asks for one), then the
    workspace is reset so the next run starts clean."""
    db = await get_store()
    job = await db.claim_due_code_automation()
    if not job:
        return None

    token = await connector_token(job["account_id"], job["provider"])
    ws = CodeWorkspace(job["provider"], job["repo"])
    await ws.discard()
    opened = await ws.open(token)
    if not opened.get("ok"):
        result = f"Couldn't update the repo: {opened.get('error')}"
        await db.set_code_automation_result(job["id"], result)
        return {"id": job["id"], "result": result}

    texts, error = [], None
    agent = CodeAgent(ws, max_steps=settings.AUTOMATION_MAX_STEPS, deadline_seconds=settings.AUTOMATION_TIMEOUT_SECONDS)
    agent.allow_handoff = False  # nobody is watching a scheduled run
    async for event in agent.run(job["prompt"]):
        if event["type"] == "text":
            texts.append(event["text"])
        elif event["type"] == "error":
            error = event["text"]
    summary = (texts[-1] if texts else "") or error or "No summary."

    if job["open_pr"] and token:
        pr = await open_pr(ws, token, f"Automation: {job['prompt'][:60]}", f"Scheduled Sem Code run.\n\n{summary}")
        if pr.get("ok"):
            summary = f"PR opened: {pr['url']}\n\n{summary}"
        elif pr.get("error") != "No changes to open a PR with.":
            summary = f"PR failed: {pr.get('error')}\n\n{summary}"
    await ws.discard()

    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    await db.set_code_automation_result(job["id"], f"[{stamp}] {summary}")
    return {"id": job["id"], "result": summary}
