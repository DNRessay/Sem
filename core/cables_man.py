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
        await self._persist_event(session, agent_type, f"routing:{query[:60]}")

        from tools.agent_tool import AgentTool
        spawner = AgentTool(tools_registry=self.registry, cables_man_ref=self)
        result = await spawner.spawn(agent_type, task)

        status = result.get("status") if isinstance(result, dict) else None
        await self._persist_event(session, agent_type, f"{status or 'error'}")
        if status == "complete":
            self.working_mem.clear(session)

        return result

    async def _persist_event(self, session_id: str, agent: str, action: str) -> None:
        """Best-effort — see pipeline.tool_execution.ToolExecution._persist
        for why a DB hiccup here must never break routing itself."""
        try:
            from storage.neon_store import get_store
            db = await get_store()
            await db.save_agent_event(session_id, agent, action)
        except Exception:
            pass

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