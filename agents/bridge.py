import json
import time

from agents.base_agent import BaseAgent
from cache import ddb_backend

_RESULTS = "bridge_result"


class BridgeAgent(BaseAgent):
    """Remote commands from a phone or another app (OpenClaw, MCP): run a
    query through CABLES MAN or call a registered tool. Runs each command
    straight away — a Lambda has no background loop to drain a queue — and
    keeps the result for a day so a later request can fetch it by id."""

    async def run(self, task: dict) -> dict:
        action = task.get("action", "run")
        if action in ("run", "enqueue"):
            command = task.get("command", {}) or {}
            cmd_id = f"bridge_{int(time.time() * 1000)}"
            self.log_audit(f"bridge:run:{cmd_id}")
            result = await self._dispatch(command)
            ddb_backend.set(_RESULTS, cmd_id, json.dumps(result, default=str), ttl=86400)
            return {"status": "complete", "cmd_id": cmd_id, "result": result}
        if action == "result":
            saved = ddb_backend.get(_RESULTS, task.get("cmd_id", ""))
            return {"status": "complete", "result": json.loads(saved)} if saved else {"status": "not_found"}
        return {"error": f"Unknown action: {action} (use run or result)"}

    async def _dispatch(self, command: dict) -> dict:
        cmd_type = command.get("type", "query")
        if cmd_type == "query":
            if not self._cables_man:
                from core.cables_man import CablesMan
                self._cables_man = CablesMan()
            return await self._cables_man.route({"query": command.get("query", ""), "session_id": self._session_id})
        if cmd_type == "tool":
            return await self.call_tool(command.get("tool", ""), command.get("args", {}))
        return {"error": f"Unknown command type: {cmd_type} (use query or tool)"}
