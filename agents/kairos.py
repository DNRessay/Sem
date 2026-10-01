import asyncio
import time
from datetime import datetime, timedelta, timezone

from config import settings
from pipeline import llm_providers
from storage.neon_store import get_store
from tools.google.calendar_tool import CalendarTool
from tools.google.gmail_tool import GmailTool
from tools.misc.whatsapp_tool import WhatsAppTool
from tools.openclaw_bridge import OpenClawBridge

TICK_BUDGET = 120  # seconds — leaves the 900s tick Lambda room for DREAM and a Code automation
_SAST = timezone(timedelta(hours=2))

_BRIEF_PROMPT = """Write the owner's morning brief for {day}. Keep it short and useful: today's schedule in time
order (flag clashes or tight gaps), emails that look like they need a reply, reminders due today, then one line
on what to tackle first. Plain text with short bullet lines — it may be read on WhatsApp. Skip empty sections.

Calendar:
{calendar}

Unread email (last 24h):
{email}

Reminders due today:
{reminders}"""


async def deliver(account_id: str, title: str, text: str) -> list[str]:
    """Always saved as a chat in the app; also sent on WhatsApp and/or
    through OpenClaw when those are configured. Returns where it went."""
    db = await get_store()
    session_id = f"kairos_{account_id}_{int(time.time())}"
    await db.save_turn(session_id, "assistant", text)
    await db.set_session_title(session_id, title)
    sent = ["app"]
    if settings.OWNER_WHATSAPP_NUMBER and settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_ID:
        result = await WhatsAppTool().send(settings.OWNER_WHATSAPP_NUMBER, f"{title}\n\n{text}"[:4000])
        if not result.get("error"):
            sent.append("whatsapp")
    if settings.OPENCLAW_URL:
        result = await OpenClawBridge().send_message("default", f"{title}\n\n{text}")
        if isinstance(result, dict) and not result.get("error"):
            sent.append("openclaw")
    return sent


class KairosDaemon:
    """SEMBLANCE's proactive side. Each tick (every 15 minutes from
    EventBridge via tick_handler.py, or every minute on an always-on box)
    delivers due reminders and, once a day at KAIROS_BRIEF_HOUR, the morning
    brief. Everything it sends lands in the app as a chat, plus WhatsApp /
    OpenClaw when configured."""

    def __init__(self):
        self._running = False
        self._audit: list[dict] = []

    async def start(self):
        """Heavy-tier: continuous loop. Only viable on an always-on process
        (EC2/Fargate) — never inside Lambda, which freezes between invocations."""
        self._running = True
        while self._running:
            await self.run_once()
            await asyncio.sleep(60)

    def stop(self):
        self._running = False

    async def run_once(self):
        """Medium-tier: a single tick. This is what the scheduled Lambda
        (tick_handler.py) calls once per EventBridge firing."""
        try:
            await asyncio.wait_for(self._tick(), timeout=TICK_BUDGET)
        except asyncio.TimeoutError:
            self._log("tick_timeout", f"Tick exceeded {TICK_BUDGET}s budget")
        except Exception as e:
            self._log("tick_error", str(e)[:300])

    async def _tick(self):
        await self._send_due_reminders()
        await self._maybe_morning_brief()

    async def _send_due_reminders(self):
        db = await get_store()
        for r in await db.claim_due_reminders():
            sent = await deliver(r["account_id"], "⏰ Reminder", r["message"])
            self._log("reminder", f"{r['id']} -> {','.join(sent)}")

    async def _maybe_morning_brief(self, now: datetime | None = None):
        now = now or datetime.now(_SAST)
        if not settings.KAIROS_MORNING_BRIEF or now.hour != settings.KAIROS_BRIEF_HOUR:
            return
        db = await get_store()
        today = now.strftime("%Y-%m-%d")
        if await db.get_state("kairos:last_brief") == today:
            return
        await db.set_state("kairos:last_brief", today)  # claim first: overlapping ticks must not double-send
        text = await self._build_brief(settings.OWNER_ACCOUNT_ID, now)
        sent = await deliver(settings.OWNER_ACCOUNT_ID, f"☀️ Morning brief · {now.strftime('%a %d %b')}", text)
        self._log("morning_brief", ",".join(sent))

    async def _build_brief(self, account_id: str, now: datetime) -> str:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        cal, mail = await asyncio.gather(
            CalendarTool().query("list_events", account_id=account_id, time_min=start.isoformat(), max_results=15),
            GmailTool().query("list_messages", account_id=account_id, query="is:unread newer_than:1d", max_results=10),
            return_exceptions=True,
        )
        db = await get_store()
        end_of_day = int((start + timedelta(days=1)).timestamp())
        reminders = [r for r in await db.list_reminders(account_id) if r["due_at"] < end_of_day]

        def section(value, key):
            if isinstance(value, Exception) or not isinstance(value, dict) or value.get("error"):
                return "(not connected)"
            items = value.get(key) or []
            return "\n".join(str(i)[:300] for i in items[:15]) or "(none)"

        prompt = _BRIEF_PROMPT.format(
            day=now.strftime("%A %d %B %Y"),
            calendar=section(cal, "events"), email=section(mail, "messages"),
            reminders="\n".join(
                f"{datetime.fromtimestamp(r['due_at'], _SAST).strftime('%H:%M')} {r['message']}" for r in reminders
            ) or "(none)",
        )
        result = await llm_providers.complete("auto", [{"role": "user", "content": prompt}], max_tokens=800)
        if "error" in result:
            return f"Couldn't write today's brief ({result['error'][:150]}).\n\nCalendar:\n{prompt.split('Calendar:')[1]}"
        return result.get("content") or "Nothing on the calendar and no unread email. Enjoy the day."

    def _log(self, action: str, detail: str):
        self._audit.append({"ts": time.time(), "action": action, "detail": detail})

    def get_audit(self) -> list[dict]:
        return list(self._audit)
