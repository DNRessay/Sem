from agents.base_agent import BaseAgent
from pipeline.query_engine import QueryEngine


class GeneralAgent(BaseAgent):
    """
    Handles a delegated task end-to-end. The workhorse of CABLES MAN.

    A single bounded call through the shared QueryEngine — not a
    multi-round ReAct loop. This account's Groq tier caps output at 1000
    tokens/minute total, shared across every call the app makes that
    minute (the main chat reply included, when a delegated task runs
    alongside it); an unbounded iterate-and-call-tools loop, each
    iteration spending its own max_tokens budget, would 429 almost
    immediately — the exact failure this app's own QueryEngine was built
    to stay under. One call, capped at QueryEngine's already-safe default,
    is the right size for what this account can actually sustain.
    """

    def __init__(self, tools_registry=None, cables_man_ref=None, **kwargs):
        super().__init__(tools_registry, cables_man_ref, **kwargs)
        self._query_engine = QueryEngine()

    async def run(self, task: dict) -> dict:
        query = task.get("query", "")
        context = task.get("context", "")

        self.log_audit(f"general:start:{query[:60]}")

        if not query:
            return {"error": "No query provided"}

        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": query})

        try:
            result = await self._query_engine.call_llm(messages, session_id=self._session_id)
            return {"status": "complete", "result": result.get("content", ""), "iterations": 1}
        except Exception as e:
            return {"status": "error", "result": f"Something went wrong: {e}", "iterations": 0}
