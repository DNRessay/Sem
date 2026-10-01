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


class ToolLoopAgent:
    """The shared agent loop behind the Code and Co-work tabs: ask the picked
    model, run the tools it calls, feed results back, repeat until it answers
    without a tool call. Yields event dicts for the UI:
    {"type": "text"|"tool"|"result"|"error"|"done", ...} plus whatever
    extra_events() adds (images, approval requests)."""

    def __init__(self, provider: str = "auto", max_steps: int = 30, deadline_seconds: float = 780):
        self.provider = provider
        self.max_steps = max_steps
        self.deadline = time.monotonic() + deadline_seconds

    def system_prompt(self) -> str:
        raise NotImplementedError

    def tools(self) -> list[dict]:
        raise NotImplementedError

    async def dispatch(self, name: str, args: dict) -> dict:
        raise NotImplementedError

    def extra_events(self, call_id: str, name: str, args: dict, result: dict) -> list[dict]:
        return []

    def model_view(self, result: dict) -> dict:
        """What the model gets back from a tool — override to drop bulky
        fields (an image's base64) that only the UI needs."""
        return result

    def _messages(self, task: str, history: list[dict]) -> list[dict]:
        msgs = [{"role": "system", "content": self.system_prompt()}]
        for h in history[-20:]:
            if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str) and h["content"]:
                msgs.append({"role": h["role"], "content": h["content"][:6000]})
        msgs.append({"role": "user", "content": task})
        return msgs

    async def _complete(self, client: httpx.AsyncClient, messages: list[dict]) -> dict:
        return await llm_providers.complete(
            self.provider, messages, self.tools(), max_tokens=settings.LOCAL_LLM_MAX_TOKENS,
            deadline=self.deadline, client=client,
        )

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
                    result = (await self.dispatch(name, args) if isinstance(args, dict)
                              else {"ok": False, "error": "arguments were not valid JSON"})
                    if not isinstance(result, dict):
                        result = {"result": result}
                    ok = bool(result.get("ok", "error" not in result))
                    yield {"type": "result", "id": call.get("id"), "name": name, "ok": ok, "output": preview(self.model_view(result))}
                    for event in self.extra_events(call.get("id"), name, args or {}, result):
                        yield event
                    messages.append({
                        "role": "tool", "tool_call_id": call.get("id"),
                        "content": json.dumps(self.model_view(result), default=str)[:_MAX_TOOL_RESULT_CHARS],
                    })
        yield {"type": "error", "text": f"Stopped after {self.max_steps} steps — send 'continue' to keep going."}
