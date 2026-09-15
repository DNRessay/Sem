import re

# Deterministic phrasing — same reasoning as pipeline/web_context.py's
# detect_web_intent and pipeline/repo_context.py's detect_repo_intent: no LLM
# tool-calling involved, just regex triggers. This is what actually connects
# CABLES MAN (core/cables_man.py — Step 7, sub-agent delegation) and its
# PlanAgent/ExploreAgent (routed through Step 5's permission-gated,
# audited tool execution) to a real chat message, instead of code that
# exists but nothing in the live /chat path ever calls.
_PLAN_RE = re.compile(
    r"\b(make (?:me )?a plan (?:for|to)|help me plan|plan out|draft a plan (?:for|to)|"
    r"create a plan (?:for|to)|what are the steps to|steps to (?:take to|complete|finish)|"
    r"map out (?:the )?steps (?:for|to))\b",
    re.I,
)
# "search/grep the code/source for X" — deliberately distinct from
# repo_context.py's _GREP_RE ("search the repo/codebase for X"), which
# searches an externally attached repo cloned via "Add repo". This searches
# SEMBLANCE's own deployed source (see agents/explore.py's _code_search) —
# no external repo needed, and no LLM call at all, so it's always safe to
# run. "code"/"source" must be followed by a separator (never glued onto
# "base") so this never fires on the same phrasing repo_intent already
# owns — repo_intent is checked first anyway (see gateway/router.py).
_CODE_RE = re.compile(
    r"\b(?:search|grep|find|look)(?: in)?(?: the| our)? (?:code|source)(?: for)?[:\s]+(.+)$",
    re.I,
)


def detect_plan_intent(query: str) -> str | None:
    """Returns the goal (the full query) if this looks like a planning
    request, else None. The whole query is passed through as the goal
    (same shape as web_context's search intent) rather than trying to strip
    the trigger phrase out — PlanAgent's prompt already asks the model to
    read the goal in context, so the extra words don't hurt."""
    if _PLAN_RE.search(query):
        return query
    return None


def detect_explore_intent(query: str) -> str | None:
    """Returns the search term for a codebase search, else None."""
    m = _CODE_RE.search(query)
    if m:
        return m.group(1).strip().rstrip("?.!")
    return None


def plan_status_label() -> str:
    return "Planning…"


def explore_status_label(term: str) -> str:
    return f'Searching SEMBLANCE\'s own code for "{term}"…'


async def run_plan_intent(goal: str, session_id: str) -> dict:
    """Routes through CablesMan (Step 7 — sub-agent delegation) to
    PlanAgent, a single bounded Groq call via the shared QueryEngine (see
    agents/plan_agent.py). Returns the raw plan dict, or an empty dict on
    any failure so a broken/misconfigured planner degrades to "no plan
    generated," never a chat-breaking error.

    Persists the plan (see storage.neon_store.save_plan) when it comes
    back with real steps — a generated plan used to only ever exist in
    that one reply; now "continue" (pipeline/plan_continue.py) can come
    back on a later turn and pick up the next unfinished step instead of
    the plan being gone the moment the reply scrolled away."""
    from core.cables_man import CablesMan
    cables = CablesMan()
    result = await cables.route({
        "query": goal, "agent": "plan", "goal": goal, "session_id": session_id,
    })
    if not isinstance(result, dict) or result.get("error"):
        return {}
    plan = result.get("plan") or {}
    if plan.get("steps"):
        from storage.neon_store import get_store
        db = await get_store()
        await db.save_plan(session_id, goal, plan["steps"])
    return plan


def format_plan(plan: dict) -> str:
    if not plan or not plan.get("steps"):
        return ""
    lines = ["**Plan:**"]
    for step in plan["steps"]:
        n = step.get("n", "?")
        action = step.get("action", "")
        tool = step.get("tool")
        suffix = f" _(tool: {tool})_" if tool else ""
        lines.append(f"{n}. {action}{suffix}")
    if plan.get("risks"):
        lines.append("\n**Risks:**")
        lines.extend(f"- {r}" for r in plan["risks"])
    if plan.get("success_criteria"):
        lines.append(f"\n**Done when:** {plan['success_criteria']}")
    return "\n".join(lines)


async def run_explore_intent(term: str, session_id: str) -> list:
    """Routes through CablesMan to ExploreAgent, scope='code' — a local
    grep over SEMBLANCE's own deployed source, no LLM call involved at all
    (see agents/explore.py._code_search). Returns the list of matches, or
    an empty list on any failure."""
    from core.cables_man import CablesMan
    cables = CablesMan()
    result = await cables.route({
        "query": term, "agent": "explore", "scope": "code", "session_id": session_id,
    })
    if not isinstance(result, dict):
        return []
    return (result.get("results") or {}).get("code") or []


def format_matches(term: str, matches: list) -> str:
    if not matches:
        return ""
    lines = [f'Found {len(matches)} match(es) for "{term}" in SEMBLANCE\'s own source:', ""]
    for m in matches[:20]:
        lines.append(f"- `{m.get('file')}:{m.get('line')}` — {m.get('content')}")
    return "\n".join(lines)
