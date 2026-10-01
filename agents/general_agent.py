from agents.base_agent import BaseAgent
from agents.tool_loop import ToolLoopAgent, fn_tool
from storage.neon_store import get_store
from tools.web.fetch_tool import FetchTool
from tools.web.search import web_search

_S = {"type": "string"}


class _Delegate(ToolLoopAgent):
    """A small, bounded tool loop for one delegated subtask: it can search the
    web, read pages and search past conversations, on the free model chain."""

    def __init__(self, context: str = ""):
        super().__init__("auto", max_steps=6, deadline_seconds=150)
        self.allow_handoff = False
        self.context = context

    def system_prompt(self) -> str:
        base = ("You are one of SEMBLANCE's helper agents, handling a single subtask. Use the tools when they'd make the "
                "answer better (current facts, a page to read, something the user said before), then answer concisely "
                "and say where facts came from.")
        return f"{self.context}\n\n{base}" if self.context else base

    def tools(self) -> list[dict]:
        return [
            fn_tool("web_search", "Search the web.", {"query": _S}, ["query"]),
            fn_tool("fetch_url", "Read a web page as text.", {"url": _S}, ["url"]),
            fn_tool("search_memory", "Search past SEMBLANCE conversations for a word or phrase.", {"term": _S}, ["term"]),
        ]

    async def dispatch(self, name: str, args: dict) -> dict:
        if name == "web_search":
            return await web_search(args.get("query", ""))
        if name == "fetch_url":
            return await FetchTool().fetch(args.get("url", ""))
        if name == "search_memory":
            db = await get_store()
            return {"matches": await db.search_conversations(args.get("term", ""), limit=20)}
        return {"ok": False, "error": f"unknown tool {name}"}


class GeneralAgent(BaseAgent):
    """Handles a delegated task end-to-end — the worker behind swarm and
    coordinator subtasks. Runs a bounded tool loop (web, pages, memory) on the
    free model chain (Bonsai → Gemini → Groq), so one rate-limited provider
    doesn't fail the task."""

    async def run(self, task: dict) -> dict:
        query = task.get("query", "")
        self.log_audit(f"general:start:{query[:60]}")
        if not query:
            return {"error": "No query provided"}
        texts, steps, error = [], 0, None
        async for ev in _Delegate(task.get("context", "")).run(query):
            if ev["type"] == "text":
                texts.append(ev["text"])
            elif ev["type"] == "tool":
                steps += 1
            elif ev["type"] == "error":
                error = ev["text"]
        if error and not texts:
            return {"status": "error", "result": f"Something went wrong: {error}", "iterations": steps}
        return {"status": "complete", "result": texts[-1] if texts else "", "iterations": steps}
