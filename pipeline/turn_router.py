"""One Laya call per chat message decides what the reply needs, before any of it is fetched:

  repo     — the attached repo's tools (pipeline/chat_tools.py)
  recall   — long-term memory search; skipped for messages that don't need it, saving an embedding
             call and a database query on every "thanks" / "what's the weather"
  remember — the user wants something kept: it becomes a pinned fact Sem sees in every chat

Without Laya (not deployed, cold, down) every field falls back to the old behaviour: keyword rules for
repo and remember, memory search always on."""
import re

from pipeline.repo_context import needs_repo
from tools import laya_client

QUESTIONS = {
    "repo": {"type": "noul", "instructions": "Is this message about source code, files, bugs or a software repository?"},
    "recall": {"type": "noul", "instructions": "Does the message refer to something from an earlier conversation, "
                                               "or to personal facts the user told the assistant before?"},
    "remember": {"type": "noul", "instructions": "Is the user asking the assistant to remember, note or keep "
                                                 "something for later?"},
}
_REMEMBER_RE = re.compile(r"\b(remember (?:that|this|my|i)|don'?t forget|keep in mind|note (?:that|down)|make a note)\b", re.I)


def _p(answers: dict, key: str) -> float | None:
    value = (answers.get(key) or {}).get("noul")
    return float(value) if isinstance(value, (int, float)) else None


async def route(message: str, recent: list[dict] | None = None) -> dict:
    """{"repo": bool, "recall": bool, "remember": bool, "laya": bool}."""
    answers = await laya_client.decide(message[-2000:], QUESTIONS) or {}
    repo, recall, remember = _p(answers, "repo"), _p(answers, "recall"), _p(answers, "remember")
    return {
        "repo": (repo is not None and repo >= 0.5) or needs_repo(message, recent),
        "recall": recall is None or recall >= 0.15,
        "remember": remember >= 0.6 if remember is not None else bool(_REMEMBER_RE.search(message)),
        "laya": bool(answers),
    }
