import pytest
import respx
from httpx import Response

from tools.google.calendar_tool import CalendarTool

BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


@pytest.mark.asyncio
async def test_query_returns_error_when_not_connected(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return {"error": "No Google connector configured for this account — connect Google first (Calendar needs it)."}

    monkeypatch.setattr("tools.google.calendar_tool.get_google_token", fake_get_token)
    result = await CalendarTool().query("list_events")
    assert "connect Google first" in result["error"]


@pytest.mark.asyncio
async def test_list_events_returns_upcoming_events(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.calendar_tool.get_google_token", fake_get_token)
    with respx.mock:
        respx.get(BASE).mock(return_value=Response(200, json={"items": [
            {"id": "e1", "summary": "Standup", "start": {"dateTime": "2026-09-20T09:00:00Z"},
             "end": {"dateTime": "2026-09-20T09:30:00Z"}, "location": "Zoom"},
        ]}))
        result = await CalendarTool().query("list_events")

    assert result == {"events": [
        {"id": "e1", "summary": "Standup", "start": "2026-09-20T09:00:00Z",
         "end": "2026-09-20T09:30:00Z", "location": "Zoom"},
    ]}


@pytest.mark.asyncio
async def test_create_event_requires_start_and_end(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.calendar_tool.get_google_token", fake_get_token)
    result = await CalendarTool().query("create_event", summary="Meeting")
    assert "start and end" in result["error"]


@pytest.mark.asyncio
async def test_create_event_posts_the_event_body(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.calendar_tool.get_google_token", fake_get_token)
    with respx.mock:
        route = respx.post(BASE).mock(return_value=Response(200, json={
            "id": "new1", "summary": "Meeting", "htmlLink": "https://calendar.google.com/x",
        }))
        result = await CalendarTool().query(
            "create_event", summary="Meeting", start="2026-09-20T09:00:00Z", end="2026-09-20T09:30:00Z",
        )

    assert result == {"id": "new1", "summary": "Meeting", "htmlLink": "https://calendar.google.com/x"}
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["summary"] == "Meeting"
    assert body["start"] == {"dateTime": "2026-09-20T09:00:00Z"}


@pytest.mark.asyncio
async def test_delete_event_requires_event_id(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.calendar_tool.get_google_token", fake_get_token)
    result = await CalendarTool().query("delete_event")
    assert result == {"error": "event_id required"}


@pytest.mark.asyncio
async def test_delete_event_succeeds(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.calendar_tool.get_google_token", fake_get_token)
    with respx.mock:
        respx.delete(f"{BASE}/e1").mock(return_value=Response(204))
        result = await CalendarTool().query("delete_event", event_id="e1")
    assert result == {"deleted": "e1"}


@pytest.mark.asyncio
async def test_unknown_action_returns_a_clear_error(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.calendar_tool.get_google_token", fake_get_token)
    result = await CalendarTool().query("frobnicate")
    assert "Unknown calendar action" in result["error"]


@pytest.mark.asyncio
async def test_api_error_is_surfaced_not_raised(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.calendar_tool.get_google_token", fake_get_token)
    with respx.mock:
        respx.get(BASE).mock(return_value=Response(403, text="insufficient scope"))
        result = await CalendarTool().query("list_events")
    assert "403" in result["error"]
