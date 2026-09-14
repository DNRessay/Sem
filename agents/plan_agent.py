import json

from agents.base_agent import BaseAgent
from pipeline.query_engine import QueryEngine


class PlanAgent(BaseAgent):
    """
    Designs strategy before any action.
    Spawned via AgentTool, or directly by a "make a plan for X"-shaped
    chat message (see pipeline/agent_intent.py).
    """

    # Capped at QueryEngine's own safe ceiling (_DEFAULT_MAX_TOKENS, 800) —
    # the previous 512/1024/2048 spread let "deep" alone request more output
    # tokens than this Groq tier allows in an entire minute (1000 OTPM),
    # which is the exact failure QueryEngine exists to avoid.
    _DEPTH_TOKENS = {"quick": 400, "medium": 800, "deep": 800}

    def __init__(self, tools_registry=None, cables_man_ref=None, **kwargs):
        super().__init__(tools_registry, cables_man_ref, **kwargs)
        self._query_engine = QueryEngine()

    async def run(self, task: dict) -> dict:
        goal = task.get("goal", "")
        context = task.get("context", "")
        depth = task.get("depth", "medium")   # quick | medium | deep

        self.log_audit(f"plan:start:{depth}:{goal[:60]}")

        if not goal:
            return {"error": "No goal provided to PlanAgent"}

        plan = await self._generate_plan(goal, context, depth)
        # "status": "complete" matters beyond this return value — CablesMan.
        # route reads it to decide what to write to the agent_events audit
        # trail (and whether to clear working_mem for this session). Without
        # it, a fully successful plan was logged as "error" in AgentFeed —
        # this key's absence, not any actual failure, was the bug.
        return {
            "status": "complete",
            "goal": goal,
            "depth": depth,
            "plan": plan,
        }

    async def _generate_plan(self, goal: str, context: str, depth: str) -> dict:
        max_tokens = self._DEPTH_TOKENS.get(depth, 800)

        system = (
            "You are a precise execution planner. "
            "Given a goal, produce a numbered step-by-step plan. "
            "Each step must be concrete and actionable — no vague instructions. "
            "Output JSON: {steps: [{n, action, tool, expected_output}], risks: [], success_criteria: ''}"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Goal: {goal}\n\nContext: {context}"},
        ]

        try:
            result = await self._query_engine.call_llm(
                messages, session_id=self._session_id, max_tokens=max_tokens,
                temperature=0.2, response_format={"type": "json_object"},
            )
            return json.loads(result.get("content", "{}"))
        except Exception as e:
            return {
                "steps": [{"n": 1, "action": goal, "tool": "general", "expected_output": "completion"}],
                "risks": [],
                "success_criteria": "Task completed without error",
                "error": str(e),
            }
