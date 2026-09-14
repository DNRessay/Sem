import asyncio
import json
import os
import time

from agents.base_agent import BaseAgent

SOCKET_PATH = "/tmp/semblance_uds.sock"


class UDSInbox(BaseAgent):
    """
    Agent-to-agent messaging over Unix Domain Sockets.
    Enables direct inter-agent communication without going through CABLES MAN.
    """

    def __init__(self, tools_registry=None, cables_man_ref=None, **kwargs):
        super().__init__(tools_registry, cables_man_ref, **kwargs)
        self._inbox: list[dict] = []
        self._server: asyncio.AbstractServer | None = None
        self._running = False

    async def run(self, task: dict) -> dict:
        action = task.get("action", "send")

        if action == "send":
            return await self.send(
                task.get("to", ""),
                task.get("message", ""),
                task.get("payload", {}),
            )
        elif action == "read":
            return {"messages": self.read_inbox()}
        elif action == "start_server":
            await self.start_server()
            return {"status": "server_started", "socket": SOCKET_PATH}
        else:
            return {"error": f"Unknown action: {action}"}

    async def send(self, to_agent: str, message: str, payload: dict = None) -> dict:
        """Send a message to another agent via UDS."""
        envelope = {
            "to": to_agent,
            "from": "semblance",
            "message": message,
            "payload": payload or {},
            "ts": time.time(),
        }
        self.log_audit(f"uds:send:{to_agent}:{message[:40]}")

        if not os.path.exists(SOCKET_PATH):
            # Fallback: write to in-memory inbox
            self._inbox.append(envelope)
            return {"status": "queued_local", "envelope": envelope}

        try:
            reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
            writer.write(json.dumps(envelope).encode() + b"\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return {"status": "sent", "to": to_agent}
        except Exception as e:
            self._inbox.append(envelope)
            return {"status": "queued_fallback", "error": str(e)}

    def read_inbox(self, clear: bool = False) -> list[dict]:
        """Read all messages in inbox."""
        messages = list(self._inbox)
        if clear:
            self._inbox.clear()
        return messages

    async def start_server(self):
        """Start UDS server to receive inbound messages."""
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=SOCKET_PATH
        )
        self._running = True
        self.log_audit("uds:server:started")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            data = await reader.readline()
            envelope = json.loads(data.decode())
            self._inbox.append(envelope)
            self.log_audit(f"uds:received:{envelope.get('from', '?')}:{envelope.get('message', '')[:40]}")
        except Exception:
            pass
        finally:
            writer.close()

    def stop(self):
        if self._server:
            self._server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        self._running = False
