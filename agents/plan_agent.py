import httpx

from agents.base_agent import BaseAgent
from config import settings


class PlanAgent(BaseAgent):
    """
    Designs strategy before any action.
    Prevents sloppy execution — always plan first, then execute.
    Spawned via AgentTool.
    """

    async def run(self, task: dict) -> dict:
        goal     = task.get("goal", "")
        context  = task.get("context", "")
        depth    = task.get("depth", "medium")   # quick | medium | deep

        self.log_audit(f"plan:start:{depth}:{goal[:60]}")

        if not goal:
            return {"error": "No goal provided to PlanAgent"}

        plan = await self._generate_plan(goal, context, depth)
        return {
            "goal": goal,
            "depth": depth,
            "plan": plan,
        }

    async def _generate_plan(self, goal: str, context: str, depth: str) -> dict:
        max_tokens = {"quick": 512, "medium": 1024, "deep": 2048}.get(depth, 1024)

        system = (
            "You are a precise execution planner. "
            "Given a goal, produce a numbered step-by-step plan. "
            "Each step must be concrete and actionable — no vague instructions. "
            "Output JSON: {steps: [{n, action, tool, expected_output}], risks: [], success_criteria: ''}"
        )

        messages = [{"role": "user", "content": f"Goal: {goal}\n\nContext: {context}"}]

        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.GROQ_MODEL,
            "messages": [{"role": "system", "content": system}] + messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload, headers=headers
                )
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                import json
                return json.loads(content)
        except Exception as e:
            return {
                "steps": [{"n": 1, "action": goal, "tool": "general", "expected_output": "completion"}],
                "risks": [],
                "success_criteria": "Task completed without error",
                "error": str(e),
            }
