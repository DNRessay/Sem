import json
import time

import httpx

from config import settings
from pipeline import llm_providers

_MAX_TOOL_RESULT_CHARS = 8000
_PREVIEW_CHARS = 1500


def fn_tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


def preview(result) -> str:
    if not isinstance(result, dict):
        return str(result)[:_PREVIEW_CHARS]
    for key in ("error", "output", "content", "result", "summary"):
        if result.get(key):
            return str(result[key])[:_PREVIEW_CHARS]
    if "entries" in result:
        return "\n".join(result["entries"])[:_PREVIEW_CHARS]
    if "matches" in result:
        return "\n".join(
            f"{m['path']}:{m['line']}: {m['text']}" if "path" in m else json.dumps(m, default=str)
            for m in result["matches"]
        )[:_PREVIEW_CHARS]
    return json.dumps(result, default=str)[:_PREVIEW_CHARS]


HANDOFF_TABS = {
    "chat": "general questions, memory, reminders, quick lookups",
    "code": "changes to a code repo: build, fix, commit, open a PR",
    "cowork": "multi-step office work: research, email, calendar, Drive notes, images",
    "design": "the user's business marketing: website brief, ad copy, ad images and videos",
    "finance": "the user's money via C-Lab: net worth, portfolio, spending, markets",
}
HANDOFF_TOOL = fn_tool(
    "handoff", "Offer to continue in another SEMBLANCE tab when that tab fits the request better (or the user asks): "
    + "; ".join(f"{k} = {v}" for k, v in HANDOFF_TABS.items())
    + ". `task` is a complete, self-contained instruction for that tab including any details from this conversation. "
    "The user gets a button; don't do that tab's work yourself.",
    {"tab": {"type": "string", "enum": list(HANDOFF_TABS)}, "task": {"type": "string"}}, ["tab", "task"],
)


def handoff_result(args: dict) -> dict:
    tab, task = args.get("tab"), (args.get("task") or "").strip()
    if tab not in HANDOFF_TABS or not task:
        return {"ok": False, "error": f"tab must be one of {', '.join(HANDOFF_TABS)} and task must be set"}
    return {"ok": True, "status": f"offered the user a button to continue in {tab}"}


class ToolLoopAgent:
    """The shared agent loop behind the Code and Co-work tabs: ask the picked
    model, run the tools it calls, feed results back, repeat until it answers
    without a tool call. Yields event dicts for the UI:
    {"type": "text"|"tool"|"result"|"error"|"done", ...} plus whatever
    extra_events() adds (images, approval requests)."""

    def __init__(self, provider: str = "auto", max_steps: int = 30, deadline_seconds: float = 780,
                 mcp=None, allow_approvals: bool = False, user_context: str = ""):
        self.provider = provider
        self.max_steps = max_steps
        self.deadline = time.monotonic() + deadline_seconds
        # Tools from the user's MCP servers (pipeline/mcp_tools.MCPToolset).
        # Servers marked require_approval only appear where approvals can
        # be shown (Co-work), and their calls are queued, not run.
        self.mcp = mcp
        self.allow_approvals = allow_approvals
        self.user_context = user_context  # the owner's profile (TAUEngine.owner_context)
        self.tab = ""  # this agent's own tab; set allow_handoff False where no one sees the button
        self.allow_handoff = True

    def system_prompt(self) -> str:
        raise NotImplementedError

    def tools(self) -> list[dict]:
        raise NotImplementedError

    async def dispatch(self, name: str, args: dict) -> dict:
        raise NotImplementedError

    def extra_events(self, call_id: str, name: str, args: dict, result: dict) -> list[dict]:
        return []

    def model_view(self, result: dict) -> dict:
        """What the model gets back from a tool — drops bulky fields (an
        image's base64) that only the UI needs."""
        if result.get("images"):
            return {**result, "images": f"{len(result['images'])} image(s) shown to the user"}
        return result

    def _messages(self, task: str, history: list[dict]) -> list[dict]:
        system = self.system_prompt()
        if self.user_context:
            system += "\n\nWho you're working for (the owner of SEMBLANCE):\n" + self.user_context.replace(
                "You are SEMBLANCE. ", "")
        msgs = [{"role": "system", "content": system}]
        for h in history[-20:]:
            if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str) and h["content"]:
                msgs.append({"role": h["role"], "content": h["content"][:6000]})
        msgs.append({"role": "user", "content": task})
        return msgs

    def all_tools(self) -> list[dict]:
        extra = self.mcp.tools(include_approval=self.allow_approvals) if self.mcp else []
        return self.tools() + extra + ([HANDOFF_TOOL] if self.allow_handoff else [])

    async def _route(self, name: str, args: dict) -> dict:
        if name == "handoff" and self.allow_handoff:
            if args.get("tab") == self.tab:
                return {"ok": False, "error": "you are already in that tab — do the work here"}
            return handoff_result(args)
        if self.mcp and self.mcp.owns(name):
            if self.mcp.needs_approval(name):
                if not self.allow_approvals:
                    return {"ok": False, "error": "this MCP server requires approval, which isn't available here"}
                return {"ok": True, "status": "waiting for the user's approval", "summary": self.mcp.describe(name, args)}
            return await self.mcp.call(name, args)
        return await self.dispatch(name, args)

    def _mcp_events(self, call_id: str, name: str, args: dict, result: dict) -> list[dict]:
        if not (self.mcp and self.mcp.owns(name)):
            return []
        if self.mcp.needs_approval(name):
            return [{"type": "approval", "id": call_id, "name": name, "args": args, "summary": result.get("summary", "")}]
        return [{"type": "image", "id": f"{call_id}-{i}", "mime": img["mime"], "base64": img["base64"], "prompt": name}
                for i, img in enumerate(result.get("images") or [])]

    async def _complete(self, client: httpx.AsyncClient, messages: list[dict]) -> dict:
        return await llm_providers.complete(
            self.provider, messages, self.all_tools(), max_tokens=settings.LOCAL_LLM_MAX_TOKENS,
            deadline=self.deadline, client=client,
        )

    async def run(self, task: str, history: list[dict] | None = None):
        messages = self._messages(task, history or [])
        answered_by = ""
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
                    yield {"type": "error", "text": msg["error"], **({"suggest": msg["suggest"]} if msg.get("suggest") else {})}
                    return

                answered_by = msg.get("_provider") or answered_by
                content = msg.get("content") or ""
                calls = msg.get("tool_calls") or []
                if content.strip():
                    yield {"type": "text", "text": content}
                if not calls:
                    yield {"type": "done", "steps": step, "model": answered_by}
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
                    result = (await self._route(name, args) if isinstance(args, dict)
                              else {"ok": False, "error": "arguments were not valid JSON"})
                    if not isinstance(result, dict):
                        result = {"result": result}
                    ok = bool(result.get("ok", "error" not in result))
                    yield {"type": "result", "id": call.get("id"), "name": name, "ok": ok, "output": preview(self.model_view(result))}
                    if name == "handoff" and result.get("ok"):
                        yield {"type": "handoff", "tab": args["tab"], "task": args["task"].strip()}
                    for event in self._mcp_events(call.get("id"), name, args or {}, result) + \
                            self.extra_events(call.get("id"), name, args or {}, result):
                        yield event
                    messages.append({
                        "role": "tool", "tool_call_id": call.get("id"),
                        "content": json.dumps(self.model_view(result), default=str)[:_MAX_TOOL_RESULT_CHARS],
                    })
        yield {"type": "error", "text": f"Stopped after {self.max_steps} steps — send 'continue' to keep going."}
