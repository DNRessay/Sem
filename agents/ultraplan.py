import httpx

from agents.base_agent import BaseAgent
from config import settings


class UltraPlanAgent(BaseAgent):
    """
    Deep planning via Groq's larger GPT-OSS-120B model (GROQ_PLANNING_MODEL)
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
    _TIMEOUT_SECONDS = 25  # well under Lambda's 30s Globals.Function.Timeout

    async def run(self, task: dict) -> dict:
        query = task.get("query", "")
        self.log_audit(f"ultraplan:start:{query[:60]}")
        if not query:
            return {"error": "No goal provided to UltraPlanAgent"}

        plan = await self._deep_plan(query)
        return {"status": "complete", "goal": query, "plan": plan}

    async def _deep_plan(self, query: str) -> str:
        """Calls GPT-OSS-120B via Groq directly (not through QueryEngine —
        this model's own use case, one long detailed reply, is exactly what
        QueryEngine's tight _DEFAULT_MAX_TOKENS/cache-vector machinery isn't
        tuned for). Any failure returns a plain error string rather than
        raising, so a bad response degrades to a visible message instead of
        crashing the whole chat turn."""
        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.GROQ_PLANNING_MODEL,
            "messages": [
                {"role": "system", "content": "You are a deep strategic planner. Think step-by-step, produce a detailed execution plan."},
                {"role": "user", "content": query},
            ],
            "max_tokens": self._MAX_TOKENS,
            "temperature": 0.6,
        }
        try:
            async with httpx.AsyncClient(timeout=self._TIMEOUT_SECONDS) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload, headers=headers,
                )
                data = r.json()
        except httpx.HTTPError as e:
            return f"Planning failed — network error: {e}"

        if "choices" not in data:
            return f"Planning failed — Groq API error (status {r.status_code}): {data}"
        return data["choices"][0]["message"]["content"]
