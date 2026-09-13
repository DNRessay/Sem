import httpx

from agents.base_agent import BaseAgent
from config import settings


class GeneralAgent(BaseAgent):
    """
    Handles complex multi-step tasks end-to-end.
    The workhorse of CABLES MAN.
    Uses Groq LLM + tool calls in a ReAct loop.
    """

    MAX_ITERATIONS = 10

    async def run(self, task: dict) -> dict:
        query     = task.get("query", "")
        context   = task.get("context", "")

        self.log_audit(f"general:start:{query[:60]}")

        if not query:
            return {"error": "No query provided"}

        history = []
        if context:
            history.append({"role": "system", "content": context})

        history.append({"role": "user", "content": query})

        for iteration in range(self.MAX_ITERATIONS):
            self.log_audit(f"general:iteration:{iteration}")
            response = await self._llm_call(history)

            if response.get("done"):
                return {"status": "complete", "result": response.get("content", ""), "iterations": iteration + 1}

            # If LLM wants to call a tool
            if response.get("tool_call"):
                tool_name = response["tool_call"]["name"]
                tool_args = response["tool_call"]["args"]
                tool_result = await self.call_tool(tool_name, tool_args)
                history.append({"role": "assistant", "content": f"[tool:{tool_name}]"})
                history.append({"role": "user", "content": f"Tool result: {tool_result}"})
            else:
                content = response.get("content", "")
                history.append({"role": "assistant", "content": content})
                return {"status": "complete", "result": content, "iterations": iteration + 1}

        return {"status": "max_iterations", "result": history[-1].get("content", ""), "iterations": self.MAX_ITERATIONS}

    async def _llm_call(self, history: list) -> dict:
        """Call Groq LLM. Return {content, done, tool_call}."""
        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.GROQ_MODEL,
            "messages": history,
            "max_tokens": 1024,
            "temperature": 0.5,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload, headers=headers
                )
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                finish = data["choices"][0].get("finish_reason", "stop")
                return {"content": content, "done": finish == "stop", "tool_call": None}
        except Exception as e:
            return {"content": f"LLM error: {e}", "done": True, "tool_call": None}
