from tools.registry import get_registry


class ToolExecution:
    """Step 5 — permission-gated tool execution. Every tool call made by a
    CABLES MAN sub-agent (see agents/base_agent.py) routes through here, not
    straight to the registry: this is where the permission mode is actually
    enforced (ToolsRegistry.execute already checks a tool's own permission
    level against trust_mode) and where the call gets audited.

    The audit log is dual: an in-process list (cheap, survives for the rest
    of this one Lambda invocation) and a best-effort row in Postgres via
    NeonStore.save_agent_event — the persistent one is what actually matters,
    since a chat POST and a later /status GET poll are almost always
    different Lambda invocations with no shared memory. A DB hiccup here
    must never fail the tool call itself, so persistence failures are
    swallowed."""

    def __init__(self, trust_mode: str = "AUTO"):
        self.trust_mode = trust_mode
        self.registry = get_registry()
        self._audit: list[dict] = []

    async def execute(self, tool_name: str, args: dict, session_id: str = "default") -> dict:
        import time
        result = await self.registry.execute(tool_name, args, self.trust_mode)
        self._audit.append({"ts": time.time(), "tool": tool_name, "args": str(args)[:100]})
        await self._persist(session_id, tool_name, args, result)
        return result

    async def _persist(self, session_id: str, tool_name: str, args: dict, result) -> None:
        try:
            from storage.neon_store import get_store
            db = await get_store()
            outcome = "blocked" if isinstance(result, dict) and (result.get("blocked") or result.get("error")) else "ok"
            await db.save_agent_event(session_id, tool_name, f"{outcome}:{str(args)[:80]}")
        except Exception:
            pass

    def get_audit(self) -> list[dict]:
        return list(self._audit)


# ─── Warm-start singleton ────────────────────────────────────────────────────
# Shared across every sub-agent tool call within a warm Lambda invocation, the
# same pattern as tools/registry.py's get_registry() — one audit trail per
# execution environment rather than a fresh, empty one per agent instance.

_execution: ToolExecution | None = None


def get_tool_execution(trust_mode: str = "AUTO") -> ToolExecution:
    global _execution
    if _execution is None or _execution.trust_mode != trust_mode:
        _execution = ToolExecution(trust_mode=trust_mode)
    return _execution
