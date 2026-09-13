import asyncio

from memory.working_mem import WorkingMem
from tools.registry import get_registry


class CablesMan:
    def __init__(self):
        self.registry = get_registry()
        self.working_mem = WorkingMem()
        self._agents = {}

    async def route(self, task: dict) -> dict:
        query = task.get("query", "")
        session = task.get("session_id", "default")
        agent_type = task.get("agent", self._classify(query))

        self.working_mem.append(session, f"routing:{agent_type}:{query[:60]}")

        from tools.agent_tool import AgentTool
        spawner = AgentTool(tools_registry=self.registry, cables_man_ref=self)
        result = await spawner.spawn(agent_type, task)

        if result.get("status") == "complete":
            self.working_mem.clear(session)

        return result

    def _classify(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["plan", "strategy", "design", "architect"]):
            return "plan"
        if any(w in q for w in ["search", "find", "look up", "explore"]):
            return "explore"
        if any(w in q for w in ["remind", "schedule", "alert", "notify"]):
            return "proactive"
        return "general"

    async def broadcast(self, task: dict, agent_types: list[str]) -> dict:
        from tools.agent_tool import AgentTool
        spawner = AgentTool(tools_registry=self.registry, cables_man_ref=self)
        results = await asyncio.gather(*[
            spawner.spawn(a, task) for a in agent_types
        ], return_exceptions=True)
        return {
            a: (r if not isinstance(r, Exception) else {"error": str(r)})
            for a, r in zip(agent_types, results)
        }