import httpx

from config import settings


class RepoTool:
    """Client for the Modal-hosted persistent repo clone/read/grep service
    (modal_app/repo_tool.py). Unlike gateway/connectors.py's one-shot
    GitHub/GitLab fetch, this keeps a real clone on a Modal Volume between
    calls — "clone_or_pull" once, then cheap read_file/grep calls against
    the same clone for every follow-up question about it."""

    async def _call(self, action: str, **kwargs) -> dict:
        if not settings.MODAL_REPO_URL:
            return {"ok": False, "error": "MODAL_REPO_URL not set"}
        headers = {"Authorization": f"Bearer {settings.MODAL_REPO_SECRET}"}
        body = {"action": action, **kwargs}
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(settings.MODAL_REPO_URL, json=body, headers=headers)
            return r.json()

    async def clone_or_pull(self, provider: str, repo: str, ref: str = "", token: str | None = None) -> dict:
        return await self._call("clone_or_pull", provider=provider, repo=repo, ref=ref, token=token)

    async def read_file(self, provider: str, repo: str, path: str) -> dict:
        return await self._call("read_file", provider=provider, repo=repo, path=path)

    async def grep(self, provider: str, repo: str, term: str) -> dict:
        return await self._call("grep", provider=provider, repo=repo, term=term)
