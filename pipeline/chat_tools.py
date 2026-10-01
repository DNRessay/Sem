"""Real function-calling tools for the main chat, so the model acts on plain
requests ("ping google", "what's in the readme", "did I mention ams before")
instead of telling the user a trigger phrase."""
import json

from agents.tool_loop import HANDOFF_TOOL, fn_tool, handoff_result
from pipeline.bash_intent import run_bash_intent
from storage.neon_store import get_store
from tools.repo_tool import RepoTool
from tools.web.fetch_tool import FetchTool
from tools.web.search import web_search

_S = {"type": "string"}

BASE = [
    fn_tool("web_search", "Search the web for current information. Returns titles, URLs and snippets.",
            {"query": _S}, ["query"]),
    fn_tool("fetch_url", "Read a web page as text.", {"url": _S}, ["url"]),
    fn_tool("bash", "Run a shell command in a throwaway Linux sandbox (python3, curl; no ping, no git). "
            "It is not the user's own machine and can't see their files or repos.", {"command": _S}, ["command"]),
    fn_tool("search_memory", "Search every past SEMBLANCE conversation for a word or phrase (names, projects, "
            "anything the user told you before).", {"term": _S}, ["term"]),
    fn_tool("deep_research", "Research a question properly: several searches, reads the best pages, cross-checks "
            "and returns a cited answer. Takes a minute or two — use it when one web_search isn't enough.",
            {"question": _S}, ["question"]),
    HANDOFF_TOOL,
]
REPO = [
    fn_tool("repo_list", "List a folder in the repo attached to this chat ('' for the root).", {"path": _S}, []),
    fn_tool("repo_read", "Read a file from the repo attached to this chat.", {"path": _S}, ["path"]),
    fn_tool("repo_grep", "Search the repo attached to this chat for a term.", {"term": _S}, ["term"]),
]
KIND = {"web_search": "search", "deep_research": "search", "fetch_url": "fetch", "bash": "bash",
        "search_memory": "memory",
        "repo_list": "read", "repo_read": "read", "repo_grep": "read", "handoff": "handoff"}


async def available(session_id: str) -> tuple[list[dict], dict | None]:
    db = await get_store()
    active = await db.get_active_repo(session_id)
    return (BASE + REPO if active else BASE), active


def label(name: str, args: dict) -> str:
    target = args.get("question") or args.get("command") or args.get("query") or args.get("url") or args.get("term") or args.get("path") or ""
    return f"{name} {target}".strip()[:120]


async def run(name: str, args: dict, session_id: str, active: dict | None) -> dict:
    try:
        if name == "handoff":
            if args.get("tab") == "chat":
                return {"ok": False, "error": "you are already in the main chat — answer here"}
            return handoff_result(args)
        if name == "web_search":
            return await web_search(args.get("query", ""))
        if name == "deep_research":
            from agents.research_agent import deep_research
            return await deep_research(args.get("question", ""))
        if name == "fetch_url":
            return await FetchTool().fetch(args.get("url", ""))
        if name == "bash":
            return await run_bash_intent(args.get("command", ""), session_id)
        if name == "search_memory":
            db = await get_store()
            return {"matches": await db.search_conversations(args.get("term", ""), limit=20)}
        if name.startswith("repo_"):
            if not active:
                return {"ok": False, "error": "no repo is attached to this chat — attach one from + → GitHub/GitLab"}
            repo = RepoTool()
            if name == "repo_list":
                return await repo.list_dir(active["provider"], active["repo"], args.get("path", ""))
            if name == "repo_read":
                return await repo.read_file(active["provider"], active["repo"], args.get("path", ""))
            return await repo.grep(active["provider"], active["repo"], args.get("term", ""))
    except Exception as e:  # a failed tool is something the model can explain, not a broken reply
        return {"ok": False, "error": f"{name} failed: {str(e)[:300]}"}
    return {"ok": False, "error": f"unknown tool {name}"}


def as_message(call_id: str, result: dict) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, default=str)[:8000]}
