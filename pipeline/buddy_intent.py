import re

# "buddy" is a distinctive enough noun that these can stay a bit looser
# than e.g. plan_continue's bare-word anchoring, but each non-status
# action still requires its own verb immediately next to "buddy" so an
# unrelated sentence that happens to mention a buddy ("my buddy Dave said
# ...") never misfires into pet/feed/train/play/rename/new.
_RENAME_RE = re.compile(r"\brename (?:my |the )?buddy to (.+)$", re.I)
_NEW_RE = re.compile(r"\b(?:hatch|get|create|start)(?: me)?(?: a| my)?(?: new)? buddy\b", re.I)
_PET_RE = re.compile(r"\bpet (?:my |the )?buddy\b", re.I)
_FEED_RE = re.compile(r"\bfeed (?:my |the )?buddy\b", re.I)
_TRAIN_RE = re.compile(r"\btrain (?:my |the )?buddy\b", re.I)
_PLAY_RE = re.compile(r"\bplay with (?:my |the )?buddy\b", re.I)
# Status is the loosest trigger, so it's anchored to the whole message —
# same shape as plan_continue's bare "continue" — so it only fires on a
# message that IS the check, not one that merely mentions a buddy.
_STATUS_RE = re.compile(r"^\s*(?:check |show )?(?:my |the )?buddy(?: status)?\s*[.!?]?\s*$", re.I)

_LABELS = {
    "status": "Checking your buddy…",
    "pet": "Petting your buddy…",
    "feed": "Feeding your buddy…",
    "train": "Training your buddy…",
    "play": "Playing with your buddy…",
    "rename": "Renaming your buddy…",
    "new": "Hatching a new buddy…",
}


def detect_buddy_intent(query: str) -> dict | None:
    """Returns {"action": ..., "name": ...?} for a buddy-shaped message,
    else None. Rename is checked first since its trailing name capture
    would otherwise also satisfy the looser status pattern."""
    q = query.strip()
    if not q:
        return None
    m = _RENAME_RE.search(q)
    if m:
        name = m.group(1).strip().rstrip("?.!")
        if name:
            return {"action": "rename", "name": name}
    if _NEW_RE.search(q):
        return {"action": "new"}
    if _PET_RE.search(q):
        return {"action": "pet"}
    if _FEED_RE.search(q):
        return {"action": "feed"}
    if _TRAIN_RE.search(q):
        return {"action": "train"}
    if _PLAY_RE.search(q):
        return {"action": "play"}
    if _STATUS_RE.match(q):
        return {"action": "status"}
    return None


def buddy_status_label(action: str) -> str:
    return _LABELS.get(action, "Working with your buddy…")


async def run_buddy_intent(intent: dict, session_id: str) -> dict:
    """Routes through CablesMan (Step 7) to BuddyAgent, which now persists
    the buddy in Neon (storage.neon_store.get_buddy/save_buddy) rather
    than an in-memory dict — CablesMan.route() builds a fresh agent
    instance on every call, so only a real DB round-trip survives across
    separate chat turns/Lambda invocations."""
    from core.cables_man import CablesMan
    cables = CablesMan()
    task = {"agent": "buddy", "action": intent["action"], "session_id": session_id}
    if intent.get("name"):
        task["name"] = intent["name"]
    result = await cables.route(task)
    return result if isinstance(result, dict) else {"error": "buddy agent returned an unexpected result"}


def _format_status(status: dict) -> str:
    if not status:
        return ""
    stats = status.get("stats", {})
    return (
        f"**{status.get('name', '?')}** — {status.get('rarity', '')} {status.get('species', '')}\n"
        f"Level {status.get('level', '?')} ({status.get('xp', 0)}/{status.get('xp_next', '?')} XP) · "
        f"Mood: {status.get('mood', '?')} · HP: {status.get('hp', '?')}\n"
        f"Energy {stats.get('energy', '?')} · Happiness {stats.get('happiness', '?')} · "
        f"Focus {stats.get('focus', '?')}"
    )


def format_buddy_result(action: str, result: dict) -> str:
    if not isinstance(result, dict) or result.get("error"):
        detail = result.get("error", "unknown error") if isinstance(result, dict) else "unknown error"
        return f"Couldn't reach your buddy: {detail}"

    if action == "status":
        return _format_status(result) or "No buddy yet — say \"get a buddy\" to hatch one."

    message = result.get("message", "")
    status_block = _format_status(result.get("status", {}))
    return "\n\n".join(part for part in (message, status_block) if part)
