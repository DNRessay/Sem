from agents.tool_loop import ToolLoopAgent, fn_tool
from config import settings
from tools.aws_read_tool import AwsReadTool
from tools.code_workspace import CodeWorkspace

_SYSTEM = """You are Sem Code, SEMBLANCE's coding agent. You work inside a git clone of {repo} ({provider}).
Every path is relative to the repo root; bash runs with the repo root as its working directory.

How to work:
- Explore before changing anything: list_dir, grep, read_file.
- Prefer edit_file for changes to existing files (copy `old` exactly from what read_file returned). Use write_file for new files.
- Verify with bash: run the project's tests, linter or a quick script. Install dependencies with pip/npm if needed.
- Keep changes minimal and focused on the request. Don't reformat unrelated code.
- Never run git commit, checkout, branch, reset or push yourself. {pr_line}
- Never print or write secrets, tokens or API keys.
- Finish with a short summary: what you changed, and how you verified it (or why you couldn't).
You are SEMBLANCE running on open-weight models; never claim to be Claude, GPT or any other vendor's model."""

_PLAN_SUFFIX = """

PLAN MODE: do not modify anything. Only explore (list_dir, read_file, grep, aws). Then reply with a numbered,
concrete implementation plan: which files change and how, and how you'll verify it. The user approves before you act."""


# Code-tab actions that change things outside the workspace: queued for a
# one-tap approval in the UI, then run here by /code/execute.
APPROVAL_ACTIONS = {"merge_pr", "push_branch", "run_workflow", "rerun_ci", "set_secret"}


def describe_action(name: str, args: dict, repo: str) -> str:
    if name == "merge_pr":
        return f"Merge #{args.get('number')} in {repo} ({args.get('method') or 'merge'})"
    if name == "push_branch":
        return f"Push the workspace changes to {repo}@{args.get('branch') or 'the default branch'}"
    if name == "run_workflow":
        return f"Run {args.get('workflow') or 'the pipeline'} on {repo}@{args.get('ref')}"
    if name == "rerun_ci":
        return f"Re-run CI run {args.get('run_id')} in {repo}"
    if name == "set_secret":
        return f"Set secret {args.get('name')} in {repo} (value hidden)"
    return name


_S = {"type": "string"}
TOOLS = {
    "list_dir": fn_tool("list_dir", "List a directory in the repo ('' for the root).", {"path": _S}, []),
    "read_file": fn_tool("read_file", "Read a text file (up to 20,000 chars).", {"path": _S}, ["path"]),
    "grep": fn_tool("grep", "Case-insensitive search across tracked files; returns path:line matches.", {"pattern": _S}, ["pattern"]),
    "write_file": fn_tool("write_file", "Create or overwrite a file with the full content.", {"path": _S, "content": _S}, ["path", "content"]),
    "edit_file": fn_tool(
        "edit_file", "Replace an exact snippet in a file. `old` must match exactly once unless replace_all is true.",
        {"path": _S, "old": _S, "new": _S, "replace_all": {"type": "boolean"}}, ["path", "old", "new"],
    ),
    "bash": fn_tool(
        "bash", "Run a shell command in the repo root (tests, linters, installs, git status/diff). Max 120s.",
        {"command": _S, "timeout": {"type": "integer"}}, ["command"],
    ),
    "open_pr": fn_tool(
        "open_pr", "Commit every changed file to a new branch and open a pull/merge request. Use when the user "
        "asks for a PR or commit, after verifying your changes.", {"title": _S, "body": _S}, ["title"],
    ),
    # Repo hosting (GitHub / GitLab) — need the connected token.
    "list_prs": fn_tool("list_prs", "List pull/merge requests (state: open, closed or all).", {"state": _S}, []),
    "pr_status": fn_tool("pr_status", "One PR/MR: state, whether it can merge, and its checks/pipeline.",
                         {"number": {"type": "integer"}}, ["number"]),
    "list_workflows": fn_tool("list_workflows", "List the repo's CI workflows (GitHub Actions) or pipeline info (GitLab).", {}, []),
    "list_ci_runs": fn_tool("list_ci_runs", "Recent CI runs/pipelines with status.", {"limit": {"type": "integer"}}, []),
    "ci_logs": fn_tool("ci_logs", "Log tails of a CI run's failed jobs.", {"run_id": {"type": "integer"}}, ["run_id"]),
    "list_secrets": fn_tool("list_secrets", "Names of the repo's CI secrets/variables (never values).", {}, []),
    "merge_pr": fn_tool("merge_pr", "Merge a PR/MR (method: merge, squash or rebase). Waits for the user's approval.",
                        {"number": {"type": "integer"}, "method": _S}, ["number"]),
    "push_branch": fn_tool("push_branch", "Commit every changed file straight to a branch (created if missing; empty = "
                           "default branch) without a PR. Waits for the user's approval.",
                           {"branch": _S, "message": _S}, ["message"]),
    "run_workflow": fn_tool("run_workflow", "Start a GitHub workflow (file name like deploy.yml) or a GitLab pipeline on a "
                            "ref, with optional inputs. Waits for the user's approval.",
                            {"ref": _S, "workflow": _S, "inputs": {"type": "object"}}, ["ref"]),
    "rerun_ci": fn_tool("rerun_ci", "Re-run a CI run's failed jobs / retry a pipeline. Waits for the user's approval.",
                        {"run_id": {"type": "integer"}}, ["run_id"]),
    "set_secret": fn_tool("set_secret", "Create or update a CI secret/variable. Only with a value the user gave you. "
                          "Waits for the user's approval.", {"name": _S, "value": _S}, ["name", "value"]),
    "aws": fn_tool(
        "aws", "Read-only AWS call via boto3 (Describe*/List*/Get* only), e.g. service='lambda', operation='ListFunctions'.",
        {"service": _S, "operation": _S, "params": {"type": "object"}, "region": _S}, ["service", "operation"],
    ),
}
_READ_ONLY = ("list_dir", "read_file", "grep", "aws", "list_prs", "pr_status", "list_workflows", "list_ci_runs",
              "ci_logs", "list_secrets")
_HOST_TOOLS = {"open_pr", "list_prs", "pr_status", "list_workflows", "list_ci_runs", "ci_logs", "list_secrets",
               "merge_pr", "push_branch", "run_workflow", "rerun_ci", "set_secret"}


class CodeAgent(ToolLoopAgent):
    """The Code tab's agent: works in a clone of one repo on Modal. Plan mode
    only offers the read-only tools."""

    def __init__(self, workspace: CodeWorkspace, mode: str = "act", max_steps: int | None = None,
                 deadline_seconds: float | None = None, aws: AwsReadTool | None = None, provider: str = "auto",
                 mcp=None, pr_token: str | None = None):
        # MCP tools have unknown side effects, so plan mode never gets them.
        super().__init__(provider, max_steps or settings.CODE_MAX_STEPS,
                         deadline_seconds or settings.AGENT_TIMEOUT_SECONDS, mcp=None if mode == "plan" else mcp)
        self.tab = "code"
        self.ws = workspace
        self.mode = "plan" if mode == "plan" else "act"
        self.aws = aws or AwsReadTool()
        self.pending: dict[str, dict] = {}  # approval id -> real action, for /code/execute
        self.pr_token = pr_token  # the connected GitHub/GitLab token; open_pr is only offered when set

    def tools(self) -> list[dict]:
        names = _READ_ONLY if self.mode == "plan" else tuple(TOOLS)
        return [TOOLS[n] for n in names if n not in _HOST_TOOLS or self.pr_token]

    def system_prompt(self) -> str:
        pr_line = ("When the user asks for a PR or commit, call open_pr: it commits everything you changed to a new branch "
                   "and opens the PR, then share its link. You can also check PRs/MRs, CI runs and logs and secret names; "
                   "merging, pushing, running workflows and setting secrets go to the user as a one-tap approval — say "
                   "it's waiting for them." if self.pr_token else
                   f"Opening a PR needs {self.ws.provider} connected in Connectors; until then the user can review "
                   "your changes with the Changes button.")
        system = _SYSTEM.format(repo=self.ws.repo, provider=self.ws.provider, pr_line=pr_line)
        return system + _PLAN_SUFFIX if self.mode == "plan" else system

    async def dispatch(self, name: str, args: dict) -> dict:
        if self.mode == "plan" and name not in _READ_ONLY:
            return {"ok": False, "error": "plan mode is read-only"}
        if name == "list_dir":
            return await self.ws.list_dir(args.get("path", ""))
        if name == "read_file":
            return await self.ws.read_file(args.get("path", ""))
        if name == "grep":
            return await self.ws.grep(args.get("pattern", ""))
        if name == "write_file":
            return await self.ws.write_file(args.get("path", ""), args.get("content", ""))
        if name == "edit_file":
            return await self.ws.edit_file(args.get("path", ""), args.get("old", ""), args.get("new", ""),
                                           bool(args.get("replace_all")))
        if name == "bash":
            return await self.ws.bash(args.get("command", ""), int(args.get("timeout") or 60))
        if name in APPROVAL_ACTIONS:
            if not self.pr_token:
                return {"ok": False, "error": f"connect {self.ws.provider} in Connectors first"}
            return {"ok": True, "status": "waiting for the user's approval",
                    "summary": describe_action(name, args, self.ws.repo)}
        if name in _HOST_TOOLS and name != "open_pr":
            return await self._host_read(name, args)
        if name == "open_pr":
            if not self.pr_token:
                return {"ok": False, "error": f"connect {self.ws.provider} in Connectors to open PRs"}
            from pipeline.code_tasks import open_pr
            return await open_pr(self.ws, self.pr_token, args.get("title", ""), args.get("body", ""))
        if name == "aws":
            return await self.aws.call(args.get("service", ""), args.get("operation", ""),
                                       args.get("params") or {}, args.get("region", ""))
        return {"ok": False, "error": f"unknown tool {name}"}

    async def _host_read(self, name: str, args: dict) -> dict:
        if not self.pr_token:
            return {"ok": False, "error": f"connect {self.ws.provider} in Connectors first"}
        from tools.git_host import GitHost, GitHostError
        host = GitHost(self.ws.provider, self.ws.repo, self.pr_token)
        try:
            if name == "list_prs":
                return {"ok": True, "prs": await host.list_prs(args.get("state") or "open")}
            if name == "pr_status":
                return {"ok": True, **await host.pr_status(int(args.get("number")))}
            if name == "list_workflows":
                return {"ok": True, "workflows": await host.list_workflows()}
            if name == "list_ci_runs":
                return {"ok": True, "runs": await host.list_runs(args.get("limit") or 10)}
            if name == "ci_logs":
                return {"ok": True, **await host.run_logs(int(args.get("run_id")))}
            if name == "list_secrets":
                return {"ok": True, "names": await host.list_secrets()}
        except (GitHostError, ValueError, TypeError) as e:
            return {"ok": False, "error": str(e)[:400]}
        return {"ok": False, "error": f"unknown tool {name}"}

    def extra_events(self, call_id: str, name: str, args: dict, result: dict) -> list[dict]:
        if name in APPROVAL_ACTIONS and result.get("status") == "waiting for the user's approval":
            self.pending[call_id] = {"name": name, "args": args}  # the real args stay server-side
            shown = {**args, "value": "••••••"} if name == "set_secret" else args
            return [{"type": "approval", "id": call_id, "name": name, "args": shown, "summary": result["summary"]}]
        return []
