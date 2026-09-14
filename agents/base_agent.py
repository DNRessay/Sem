import time
from abc import ABC, abstractmethod


class BaseAgent(ABC):
    """
    Abstract base for all Semblance agents.
    All agents access external resources exclusively through TOOLS.
    Zero direct API calls permitted.
    """

    def __init__(self, tools_registry=None, cables_man_ref=None, session_id: str = "default", trust_mode: str = "AUTO"):
        self._tools = tools_registry
        self._cables_man = cables_man_ref
        self._session_id = session_id
        self._trust_mode = trust_mode
        self._audit: list[dict] = []

    @abstractmethod
    async def run(self, task: dict) -> dict:
        """Execute the agent's primary task. Must be implemented."""

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        """All tool calls routed through Step 5 (pipeline.tool_execution) —
        not straight to the registry — so every sub-agent tool call is
        permission-gated against this agent's trust mode and audited (both
        in-process and persisted, see ToolExecution._persist) the same way
        as any other tool call in the app."""
        if self._tools is None or self._tools.get(tool_name) is None:
            return {"error": f"Tool '{tool_name}' not found in registry"}
        self.log_audit(f"call_tool:{tool_name}")
        from pipeline.tool_execution import get_tool_execution
        execution = get_tool_execution(trust_mode=self._trust_mode)
        return await execution.execute(tool_name, args, session_id=self._session_id)

    def log_audit(self, action: str) -> None:
        """Append action to append-only audit log with timestamp."""
        self._audit.append({"ts": time.time(), "agent": self.__class__.__name__, "action": action})

    def get_audit(self) -> list[dict]:
        return list(self._audit)
