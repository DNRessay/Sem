import asyncio
import time

import httpx

from agents.base_agent import BaseAgent
from config import settings

POLL_INTERVAL = 3      # seconds
MAX_WINDOW    = 1800   # 30 minutes


class UltraPlanAgent(BaseAgent):
    """
    Remote DeepSeek-R1 planning agent via Groq.
    Up to 30-minute planning window. Polls every 3s.
    Browser approval gate before any execution.
    """

    def __init__(self, tools_registry=None, cables_man_ref=None):
        super().__init__(tools_registry, cables_man_ref)
        self._pending_approval: dict[str, dict] = {}

    async def run(self, task: dict) -> dict:
        task_id = task.get("id", str(time.time()))
        query   = task.get("query", "")
        self.log_audit(f"ultraplan:start:{task_id}")

        plan = await self._deep_plan(query)
        self._pending_approval[task_id] = {"plan": plan, "approved": False, "ts": time.time()}

        # Wait for approval (browser / human gate) up to MAX_WINDOW
        approved = await self._wait_for_approval(task_id)
        if not approved:
            self.log_audit(f"ultraplan:rejected:{task_id}")
            return {"status": "rejected", "task_id": task_id}

        self.log_audit(f"ultraplan:executing:{task_id}")
        return {"status": "approved", "plan": plan, "task_id": task_id}

    async def _deep_plan(self, query: str) -> str:
        """Call DeepSeek-R1 via Groq for extended reasoning."""
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
            "max_tokens": 4096,
            "temperature": 0.6,
        }
        deadline = time.time() + MAX_WINDOW
        async with httpx.AsyncClient(timeout=MAX_WINDOW) as client:
            while time.time() < deadline:
                try:
                    r = await client.post("https://api.groq.com/openai/v1/chat/completions",
                                          json=payload, headers=headers)
                    data = r.json()
                    return data["choices"][0]["message"]["content"]
                except Exception:
                    await asyncio.sleep(POLL_INTERVAL)
        return "Planning timeout — no result produced."

    async def _wait_for_approval(self, task_id: str, timeout: int = 300) -> bool:
        """Poll for human approval up to timeout seconds."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            entry = self._pending_approval.get(task_id, {})
            if entry.get("approved"):
                return True
            await asyncio.sleep(POLL_INTERVAL)
        return False

    def approve(self, task_id: str) -> bool:
        """Called externally (browser endpoint) to approve a pending plan."""
        if task_id in self._pending_approval:
            self._pending_approval[task_id]["approved"] = True
            return True
        return False

    def get_pending(self) -> list[dict]:
        return [{"task_id": k, **v} for k, v in self._pending_approval.items()
                if not v["approved"]]
