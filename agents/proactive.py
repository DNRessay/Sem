import time

from agents.base_agent import BaseAgent


class ProactiveAgent(BaseAgent):
    """
    KAIROS-driven outreach agent.
    Semblance initiates contact — alerts, suggestions, reminders without being asked.
    All outbound messages routed through OpenClaw bridge.
    """

    def __init__(self, tools_registry=None, cables_man_ref=None, **kwargs):
        super().__init__(tools_registry, cables_man_ref, **kwargs)
        self._sent: list[dict] = []

    async def run(self, task: dict) -> dict:
        trigger = task.get("trigger", "manual")
        message = task.get("message", "")
        channel = task.get("channel", "default")
        recipient = task.get("recipient", "")

        if not message:
            return {"error": "No message to send"}

        self.log_audit(f"proactive:send:{trigger}:{channel}")
        result = await self._send_outreach(channel, recipient, message)

        self._sent.append({
            "ts": time.time(),
            "trigger": trigger,
            "channel": channel,
            "recipient": recipient,
            "message": message[:200],
        })

        return {"status": "sent", "channel": channel, "result": result}

    async def _send_outreach(self, channel: str, recipient: str, message: str) -> dict:
        """Route outbound message through OpenClaw."""
        from tools.openclaw_bridge import OpenClawBridge
        bridge = OpenClawBridge()
        try:
            if channel == "whatsapp" and recipient:
                return await bridge.send_whatsapp(recipient, message)
            elif channel == "telegram" and recipient:
                return await bridge.send_telegram(recipient, message)
            else:
                return await bridge.send_message(channel, message)
        except Exception as e:
            return {"error": str(e)}

    def schedule_reminder(self, message: str, channel: str, delay_seconds: int) -> dict:
        """Register a future reminder. KAIROS picks these up on next tick."""
        entry = {
            "message": message,
            "channel": channel,
            "send_at": time.time() + delay_seconds,
            "sent": False,
        }
        self._sent.append(entry)
        return {"scheduled": True, "send_at": entry["send_at"]}

    def get_pending_reminders(self) -> list[dict]:
        now = time.time()
        return [r for r in self._sent if not r.get("sent") and r.get("send_at", 0) <= now]

    def get_history(self) -> list[dict]:
        return list(self._sent)
