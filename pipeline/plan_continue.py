import re

_CONTINUE_RE = re.compile(
    r"^\s*(continue(?: the plan| with the plan)?|keep going(?: with the plan)?|"
    r"next step|resume(?: the)? plan)\s*[.!]?\s*$",
    re.I,
)

# A plan step's "tool" field is free text PlanAgent's own Groq call chose,
# not a fixed enum — anything naming a shell/terminal/command is treated as
# bash-executable; everything else (general, browser, manual, modal, a tool
# name it invented, or missing entirely) is treated as narrative-only, no
# execution attempted.
_BASH_TOOL_RE = re.compile(r"bash|shell|terminal|command", re.I)

_TRANSLATE_MAX_TOKENS = 200


def detect_continue_intent(query: str) -> bool:
    """True for a bare "continue"-shaped message — deliberately strict
    (anchored, no trailing content) so an ordinary sentence that happens to
    contain the word "continue" ("continue reading this for me") doesn't
    misfire, the same false-positive shape already fixed once this session
    for the bash intent's bare "bash" trigger."""
    return bool(_CONTINUE_RE.match(query.strip()))


def continue_status_label() -> str:
    return "Continuing the plan…"


def _next_pending_step(plan: dict) -> dict | None:
    for step in plan.get("steps", []):
        if step.get("status", "pending") == "pending":
            return step
    return None


async def run_continue_intent(session_id: str) -> dict:
    """Finds the session's persisted plan (see storage.neon_store.save_plan)
    and advances it by exactly one step — never more than one, and never
    more than the single bounded Groq call below, for the same rate-limit
    reason every other intent in this app stays to one call per turn. A
    step whose tool hints at bash gets that translated command actually
    run (through the same Step 5 permission-gated path pipeline.bash_intent
    already uses); anything else just gets a short narrative note. Returns
    a result dict describing what happened, or {"done": None} if there's
    no active plan / nothing left to do."""
    from storage.neon_store import get_store
    db = await get_store()
    plan = await db.get_active_plan(session_id)
    if not plan:
        return {"done": None}

    step = _next_pending_step(plan)
    if not step:
        return {"done": True, "goal": plan.get("goal", "")}

    from pipeline.query_engine import QueryEngine
    engine = QueryEngine()
    prompt = (
        f"You are executing one step of an existing plan for this goal: {plan.get('goal', '')}\n"
        f"Step {step.get('n', '?')}: {step.get('action', '')}\n\n"
        "If this step is best done by running a shell command, respond with "
        "ONLY the exact command to run — nothing else, no explanation, no "
        "markdown fences. If it is not something a shell command can do, "
        "respond with a short 1-2 sentence note on what was done or should "
        "be noted instead — still nothing else, no preamble."
    )
    try:
        result = await engine.call_llm(
            [{"role": "user", "content": prompt}], session_id=session_id,
            max_tokens=_TRANSLATE_MAX_TOKENS, temperature=0.2,
        )
        response_text = (result.get("content") or "").strip()
    except Exception as e:
        response_text = f"(couldn't work out this step: {e})"

    is_bash = bool(_BASH_TOOL_RE.search(step.get("tool") or ""))
    bash_result = None
    if is_bash and response_text:
        from pipeline.bash_intent import run_bash_intent
        bash_result = await run_bash_intent(response_text, session_id)

    outcome = response_text
    if bash_result is not None:
        from pipeline.bash_intent import format_bash_result
        outcome = format_bash_result(bash_result)

    await db.update_plan_step(session_id, step.get("n"), "done", outcome[:2000])
    remaining = sum(1 for s in plan["steps"] if s.get("status", "pending") == "pending" and s.get("n") != step.get("n"))

    return {
        "done": False,
        "step_n": step.get("n"),
        "action": step.get("action", ""),
        "command": response_text if is_bash else None,
        "outcome": outcome,
        "remaining": remaining,
        "total": len(plan["steps"]),
    }


def format_continue_result(result: dict) -> str:
    if result.get("done") is None:
        return "There's no active plan for this session yet — ask me to plan something first."
    if result.get("done") is True:
        return f"**Plan complete** — every step for \"{result.get('goal', '')}\" is done."

    lines = [f"**Step {result['step_n']} of {result['total']}:** {result['action']}"]
    if result.get("command"):
        lines.append(f"\n`{result['command']}`\n")
    lines.append(result.get("outcome", ""))
    remaining = result.get("remaining", 0)
    lines.append(f"\n_{remaining} step(s) left — say \"continue\" to keep going._" if remaining else "\n**That was the last step.**")
    return "\n".join(lines)
