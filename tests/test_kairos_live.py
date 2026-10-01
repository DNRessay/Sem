from datetime import datetime, timedelta, timezone

import pytest

from agents import kairos as kairos_mod
from agents.cowork_agent import CoworkAgent
from agents.kairos import KairosDaemon
from pipeline.ctx_pressure import SUMMARY_TARGET, CTXPressure

SAST = timezone(timedelta(hours=2))


class Store:
    def __init__(self):
        self.state, self.turns, self.titles, self.reminders = {}, [], {}, []

    async def get_state(self, key):
        return self.state.get(key)

    async def set_state(self, key, value):
        self.state[key] = value

    async def save_turn(self, session_id, role, content):
        self.turns.append((session_id, role, content))

    async def set_session_title(self, session_id, title):
        self.titles[session_id] = title

    async def add_reminder(self, account_id, message, due_at):
        row = {"id": len(self.reminders) + 1, "account_id": account_id, "message": message, "due_at": due_at, "sent_at": None}
        self.reminders.append(row)
        return row

    async def list_reminders(self, account_id, include_sent=False):
        return [r for r in self.reminders if r["sent_at"] is None]

    async def claim_due_reminders(self, limit=20):
        import time
        due = [r for r in self.reminders if r["sent_at"] is None and r["due_at"] <= time.time()]
        for r in due:
            r["sent_at"] = time.time()
        return due


@pytest.fixture
def store(monkeypatch):
    s = Store()

    async def fake_get_store():
        return s

    for target in ("agents.kairos.get_store", "agents.cowork_agent.get_store"):
        monkeypatch.setattr(target, fake_get_store)
    from config import settings
    monkeypatch.setattr(settings, "OWNER_WHATSAPP_NUMBER", "")
    monkeypatch.setattr(settings, "OPENCLAW_URL", "")
    return s


@pytest.fixture
def brief_inputs(monkeypatch):
    async def cal(self, action, **kw):
        return {"events": [{"summary": "Supplier call", "start": "09:00"}]}

    async def mail(self, action, **kw):
        return {"error": "Google not connected"}

    prompts = []

    async def complete(model, messages, **kw):
        prompts.append(messages[0]["content"])
        return {"content": "• 09:00 Supplier call"}

    monkeypatch.setattr("agents.kairos.CalendarTool.query", cal)
    monkeypatch.setattr("agents.kairos.GmailTool.query", mail)
    monkeypatch.setattr("agents.kairos.llm_providers.complete", complete)
    return prompts


@pytest.mark.asyncio
async def test_morning_brief_is_sent_once_a_day_at_the_brief_hour(store, brief_inputs, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "KAIROS_BRIEF_HOUR", 7)
    k = KairosDaemon()
    seven = datetime(2026, 10, 2, 7, 5, tzinfo=SAST)
    await k._maybe_morning_brief(datetime(2026, 10, 2, 8, 0, tzinfo=SAST))
    assert store.turns == []
    await k._maybe_morning_brief(seven)
    await k._maybe_morning_brief(seven + timedelta(minutes=15))
    assert len(store.turns) == 1 and store.turns[0][2] == "• 09:00 Supplier call"
    assert "Supplier call" in brief_inputs[0] and "(not connected)" in brief_inputs[0]
    assert list(store.titles.values())[0].startswith("☀️ Morning brief")


@pytest.mark.asyncio
async def test_due_reminders_are_delivered_once(store):
    import time
    await store.add_reminder("owner", "Call the bank", int(time.time()) - 5)
    await store.add_reminder("owner", "Later thing", int(time.time()) + 3600)
    k = KairosDaemon()
    await k._send_due_reminders()
    await k._send_due_reminders()
    assert [t[2] for t in store.turns] == ["Call the bank"]


@pytest.mark.asyncio
async def test_whatsapp_delivery_when_configured(store, monkeypatch):
    from config import settings
    for name, value in {"OWNER_WHATSAPP_NUMBER": "27820000000", "WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_ID": "p"}.items():
        monkeypatch.setattr(settings, name, value)
    sent = []

    async def fake_send(self, phone, message):
        sent.append((phone, message))
        return {"id": "w1"}

    monkeypatch.setattr("agents.kairos.WhatsAppTool.send", fake_send)
    where = await kairos_mod.deliver("owner", "⏰ Reminder", "Call the bank")
    assert where == ["app", "whatsapp"] and sent[0][0] == "27820000000"


@pytest.mark.asyncio
async def test_cowork_set_reminder_stores_it(store):
    agent = CoworkAgent("owner")
    result = await agent.dispatch("set_reminder", {"message": "Pay invoice", "when": "2026-10-03T09:00:00+02:00"})
    assert result["ok"] and result["due"] == "Sat 03 Oct 09:00"
    assert (await agent.dispatch("list_reminders", {}))["reminders"][0]["message"] == "Pay invoice"
    assert not (await agent.dispatch("set_reminder", {"message": "x", "when": "tomorrow"}))["ok"]


def test_autocompact_keeps_the_start_and_the_end():
    ctx = "IDENTITY " + "x" * 30_000 + " MEMORIES"
    out = CTXPressure().autocompact(ctx)
    assert len(out) <= SUMMARY_TARGET and out.startswith("IDENTITY") and out.endswith("MEMORIES")
