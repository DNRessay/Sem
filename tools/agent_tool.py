from typing import Any

AGENT_MAP = {
    "explore":   "agents.explore.ExploreAgent",
    "plan":      "agents.plan_agent.PlanAgent",
    "general":   "agents.general_agent.GeneralAgent",
    "guide":     "agents.guide_agent.GuideAgent",
    "dream":     "agents.dream_agent.DreamAgent",
    "proactive": "agents.proactive.ProactiveAgent",
    "swarm":     "agents.swarm.SwarmAgent",
    "buddy":     "agents.buddy.BuddyAgent",
    "bridge":    "agents.bridge.BridgeAgent",
    "coordinator": "agents.coordinator.CoordinatorAgent",
    "ultraplan": "agents.ultraplan.UltraPlanAgent",
}


class AgentTool:
    """
    Spawns sub-agents as standard tool calls.
    Flat and predictable — sub-agents are first-class registry citizens.
    """

    def __init__(self, tools_registry=None, cables_man_ref=None):
        self._tools = tools_registry
        self._cables_man = cables_man_ref

    async def spawn(self, agent_type: str, task: dict) -> Any:
        """Instantiate and run a named agent type."""
        module_path = AGENT_MAP.get(agent_type)
        if not module_path:
            return {"error": f"Unknown agent type: {agent_type}. Valid: {list(AGENT_MAP.keys())}"}

        agent_cls = self._import_agent(module_path)
        if agent_cls is None:
            return {"error": f"Could not import agent: {module_path}"}

        agent = agent_cls(
            tools_registry=self._tools,
            cables_man_ref=self._cables_man,
        )
        return await agent.run(task)

    def _import_agent(self, dotted_path: str):
        try:
            parts = dotted_path.rsplit(".", 1)
            module = __import__(parts[0], fromlist=[parts[1]])
            return getattr(module, parts[1])
        except (ImportError, AttributeError):
            return None

    def list_agents(self) -> list[str]:
        return list(AGENT_MAP.keys())

    # Convenience: callable as a tool registry entry
    async def __call__(self, agent_type: str = "general", task: dict = None) -> Any:
        return await self.spawn(agent_type, task or {})
