import time
from abc import ABC, abstractmethod


class BaseAgent(ABC):
    """
    Abstract base for all Semblance agents.
    All agents access external resources exclusively through TOOLS.
    Zero direct API calls permitted.
    """

    def __init__(self, tools_registry=None, cables_man_ref=None):
        self._tools = tools_registry
        self._cables_man = cables_man_ref
        self._audit: list[dict] = []

    @abstractmethod
    async def run(self, task: dict) -> dict:
        """Execute the agent's primary task. Must be implemented."""

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        """All tool calls routed through this method."""
        if self._tools is None:
            return {"error": f"No tool registry available for {tool_name}"}
        tool = self._tools.get(tool_name)
        if not tool:
            return {"error": f"Tool '{tool_name}' not found in registry"}
        self.log_audit(f"call_tool:{tool_name}")
        try:
            return await tool["handler"](**args)
        except Exception as e:
            return {"error": str(e)}

    def log_audit(self, action: str) -> None:
        """Append action to append-only audit log with timestamp."""
        self._audit.append({"ts": time.time(), "agent": self.__class__.__name__, "action": action})

    def get_audit(self) -> list[dict]:
        return list(self._audit)
