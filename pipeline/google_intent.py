import re

# Deterministic phrasing, same reasoning as every other intent in this
# package — no LLM tool-calling, just regex triggers, dispatching straight
# to the tools registry (Calendar/Gmail/Drive/Contacts — tools/google/*)
# rather than through CablesMan, since these are single tool calls with no
# sub-agent reasoning involved. Each detector returns enough (tool, action,
# kwargs, label) for run_google_intent to make one registry.execute call.
_CAL_LIST_RE = re.compile(
    r"\b(?:what'?s on|check|list|show) my calendar\b|\bmy (?:upcoming )?events\b|\bmy schedule\b", re.I,
)
_CAL_CREATE_RE = re.compile(
    r"\b(?:add|create|schedule) (?:an? )?event[:\s]+(.+?)\s+from\s+(\S+)\s+to\s+(\S+)\s*$", re.I,
)
_CAL_DELETE_RE = re.compile(r"\b(?:delete|cancel|remove) (?:the )?(?:calendar )?event[:\s]+(\S+)\s*$", re.I)

_GMAIL_LIST_RE = re.compile(
    r"\bcheck my (?:gmail|email|inbox)\b|\bmy (?:recent )?emails\b|\bwhat'?s in my inbox\b", re.I,
)
_GMAIL_SEND_RE = re.compile(
    r"\bsend an? email to (\S+@\S+)(?: with)? subject (.+?) (?:saying|body|that says)[:\s]+(.+)$", re.I,
)

_NOTE_CREATE_RE = re.compile(r"\b(?:save|create|write) a note[:\s]+(.+)$", re.I)
_NOTE_LIST_RE = re.compile(r"\bmy notes\b|\blist my (?:drive )?(?:files|notes)\b", re.I)

_CONTACT_SEARCH_RE = re.compile(r"\b(?:who is|look up|find) (.+?) in my contacts\b", re.I)
_CONTACT_LIST_RE = re.compile(r"\blist my contacts\b|\bmy contacts\b", re.I)


def detect_google_intent(query: str) -> dict | None:
    """Returns {"tool", "action", "kwargs", "label"} for a Calendar/Gmail/
    Drive-notes/Contacts request, else None. Checked in specificity order
    within each area (create/delete before a bare list phrase) so e.g.
    "add event: X from A to B" doesn't also get caught by the looser
    "my events" list trigger."""
    m = _CAL_CREATE_RE.search(query)
    if m:
        summary = m.group(1).strip()
        return {
            "tool": "calendar", "action": "create_event",
            "kwargs": {"summary": summary, "start": m.group(2), "end": m.group(3)},
            "label": f'Creating calendar event "{summary}"',
        }
    m = _CAL_DELETE_RE.search(query)
    if m:
        return {"tool": "calendar", "action": "delete_event", "kwargs": {"event_id": m.group(1)},
                "label": "Deleting calendar event"}
    if _CAL_LIST_RE.search(query):
        return {"tool": "calendar", "action": "list_events", "kwargs": {}, "label": "Checking your calendar"}

    m = _GMAIL_SEND_RE.search(query)
    if m:
        to = m.group(1)
        return {
            "tool": "gmail", "action": "send_message",
            "kwargs": {"to": to, "subject": m.group(2).strip(), "body": m.group(3).strip()},
            "label": f"Sending email to {to}",
        }
    if _GMAIL_LIST_RE.search(query):
        return {"tool": "gmail", "action": "list_messages", "kwargs": {}, "label": "Checking your inbox"}

    m = _NOTE_CREATE_RE.search(query)
    if m:
        return {"tool": "drive", "action": "create_note",
                "kwargs": {"title": "Note", "content": m.group(1).strip()}, "label": "Saving note"}
    if _NOTE_LIST_RE.search(query):
        return {"tool": "drive", "action": "list_files", "kwargs": {}, "label": "Checking your notes"}

    m = _CONTACT_SEARCH_RE.search(query)
    if m:
        term = m.group(1).strip()
        return {"tool": "contacts", "action": "search_contacts", "kwargs": {"query": term},
                "label": f'Looking up "{term}" in contacts'}
    if _CONTACT_LIST_RE.search(query):
        return {"tool": "contacts", "action": "list_contacts", "kwargs": {}, "label": "Checking your contacts"}

    return None


async def run_google_intent(intent: dict, account_id: str, session_id: str) -> dict:
    """One registry.execute call to the matched Google tool — every
    Calendar/Gmail/Drive/Contacts tool shares the same {"error": ...}
    shape when the account has no Google connector yet (see
    tools/google/_auth.py), so a caller never needs special-casing for
    "not connected" versus any other failure."""
    from tools.registry import get_registry
    registry = get_registry()
    args = {"action": intent["action"], "account_id": account_id, **intent["kwargs"]}
    result = await registry.execute(intent["tool"], args)
    return result if isinstance(result, dict) else {"error": "Unexpected response from Google tool"}


def format_google_result(intent: dict, result: dict) -> str:
    if not isinstance(result, dict):
        return ""
    if result.get("error"):
        return f"**{intent['label']}** — {result['error']}"

    tool, action = intent["tool"], intent["action"]

    if tool == "calendar" and action == "list_events":
        events = result.get("events", [])
        if not events:
            return "No upcoming events on your calendar."
        lines = ["**Upcoming events:**", ""]
        for e in events[:10]:
            loc = f" @ {e['location']}" if e.get("location") else ""
            lines.append(f"- {e.get('summary')} — {e.get('start', '?')}{loc}")
        return "\n".join(lines)
    if tool == "calendar" and action == "create_event":
        link = result.get("htmlLink")
        return f"Created **{result.get('summary')}**" + (f" — [view]({link})" if link else "")
    if tool == "calendar" and action == "delete_event":
        return f"Deleted event `{result.get('deleted')}`."

    if tool == "gmail" and action == "list_messages":
        msgs = result.get("messages", [])
        if not msgs:
            return "No recent messages."
        lines = ["**Recent emails:**", ""]
        for m in msgs[:10]:
            snippet = (m.get("snippet") or "")[:100]
            lines.append(f"- **{m.get('subject') or '(no subject)'}** from {m.get('from')} — {snippet}")
        return "\n".join(lines)
    if tool == "gmail" and action == "send_message":
        return f"Sent to **{result.get('sent_to')}** — subject: {result.get('subject')}"

    if tool == "drive" and action == "create_note":
        return f"Saved note **{result.get('title')}** (file id `{result.get('file_id')}`)."
    if tool == "drive" and action == "list_files":
        files = result.get("files", [])
        if not files:
            return "No notes/files found — SEMBLANCE can only see files it created itself (Drive's drive.file scope)."
        lines = ["**Your files:**", ""]
        for f in files[:10]:
            lines.append(f"- {f.get('name')} (`{f.get('id')}`)")
        return "\n".join(lines)

    if tool == "contacts":
        contacts = result.get("contacts", [])
        if not contacts:
            return "No matching contacts found."
        lines = ["**Contacts:**", ""]
        for c in contacts[:10]:
            email = c["emails"][0] if c.get("emails") else ""
            lines.append(f"- {c.get('name')} — {email}")
        return "\n".join(lines)

    return "Done."
