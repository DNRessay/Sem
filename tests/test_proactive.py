import pytest

from agents.proactive import ProactiveAgent


@pytest.mark.asyncio
async def test_reminder_request_becomes_a_stored_reminder(monkeypatch):
    stored = []

    async def fake_complete(model, messages, **kw):
        return {"content": '{"message": "Call the bank", "when": "2099-01-05T09:00:00+02:00"}'}

    async def fake_schedule(self, message, delay_seconds, account_id=""):
        stored.append((message, delay_seconds))
        return {"scheduled": True, "id": 1, "send_at": 0}

    monkeypatch.setattr("pipeline.llm_providers.complete", fake_complete)
    monkeypatch.setattr(ProactiveAgent, "schedule_reminder", fake_schedule)
    result = await ProactiveAgent().run({"query": "remind me to call the bank on 5 Jan at 9"})
    assert result["status"] == "complete" and "Mon 05 Jan 09:00" in result["result"]
    assert stored[0][0] == "Call the bank" and stored[0][1] > 0


@pytest.mark.asyncio
async def test_unparseable_reminder_is_a_clear_error(monkeypatch):
    async def fake_complete(model, messages, **kw):
        return {"content": "sure!"}

    monkeypatch.setattr("pipeline.llm_providers.complete", fake_complete)
    result = await ProactiveAgent().run({"query": "remind me sometime"})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_explicit_message_is_delivered(monkeypatch):
    sent = []

    async def fake_deliver(account_id, title, text):
        sent.append((title, text))
        return ["app"]

    monkeypatch.setattr("agents.kairos.deliver", fake_deliver)
    result = await ProactiveAgent().run({"message": "Server is down", "title": "Alert"})
    assert result == {"status": "complete", "sent_to": ["app"]} and sent == [("Alert", "Server is down")]
