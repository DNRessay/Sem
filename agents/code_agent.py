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
    "aws": fn_tool(
        "aws", "Read-only AWS call via boto3 (Describe*/List*/Get* only), e.g. service='lambda', operation='ListFunctions'.",
        {"service": _S, "operation": _S, "params": {"type": "object"}, "region": _S}, ["service", "operation"],
    ),
}
_READ_ONLY = ("list_dir", "read_file", "grep", "aws")


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
        self.pr_token = pr_token  # the connected GitHub/GitLab token; open_pr is only offered when set

    def tools(self) -> list[dict]:
        names = _READ_ONLY if self.mode == "plan" else tuple(n for n in TOOLS if n != "open_pr" or self.pr_token)
        return [TOOLS[n] for n in names]

    def system_prompt(self) -> str:
        pr_line = ("When the user asks for a PR or commit, call open_pr: it commits everything you changed to a new branch "
                   "and opens the PR, then share its link." if self.pr_token else
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
        if name == "open_pr":
            if not self.pr_token:
                return {"ok": False, "error": f"connect {self.ws.provider} in Connectors to open PRs"}
            from pipeline.code_tasks import open_pr
            return await open_pr(self.ws, self.pr_token, args.get("title", ""), args.get("body", ""))
        if name == "aws":
            return await self.aws.call(args.get("service", ""), args.get("operation", ""),
                                       args.get("params") or {}, args.get("region", ""))
        return {"ok": False, "error": f"unknown tool {name}"}
