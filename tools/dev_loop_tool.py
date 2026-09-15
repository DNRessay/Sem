import os
import shutil
import uuid

from tools.bash_tool import BashTool
from tools.repo_write_tool import RepoWriteTool


class DevLoopTool:
    """
    Gates RepoWriteTool.propose_fix behind a real lint check — the "only
    commit once we think we fixed it" enforcement, as actual code, not a
    skill the model could choose to skip. Writes each changed .py file
    into a scratch directory under this Lambda's own /tmp (the same
    sandbox BashTool already runs against) and lints it with ruff — the
    same tool this project's own CI already runs, and its Rust-native
    startup fits the Lambda's 30s Globals.Function.Timeout far better
    than flake8's pure-Python one would. `python -m ruff` rather than a
    bare `ruff` command, since a packaged Lambda's subprocess PATH isn't
    guaranteed to include pip's console-script shims — importing it as a
    module sidesteps that.

    Only a clean lint run reaches propose_fix at all; a failure returns
    the raw ruff output instead, for the caller to fix and retry — no
    partial or failing commit ever happens. Non-.py files pass through
    unchecked (scoped honestly: this only knows how to lint Python
    today), and a full test-suite gate is a separate follow-up — that
    needs the whole repo materialized somewhere bash can reach, which
    today only exists on Modal's persistent clone (tools/repo_tool.py),
    not this Lambda's throwaway /tmp.
    """

    def __init__(self, bash: BashTool | None = None, repo_write: RepoWriteTool | None = None):
        self._bash = bash or BashTool()
        self._repo_write = repo_write or RepoWriteTool()

    async def check_and_propose_fix(
        self, provider: str, repo: str, token: str,
        level: str, slug: str, files: dict, commit_message: str,
        pr_title: str = "", pr_body: str = "", base_branch: str = "",
    ) -> dict:
        lint_result = await self._lint_files(files)
        if not lint_result["ok"]:
            return {"ok": False, "gate": "lint", "lint_output": lint_result["output"]}

        result = await self._repo_write.propose_fix(
            provider=provider, repo=repo, token=token, level=level, slug=slug,
            files=files, commit_message=commit_message, pr_title=pr_title,
            pr_body=pr_body, base_branch=base_branch,
        )
        return {**result, "gate": "lint", "lint_output": lint_result["output"]}

    async def _lint_files(self, files: dict) -> dict:
        py_files = {p: c for p, c in files.items() if p.endswith(".py")}
        if not py_files:
            return {"ok": True, "output": "(no .py files to lint)"}

        workdir = f"/tmp/lint-{uuid.uuid4().hex[:8]}"
        os.makedirs(workdir, exist_ok=True)
        try:
            for path, content in py_files.items():
                full_path = os.path.join(workdir, path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    f.write(content)

            result = await self._bash.execute(f"python -m ruff check {workdir}", timeout=15, cwd=workdir)
            if result.get("blocked"):
                return {"ok": False, "output": result.get("error", "lint command blocked by the security gate")}

            # A timeout or subprocess exception also comes back with
            # exit_code=-1 (see BashTool.execute) and no stdout/stderr —
            # falling back to "error" there surfaces what actually happened
            # instead of an empty lint output.
            exit_code = result.get("exit_code", 1)
            output = (result.get("stdout", "") + result.get("stderr", "")).strip() or result.get("error", "")
            return {"ok": exit_code == 0, "output": output}
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
