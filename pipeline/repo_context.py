import re

from storage.neon_store import get_store
from tools.registry import get_registry

# Deliberately narrow, deterministic phrasing — same reasoning as
# pipeline/web_context.py's detect_web_intent: no LLM tool-calling involved,
# just regex triggers checked against the session's persistently cloned repo
# (set via "Add repo" — see gateway/connectors.py fetch_repo).
_README_RE = re.compile(r"\b(what'?s in the readme|read (?:the )?readme|show (?:me )?the readme)\b", re.I)
_READ_FILE_RE = re.compile(r"\bread (?:the )?file[:\s]+([^\s,;!?]+)", re.I)
_GREP_RE = re.compile(r"\b(?:search|grep)(?: the)? (?:repo|codebase)(?: for)?[:\s]+(.+)$", re.I)


def detect_repo_intent(query: str) -> tuple[str, str] | None:
    """Returns (kind, target) — kind is 'read' or 'grep' — or None. Checked
    in order of specificity: an explicit "read file X" or "search the repo
    for X" wins over the README shortcut, since those name what they want."""
    m = _READ_FILE_RE.search(query)
    if m:
        return ("read", m.group(1))
    m = _GREP_RE.search(query)
    if m:
        return ("grep", m.group(1).strip().rstrip("?.!"))
    if _README_RE.search(query):
        return ("read", "README.md")
    return None


def repo_status_label(kind: str, target: str) -> str:
    if kind == "read":
        return f"Reading {target}…"
    return f'Searching the repo for "{target}"…'


async def run_repo_intent(kind: str, target: str, session_id: str) -> str:
    """Executes against the session's active (persistently cloned) repo —
    empty string if there's no active repo, or on any tool failure, so a
    missing/unset Modal repo tool degrades to "no repo context added,"
    never a chat-breaking error."""
    db = await get_store()
    active = await db.get_active_repo(session_id)
    if not active:
        return ""

    registry = get_registry()

    if kind == "read":
        result = await registry.execute(
            "repo_read", {"provider": active["provider"], "repo": active["repo"], "path": target},
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return ""
        return f'<repo_file repo="{active["repo"]}" path="{target}">\n{result.get("content", "")}\n</repo_file>'

    result = await registry.execute(
        "repo_grep", {"provider": active["provider"], "repo": active["repo"], "term": target},
    )
    if not isinstance(result, dict) or not result.get("ok") or not result.get("matches"):
        return ""
    lines = [f'{m["path"]}:{m["line"]}: {m["text"]}' for m in result["matches"][:20]]
    return f'<repo_grep repo="{active["repo"]}" term="{target}">\n' + "\n".join(lines) + "\n</repo_grep>"
