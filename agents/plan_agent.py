import json
import re

from agents.base_agent import BaseAgent
from pipeline import llm_providers


class PlanAgent(BaseAgent):
    """
    Designs strategy before any action.
    Spawned via AgentTool, or directly by a "make a plan for X"-shaped
    chat message (see pipeline/agent_intent.py).
    """

    # Runs on the free chain (Bonsai → Gemini → Groq); Groq's own provider
    # cap still keeps its share small if it ends up answering.
    _DEPTH_TOKENS = {"quick": 600, "medium": 1200, "deep": 2400}

    async def run(self, task: dict) -> dict:
        goal = task.get("goal", "")
        context = task.get("context", "")
        depth = task.get("depth", "medium")   # quick | medium | deep

        self.log_audit(f"plan:start:{depth}:{goal[:60]}")

        if not goal:
            return {"error": "No goal provided to PlanAgent"}

        plan = await self._generate_plan(goal, context, depth)
        if "error" in plan:
            # No pretend plan: say it failed so the chat falls back to a normal answer.
            return {"status": "error", "goal": goal, "error": plan["error"]}
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
            "Reply with ONLY a JSON object: {\"steps\": [{\"n\", \"action\", \"tool\", \"expected_output\"}], \"risks\": [], \"success_criteria\": \"\"}"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Goal: {goal}\n\nContext: {context}"},
        ]

        result = await llm_providers.complete("auto", messages, max_tokens=max_tokens)
        if "error" in result:
            return {"error": result["error"]}
        text = result.get("content") or ""
        match = re.search(r"\{[\s\S]*\}", text)
        try:
            return json.loads(match.group(0) if match else text)
        except ValueError:
            return {"error": "the model didn't return a plan in the expected format"}
