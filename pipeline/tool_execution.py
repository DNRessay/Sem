from tools.registry import get_registry


class ToolExecution:
    def __init__(self, trust_mode: str = "AUTO"):
        self.trust_mode = trust_mode
        self.registry = get_registry()
        self._audit: list[dict] = []

    async def execute(self, tool_name: str, args: dict) -> dict:
        import time
        self._audit.append({"ts": time.time(), "tool": tool_name, "args": str(args)[:100]})
        return await self.registry.execute(tool_name, args, self.trust_mode)

    def get_audit(self) -> list[dict]:
        return list(self._audit)