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

    async def schedule_reminder(self, message: str, delay_seconds: int, account_id: str = "") -> dict:
        """Persisted, so it survives between Lambda invocations; the KAIROS
        tick (agents/kairos.py) delivers it once due."""
        from config import settings
        from storage.neon_store import get_store

        db = await get_store()
        row = await db.add_reminder(account_id or settings.OWNER_ACCOUNT_ID, message, int(time.time()) + delay_seconds)
        return {"scheduled": True, "id": row["id"], "send_at": row["due_at"]}

    def get_history(self) -> list[dict]:
        return list(self._sent)
