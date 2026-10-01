import httpx

from config import settings
from tools.bash_tool import BashTool

# Code mode's clone lives under its own namespace on the Modal volume, so its
# edits never touch the read-only clone chat's "Add repo" reads from.
NAMESPACE = "code"


class CodeWorkspace:
    """Client for Code mode's editable clone on Modal (modal_app/repo_tool.py).
    Every bash command passes BashTool's 23 security checks here first, then
    runs inside the Modal container — never in this Lambda."""

    def __init__(self, provider: str, repo: str):
        self.provider = provider
        self.repo = repo
        self._gate = BashTool()

    async def _call(self, action: str, http_timeout: float = 90, **kwargs) -> dict:
        if not settings.MODAL_REPO_URL:
            return {"ok": False, "error": "MODAL_REPO_URL not set — deploy modal_app/repo_tool.py first"}
        body = {"action": action, "provider": self.provider, "repo": self.repo, "namespace": NAMESPACE, **kwargs}
        headers = {"Authorization": f"Bearer {settings.MODAL_REPO_SECRET}"}
        try:
            async with httpx.AsyncClient(timeout=http_timeout) as client:
                r = await client.post(settings.MODAL_REPO_URL, json=body, headers=headers)
                return r.json()
        except (httpx.HTTPError, ValueError) as e:
            return {"ok": False, "error": f"workspace unreachable: {e}"}

    async def open(self, token: str | None, ref: str = "") -> dict:
        return await self._call("clone_or_pull", http_timeout=150, ref=ref, token=token)

    async def list_dir(self, path: str = "") -> dict:
        return await self._call("list_dir", path=path)

    async def read_file(self, path: str) -> dict:
        return await self._call("read_file", path=path)

    async def grep(self, term: str) -> dict:
        return await self._call("grep", term=term)

    async def write_file(self, path: str, content: str) -> dict:
        return await self._call("write_file", path=path, content=content)

    async def edit_file(self, path: str, old: str, new: str, replace_all: bool = False) -> dict:
        return await self._call("edit_file", path=path, old=old, new=new, replace_all=replace_all)

    async def bash(self, command: str, timeout: int = 60) -> dict:
        failures = self._gate._run_security_checks(command)
        if failures:
            return {"ok": False, "blocked": True, "error": f"Blocked by security gate: {', '.join(failures)}"}
        return await self._call("bash", http_timeout=min(timeout, 120) + 30, command=command, timeout=timeout)

    async def changes(self) -> dict:
        return await self._call("changes")

    async def discard(self) -> dict:
        return await self._call("discard")
