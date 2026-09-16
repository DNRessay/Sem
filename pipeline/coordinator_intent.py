import re
from xml.sax.saxutils import escape

# "run these in parallel: a, b, c" / "coordinate: a, b, c" — routes to
# CoordinatorAgent (agents/coordinator.py), which fans the listed subtasks
# out concurrently via asyncio.gather. CoordinatorAgent's own interface is
# an XML task list (its tested contract); this builds that XML from a
# plain comma/semicolon/"and"-separated list so a chat message doesn't
# need to be hand-written XML.
_COORDINATOR_RE = re.compile(
    r"\b(?:run|do|handle)(?: these| this)? in parallel[:\s]+(.+)$|"
    r"\bcoordinate(?: these)?[:\s]+(.+)$",
    re.I,
)
_SPLIT_RE = re.compile(r",|;| and ", re.I)
_URL_RE = re.compile(r"^https?://", re.I)


def detect_coordinator_intent(query: str) -> list[str] | None:
    """Returns a list of subtask descriptions if this looks like a
    parallel-tasks request, else None. Requires at least 2 real subtasks
    after splitting — a single item isn't worth fanning out through
    CoordinatorAgent over just answering directly."""
    m = _COORDINATOR_RE.search(query)
    if not m:
        return None
    body = next(g for g in m.groups() if g)
    subtasks = [p.strip().rstrip("?.!") for p in _SPLIT_RE.split(body) if p.strip()]
    return subtasks if len(subtasks) >= 2 else None


def coordinator_status_label(subtasks: list[str]) -> str:
    return f"Coordinating {len(subtasks)} parallel task(s)…"


def _build_xml(subtasks: list[str]) -> str:
    parts = []
    for i, s in enumerate(subtasks):
        task_type = "fetch" if _URL_RE.match(s) else "general"
        parts.append(f'<task id="t{i}" type="{task_type}"><query>{escape(s)}</query></task>')
    return "".join(parts)


async def run_coordinator_intent(subtasks: list[str], session_id: str) -> dict:
    """Routes through CablesMan (Step 7) to CoordinatorAgent — real
    asyncio.gather fan-out, one worker per subtask. Returns the raw result
    dict, or {} on any failure so a caller can fall back cleanly."""
    from core.cables_man import CablesMan
    cables = CablesMan()
    result = await cables.route({
        "query": ", ".join(subtasks), "agent": "coordinator",
        "xml": _build_xml(subtasks), "session_id": session_id,
    })
    if not isinstance(result, dict) or result.get("error"):
        return {}
    return result


def format_coordinator_result(subtasks: list[str], result: dict) -> str:
    if not result or not result.get("results"):
        return ""
    lines = [f"**Coordinated {len(subtasks)} task(s):**", ""]
    for i, s in enumerate(subtasks):
        worker_result = result["results"].get(f"worker_{i}", {})
        if worker_result.get("error"):
            lines.append(f"- {s} — _error: {worker_result['error']}_")
        elif "content" in worker_result:
            snippet = (worker_result.get("content") or "")[:200].replace("\n", " ")
            lines.append(f"- {s} — {snippet}")
        else:
            lines.append(f"- {s} — done")
    return "\n".join(lines)
