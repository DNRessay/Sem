import json
import time

import httpx

from config import settings
from pipeline import llm_providers
from tools.aws_read_tool import AwsReadTool
from tools.code_workspace import CodeWorkspace

_MAX_TOOL_RESULT_CHARS = 8000
_PREVIEW_CHARS = 1500

_SYSTEM = """You are Sem Code, SEMBLANCE's coding agent. You work inside a git clone of {repo} ({provider}).
Every path is relative to the repo root; bash runs with the repo root as its working directory.

How to work:
- Explore before changing anything: list_dir, grep, read_file.
- Prefer edit_file for changes to existing files (copy `old` exactly from what read_file returned). Use write_file for new files.
- Verify with bash: run the project's tests, linter or a quick script. Install dependencies with pip/npm if needed.
- Keep changes minimal and focused on the request. Don't reformat unrelated code.
- You cannot push or commit. When you're done, the user reviews your changes and opens a pull request with a button.
- Never print or write secrets, tokens or API keys.
- Finish with a short summary: what you changed, and how you verified it (or why you couldn't).
You are SEMBLANCE running on open-weight models; never claim to be Claude, GPT or any other vendor's model."""

_PLAN_SUFFIX = """

PLAN MODE: do not modify anything. Only explore (list_dir, read_file, grep, aws). Then reply with a numbered,
concrete implementation plan: which files change and how, and how you'll verify it. The user approves before you act."""


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


_S = {"type": "string"}
TOOLS = {
    "list_dir": _fn("list_dir", "List a directory in the repo ('' for the root).", {"path": _S}, []),
    "read_file": _fn("read_file", "Read a text file (up to 20,000 chars).", {"path": _S}, ["path"]),
    "grep": _fn("grep", "Case-insensitive search across tracked files; returns path:line matches.", {"pattern": _S}, ["pattern"]),
    "write_file": _fn("write_file", "Create or overwrite a file with the full content.", {"path": _S, "content": _S}, ["path", "content"]),
    "edit_file": _fn(
        "edit_file", "Replace an exact snippet in a file. `old` must match exactly once unless replace_all is true.",
        {"path": _S, "old": _S, "new": _S, "replace_all": {"type": "boolean"}}, ["path", "old", "new"],
    ),
    "bash": _fn(
        "bash", "Run a shell command in the repo root (tests, linters, installs, git status/diff). Max 120s.",
        {"command": _S, "timeout": {"type": "integer"}}, ["command"],
    ),
    "aws": _fn(
        "aws", "Read-only AWS call via boto3 (Describe*/List*/Get* only), e.g. service='lambda', operation='ListFunctions'.",
        {"service": _S, "operation": _S, "params": {"type": "object"}, "region": _S}, ["service", "operation"],
    ),
}
_READ_ONLY = ("list_dir", "read_file", "grep", "aws")


def _preview(result: dict) -> str:
    if not isinstance(result, dict):
        return str(result)[:_PREVIEW_CHARS]
    for key in ("error", "output", "content", "result"):
        if result.get(key):
            return str(result[key])[:_PREVIEW_CHARS]
    if "entries" in result:
        return "\n".join(result["entries"])[:_PREVIEW_CHARS]
    if "matches" in result:
        return "\n".join(f"{m['path']}:{m['line']}: {m['text']}" for m in result["matches"])[:_PREVIEW_CHARS]
    return json.dumps(result)[:_PREVIEW_CHARS]


class CodeAgent:
    """Tool-calling loop for the Code tab. Yields event dicts as it goes:
    {"type": "text"|"tool"|"result"|"error"|"done", ...}. `provider` is a
    model-picker id (pipeline/llm_providers.py); "auto" walks the free
    models — self-hosted Bonsai first, since it has no per-minute token cap."""

    def __init__(self, workspace: CodeWorkspace, mode: str = "act", max_steps: int = 30,
                 deadline_seconds: float = 780, aws: AwsReadTool | None = None, provider: str = "auto"):
        self.ws = workspace
        self.provider = provider
        self.mode = "plan" if mode == "plan" else "act"
        self.max_steps = max_steps
        self.deadline = time.monotonic() + deadline_seconds
        self.aws = aws or AwsReadTool()

    def _tools(self) -> list[dict]:
        names = _READ_ONLY if self.mode == "plan" else tuple(TOOLS)
        return [TOOLS[n] for n in names]

    def _messages(self, task: str, history: list[dict]) -> list[dict]:
        system = _SYSTEM.format(repo=self.ws.repo, provider=self.ws.provider)
        if self.mode == "plan":
            system += _PLAN_SUFFIX
        msgs = [{"role": "system", "content": system}]
        for h in history[-20:]:
            if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str) and h["content"]:
                msgs.append({"role": h["role"], "content": h["content"][:6000]})
        msgs.append({"role": "user", "content": task})
        return msgs

    async def _complete(self, client: httpx.AsyncClient, messages: list[dict]) -> dict:
        return await llm_providers.complete(
            self.provider, messages, self._tools(), max_tokens=settings.LOCAL_LLM_MAX_TOKENS,
            deadline=self.deadline, client=client,
        )

    async def _dispatch(self, name: str, args: dict) -> dict:
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
        if name == "aws":
            return await self.aws.call(args.get("service", ""), args.get("operation", ""),
                                       args.get("params") or {}, args.get("region", ""))
        return {"ok": False, "error": f"unknown tool {name}"}

    async def run(self, task: str, history: list[dict] | None = None):
        messages = self._messages(task, history or [])
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=180.0)) as client:
            for step in range(1, self.max_steps + 1):
                if time.monotonic() > self.deadline:
                    yield {"type": "error", "text": "Time limit reached — send 'continue' to keep going."}
                    return
                try:
                    msg = await self._complete(client, messages)
                except httpx.HTTPError as e:
                    msg = {"error": f"model unreachable: {e}"}
                if "error" in msg:
                    yield {"type": "error", "text": msg["error"]}
                    return

                content = msg.get("content") or ""
                calls = msg.get("tool_calls") or []
                if content.strip():
                    yield {"type": "text", "text": content}
                if not calls:
                    yield {"type": "done", "steps": step}
                    return

                messages.append({**msg, "role": "assistant", "content": content, "tool_calls": calls})
                for call in calls:
                    fn = call.get("function") or {}
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = None
                    yield {"type": "tool", "id": call.get("id"), "name": name, "args": args or {}}
                    result = (await self._dispatch(name, args) if isinstance(args, dict)
                              else {"ok": False, "error": "arguments were not valid JSON"})
                    ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
                    yield {"type": "result", "id": call.get("id"), "name": name, "ok": ok, "output": _preview(result)}
                    messages.append({
                        "role": "tool", "tool_call_id": call.get("id"),
                        "content": json.dumps(result, default=str)[:_MAX_TOOL_RESULT_CHARS],
                    })
        yield {"type": "error", "text": f"Stopped after {self.max_steps} steps — send 'continue' to keep going."}
