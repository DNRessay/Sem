import asyncio
import time

from agents.base_agent import BaseAgent


class BridgeAgent(BaseAgent):
    """
    Remote CLI control from phone or external browser.
    Exposes a lightweight WebSocket / polling endpoint.
    Allows triggering CABLES MAN agents remotely.
    """

    def __init__(self, tools_registry=None, cables_man_ref=None, **kwargs):
        super().__init__(tools_registry, cables_man_ref, **kwargs)
        self._command_queue: asyncio.Queue = asyncio.Queue()
        self._result_store: dict[str, dict] = {}

    async def run(self, task: dict) -> dict:
        action = task.get("action", "enqueue")

        if action == "enqueue":
            cmd_id = await self.enqueue_command(task.get("command", {}))
            return {"status": "enqueued", "cmd_id": cmd_id}
        elif action == "result":
            return self._result_store.get(task.get("cmd_id", ""), {"status": "not_found"})
        elif action == "list_pending":
            return {"pending": self._command_queue.qsize()}
        else:
            return {"error": f"Unknown action: {action}"}

    async def enqueue_command(self, command: dict) -> str:
        """Accept a remote command and put it in the execution queue."""
        cmd_id = f"bridge_{int(time.time() * 1000)}"
        command["_id"] = cmd_id
        await self._command_queue.put(command)
        self.log_audit(f"bridge:enqueue:{cmd_id}")
        return cmd_id

    async def process_queue(self):
        """Background loop — processes remote commands as they arrive."""
        while True:
            try:
                command = await asyncio.wait_for(self._command_queue.get(), timeout=5.0)
                cmd_id = command.get("_id", "unknown")
                self.log_audit(f"bridge:process:{cmd_id}")

                result = await self._dispatch(command)
                self._result_store[cmd_id] = result
                self._command_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.log_audit(f"bridge:error:{e}")

    async def _dispatch(self, command: dict) -> dict:
        """Route the remote command to the appropriate agent or tool."""
        cmd_type = command.get("type", "query")

        if cmd_type == "query" and self._cables_man:
            return await self._cables_man.route({"query": command.get("query", "")})
        elif cmd_type == "tool":
            return await self.call_tool(command.get("tool", ""), command.get("args", {}))
        else:
            return {"status": "dispatched", "type": cmd_type, "command": command}

    def get_result(self, cmd_id: str) -> dict:
        return self._result_store.get(cmd_id, {"status": "pending"})
