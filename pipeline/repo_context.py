import re

from storage.neon_store import get_store
from tools.registry import get_registry

# Deterministic phrasing — same reasoning as pipeline/web_context.py's
# detect_web_intent: no LLM tool-calling involved, just regex triggers
# checked against the session's persistently cloned repo (set via "Add
# repo" — see gateway/connectors.py fetch_repo). Several patterns rather
# than one big alternation, since each phrasing needs the target word in a
# different position — tried in order, first match wins.
_README_RE = re.compile(r"\b(what'?s in the readme|read (?:the )?readme|show (?:me )?the readme)\b", re.I)
_READ_FILE_PATTERNS = [
    re.compile(r"\bread (?:the )?(?:file[:\s]+)?([\w./-]+)", re.I),
    re.compile(r"\bshow (?:me )?(?:the )?(?:file[:\s]+)?([\w./-]+)", re.I),
    re.compile(r"\bwhat'?s in (?:the )?(?:file[:\s]+)?([\w./-]+)", re.I),
    re.compile(r"\bwhat does (?:the )?([\w./-]+) look like\b", re.I),
    re.compile(r"\bwhat (?:the )?([\w./-]+) looks?\s+like\b", re.I),
    re.compile(r"\bgive me (?:a )?copy of (?:the )?(?:content(?:s)? of )?(?:the )?([\w./-]+)", re.I),
    re.compile(r"\b(?:contents?|content) of (?:the )?([\w./-]+)", re.I),
]
_GREP_RE = re.compile(r"\b(?:search|grep)(?: the)? (?:repo|codebase)(?: for)?[:\s]+(.+)$", re.I)

# The broadened read-file patterns above capture whatever word follows their
# trigger phrase — for a generic "what's in here"/"what does this look
# like", that word is a pronoun, not a filename. Reject those rather than
# firing a bogus repo_read with target="here".
_GENERIC_TARGET_STOPWORDS = {
    "here", "there", "this", "that", "it", "them", "everything", "anything",
    "the", "file", "repo", "repository", "code", "codebase", "project",
}


def detect_repo_intent(query: str) -> tuple[str, str] | None:
    """Returns (kind, target) — kind is 'read' or 'grep' — or None. Checked
    in order of specificity: the README shortcut first (it would otherwise
    also match the generic read-file patterns below, just capturing the
    literal word "readme" instead of the exact "README.md"), then an
    explicit "search the repo for X", then the broader read-file phrasings."""
    if _README_RE.search(query):
        return ("read", "README.md")
    m = _GREP_RE.search(query)
    if m:
        return ("grep", m.group(1).strip().rstrip("?.!"))
    for pattern in _READ_FILE_PATTERNS:
        m = pattern.search(query)
        if m:
            target = m.group(1).rstrip("?.,!")
            if target.lower() in _GENERIC_TARGET_STOPWORDS:
                continue
            return ("read", target)
    return None


def repo_status_label(kind: str, target: str) -> str:
    if kind == "read":
        return f"Reading {target}…"
    return f'Searching the repo for "{target}"…'


async def run_repo_intent(target: str, session_id: str) -> str:
    """Grep-only: executes against the session's active (persistently
    cloned) repo and returns a context block to fold into the model's
    message for it to reason about. Empty string if there's no active repo,
    or on any tool failure, so a missing/unset Modal repo tool degrades to
    "no repo context added," never a chat-breaking error. A file read is
    handled separately by fetch_repo_file_raw (see gateway/router.py) —
    reproducing a file's exact content is not something to route through
    the model at all, let alone reason about first."""
    db = await get_store()
    active = await db.get_active_repo(session_id)
    if not active:
        return ""

    registry = get_registry()
    result = await registry.execute(
        "repo_grep", {"provider": active["provider"], "repo": active["repo"], "term": target},
    )
    if not isinstance(result, dict) or not result.get("ok") or not result.get("matches"):
        return ""
    lines = [f'{m["path"]}:{m["line"]}: {m["text"]}' for m in result["matches"][:20]]
    return f'<repo_grep repo="{active["repo"]}" term="{target}">\n' + "\n".join(lines) + "\n</repo_grep>"


async def fetch_repo_file_raw(target: str, session_id: str) -> tuple[str, str] | None:
    """Fetches one file's exact content from the session's active repo for
    the router to stream straight back to the client, bypassing the LLM
    entirely. A max_tokens-limited model re-typing content it already has
    verbatim doesn't just waste its (rate-limited) output budget — for
    anything more than a couple thousand characters it reliably truncates
    partway through, and there's no reasoning involved in reproducing exact
    bytes anyway. Returns (path, content), or None if there's no active
    repo or the read failed for any reason."""
    db = await get_store()
    active = await db.get_active_repo(session_id)
    if not active:
        return None

    registry = get_registry()
    result = await registry.execute(
        "repo_read", {"provider": active["provider"], "repo": active["repo"], "path": target},
    )
    if not isinstance(result, dict) or not result.get("ok"):
        return None
    return result.get("path", target), result.get("content", "")
