import time

from agents.base_agent import BaseAgent


class ProactiveAgent(BaseAgent):
    """
    Outreach and reminders. Messages go out through KAIROS's delivery
    (always the app, plus WhatsApp/OpenClaw when configured); reminders are
    stored and sent by the KAIROS tick once due.
    """

    def __init__(self, tools_registry=None, cables_man_ref=None, **kwargs):
        super().__init__(tools_registry, cables_man_ref, **kwargs)
        self._sent: list[dict] = []

    async def run(self, task: dict) -> dict:
        """Two jobs: a natural-language reminder request ("remind me to call
        the bank tomorrow at 9") becomes a stored reminder that the KAIROS
        tick delivers; an explicit {"message": ...} is sent right away to the
        app (plus WhatsApp/OpenClaw when configured)."""
        message = task.get("message", "")
        if not message:
            return await self._reminder_from_text(task.get("query", ""))
        from agents.kairos import deliver
        from config import settings

        trigger = task.get("trigger", "manual")
        self.log_audit(f"proactive:send:{trigger}")
        sent = await deliver(settings.OWNER_ACCOUNT_ID, task.get("title") or "📣 SEMBLANCE", message)
        self._sent.append({"ts": time.time(), "trigger": trigger, "message": message[:200], "sent": sent})
        return {"status": "complete", "sent_to": sent}

    async def _reminder_from_text(self, query: str) -> dict:
        import json
        import re
        from datetime import datetime, timedelta, timezone

        from pipeline import llm_providers

        if not query.strip():
            return {"status": "error", "error": "Nothing to remind you about"}
        sast = timezone(timedelta(hours=2))
        now = datetime.now(sast)
        prompt = (f"It is {now.isoformat(timespec='minutes')} (South Africa). Turn this into a reminder. Reply with JSON "
                  f'only: {{"message": what to remind, "when": RFC3339 with +02:00}}. If no time is given, use 09:00 '
                  f"the next morning.\n\nRequest: {query}")
        result = await llm_providers.complete("auto", [{"role": "user", "content": prompt}], max_tokens=200)
        match = re.search(r"\{.*\}", result.get("content") or "", re.S)
        try:
            data = json.loads(match.group(0)) if match else {}
            when = datetime.fromisoformat(str(data["when"]).replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, ValueError):
            return {"status": "error", "error": "Couldn't work out when to remind you — try e.g. 'remind me at 3pm to…'"}
        if when.tzinfo is None:
            when = when.replace(tzinfo=sast)
        delay = max(60, int((when - now).total_seconds()))
        scheduled = await self.schedule_reminder(str(data.get("message") or query)[:500], delay)
        self.log_audit("proactive:reminder")
        return {"status": "complete", "result": f"Reminder set for {when.astimezone(sast).strftime('%a %d %b %H:%M')}: "
                                                f"{data.get('message') or query}", **scheduled}

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
