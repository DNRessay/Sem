import re

# Deterministic phrasing — same reasoning as every other intent detector in
# this app (web/repo/plan/explore): no LLM tool-calling involved, and a
# command this consequential especially isn't something to trigger on a
# loose keyword match. Requires an explicit trigger phrase, not just "run"
# or "execute" alone (which show up constantly in ordinary conversation —
# "run the numbers", "execute the plan").
#
# A bare "bash[:\s]+(.+)" alternative used to be in this same pattern —
# "Do you have bash tools" matched it (captured "tools" as the literal
# command to run: "bash" + a space + everything after) since ordinary
# conversation says the word "bash" far more often than it means "run this
# as a command." The colon-shorthand below is scoped much tighter: anchored
# to the start of the message and requiring an actual colon, not just
# whitespace, which "asking about bash" essentially never looks like.
_BASH_RE = re.compile(
    r"\b(?:run\s+bash|run\s+shell|run\s+command|run\s+this\s+command|"
    r"execute\s+command|execute\s+this\s+command)[:\s]+(.+)$",
    re.I,
)
_BASH_SHORTHAND_RE = re.compile(r"^\s*bash:\s*(.+)$", re.I)


def detect_bash_intent(query: str) -> str | None:
    """Returns the command to run, or None."""
    m = _BASH_RE.search(query)
    if m:
        return m.group(1).strip()
    m = _BASH_SHORTHAND_RE.match(query)
    if m:
        return m.group(1).strip()
    return None


def bash_status_label() -> str:
    return "Running…"


async def run_bash_intent(command: str, session_id: str) -> dict:
    """Executes via the existing tool registry (Step 5 — permission-gated,
    audited, same as every other sub-agent tool call). Runs inside this
    Lambda's own sandbox (/tmp — the one writable directory in a standard
    Lambda runtime), not on the user's own machine, Colab, or Termux —
    there is no connection between the two. It also currently has no
    awareness of a session's actively-cloned repo (see gateway/connectors.py
    fetch_repo): that repo lives on Modal's persistent Volume, and this
    Lambda runtime has no `git` binary to clone it locally, nor does the
    Modal repo tool yet expose a bulk-file-export endpoint that could
    materialize it into /tmp another way. A command that references repo
    files will simply not find them.

    trust_mode is BYPASS here, not AUTO — that skips only the registry's
    soft "does this look like a write?" heuristic (tools/registry.py's
    _is_write_op, a crude substring match that would otherwise block any
    command whose text happens to contain "create"/"update"/etc, a common
    thing to actually ask a shell to do). It does NOT skip BashTool's own
    23 hardcoded security checks — those run unconditionally, regardless
    of trust_mode, inside BashTool.execute itself. Reasonable specifically
    because every command here is confined to the throwaway /tmp sandbox
    with no access to anything that matters."""
    from pipeline.tool_execution import get_tool_execution
    execution = get_tool_execution(trust_mode="BYPASS")
    return await execution.execute("bash", {"command": command}, session_id=session_id)


def format_bash_result(result: dict) -> str:
    if not isinstance(result, dict):
        return ""
    if result.get("blocked"):
        checks = ", ".join(result.get("failed_checks", []))
        return f"Blocked by the security gate ({checks}):\n\n{result.get('error', '')}"
    if result.get("status") == "confirmation_required":
        return (
            "This looks like a write operation and needs a higher trust "
            "level than this chat session has — not run."
        )
    if result.get("error"):
        return f"Error: {result['error']}"

    parts = []
    stdout = (result.get("stdout") or "").strip()
    stderr = (result.get("stderr") or "").strip()
    exit_code = result.get("exit_code")
    if stdout:
        parts.append(f"```\n{stdout}\n```")
    if stderr:
        parts.append(f"**stderr:**\n```\n{stderr}\n```")
    if not stdout and not stderr:
        parts.append("_(no output)_")
    parts.append(f"Exit code: {exit_code}")
    return "\n\n".join(parts)
