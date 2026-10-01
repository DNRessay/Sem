from agents.base_agent import BaseAgent
from pipeline import llm_providers


class UltraPlanAgent(BaseAgent):
    """
    Deep planning with a big output budget on the free model chain
    — a bigger-budget, slower alternative to PlanAgent's quick pass, for a
    goal that genuinely needs more reasoning. Single bounded call, same
    shape as PlanAgent (agents/plan_agent.py).

    The original design here (poll every 3s for up to 30 minutes, wait for
    a browser approval gate before returning) could never actually run:
    AgentTool.spawn() (tools/agent_tool.py) constructs a fresh
    UltraPlanAgent on every call, so `_pending_approval` never survived
    past the single request that created it, and nothing exposed an
    `approve()` endpoint for a second HTTP request to call anyway — the
    same class of bug as DreamAgent's in-memory gate counters resetting
    every Lambda invocation. Returns the plan directly instead.
    """

    _MAX_TOKENS = 4096

    async def run(self, task: dict) -> dict:
        query = task.get("query", "")
        self.log_audit(f"ultraplan:start:{query[:60]}")
        if not query:
            return {"error": "No goal provided to UltraPlanAgent"}

        plan = await self._deep_plan(query)
        return {"status": "complete", "goal": query, "plan": plan}

    async def _deep_plan(self, query: str) -> str:
        """One long, detailed reply on the free chain (Bonsai → Gemini → Groq).
        A failure comes back as a readable message, never an exception."""
        result = await llm_providers.complete("auto", [
            {"role": "system", "content": "You are a deep strategic planner. Think step-by-step, produce a detailed execution plan."},
            {"role": "user", "content": query},
        ], max_tokens=self._MAX_TOKENS)
        if "error" in result:
            return f"Planning failed — {result['error'][:300]}"
        return result.get("content") or "Planning failed — the model returned nothing."
