import pytest

from pipeline.google_intent import detect_google_intent, format_google_result, run_google_intent


def test_detect_calendar_list():
    intent = detect_google_intent("what's on my calendar")
    assert intent["tool"] == "calendar"
    assert intent["action"] == "list_events"

    assert detect_google_intent("check my calendar")["action"] == "list_events"
    assert detect_google_intent("my upcoming events")["action"] == "list_events"
    assert detect_google_intent("my schedule")["action"] == "list_events"


def test_detect_calendar_create():
    intent = detect_google_intent("add event: Team standup from 2026-09-20T09:00:00 to 2026-09-20T09:30:00")
    assert intent["tool"] == "calendar"
    assert intent["action"] == "create_event"
    assert intent["kwargs"] == {
        "summary": "Team standup", "start": "2026-09-20T09:00:00", "end": "2026-09-20T09:30:00",
    }


def test_detect_calendar_delete():
    intent = detect_google_intent("delete event: abc123")
    assert intent["tool"] == "calendar"
    assert intent["action"] == "delete_event"
    assert intent["kwargs"] == {"event_id": "abc123"}


def test_detect_gmail_list():
    assert detect_google_intent("check my email")["action"] == "list_messages"
    assert detect_google_intent("check my inbox")["action"] == "list_messages"
    assert detect_google_intent("my recent emails")["action"] == "list_messages"


def test_detect_gmail_send():
    intent = detect_google_intent("send an email to bob@example.com subject Hello saying how are you doing")
    assert intent["tool"] == "gmail"
    assert intent["action"] == "send_message"
    assert intent["kwargs"] == {"to": "bob@example.com", "subject": "Hello", "body": "how are you doing"}


def test_detect_note_create():
    intent = detect_google_intent("save a note: buy milk and eggs")
    assert intent["tool"] == "drive"
    assert intent["action"] == "create_note"
    assert intent["kwargs"] == {"title": "Note", "content": "buy milk and eggs"}


def test_detect_note_list():
    assert detect_google_intent("my notes")["action"] == "list_files"
    assert detect_google_intent("list my files")["action"] == "list_files"


def test_detect_contact_search():
    intent = detect_google_intent("who is Jane Doe in my contacts")
    assert intent["tool"] == "contacts"
    assert intent["action"] == "search_contacts"
    assert intent["kwargs"] == {"query": "Jane Doe"}


def test_detect_contact_list():
    assert detect_google_intent("list my contacts")["action"] == "list_contacts"


def test_detect_returns_none_for_ordinary_chat():
    assert detect_google_intent("hey, how's it going?") is None
    assert detect_google_intent("what's the weather like") is None


@pytest.mark.asyncio
async def test_run_google_intent_calls_the_matched_registry_tool(monkeypatch):
    captured = {}

    class FakeRegistry:
        async def execute(self, tool_name, args):
            captured["tool_name"] = tool_name
            captured["args"] = args
            return {"events": []}

    monkeypatch.setattr("tools.registry.get_registry", lambda: FakeRegistry())
    intent = {"tool": "calendar", "action": "list_events", "kwargs": {}, "label": "Checking your calendar"}
    result = await run_google_intent(intent, "owner", "sess1")

    assert result == {"events": []}
    assert captured["tool_name"] == "calendar"
    assert captured["args"] == {"action": "list_events", "account_id": "owner"}


def test_format_google_result_shows_the_error(monkeypatch):
    intent = {"tool": "calendar", "action": "list_events", "label": "Checking your calendar"}
    out = format_google_result(intent, {"error": "connect Google first"})
    assert "Checking your calendar" in out
    assert "connect Google first" in out


def test_format_google_result_calendar_list_events():
    intent = {"tool": "calendar", "action": "list_events", "label": "x"}
    result = {"events": [{"summary": "Standup", "start": "2026-09-20T09:00:00Z", "location": "Zoom"}]}
    out = format_google_result(intent, result)
    assert "Standup" in out
    assert "Zoom" in out


def test_format_google_result_calendar_list_events_empty():
    intent = {"tool": "calendar", "action": "list_events", "label": "x"}
    assert "No upcoming events" in format_google_result(intent, {"events": []})


def test_format_google_result_gmail_list_messages():
    intent = {"tool": "gmail", "action": "list_messages", "label": "x"}
    result = {"messages": [{"subject": "Hi", "from": "a@x.com", "snippet": "hello"}]}
    out = format_google_result(intent, result)
    assert "Hi" in out
    assert "a@x.com" in out


def test_format_google_result_gmail_send():
    intent = {"tool": "gmail", "action": "send_message", "label": "x"}
    out = format_google_result(intent, {"sent_to": "bob@x.com", "subject": "Hello"})
    assert "bob@x.com" in out


def test_format_google_result_drive_create_note():
    intent = {"tool": "drive", "action": "create_note", "label": "x"}
    out = format_google_result(intent, {"file_id": "f1", "title": "Shopping"})
    assert "Shopping" in out
    assert "f1" in out


def test_format_google_result_drive_list_files_empty():
    intent = {"tool": "drive", "action": "list_files", "label": "x"}
    out = format_google_result(intent, {"files": []})
    assert "drive.file" in out


def test_format_google_result_contacts():
    intent = {"tool": "contacts", "action": "search_contacts", "label": "x"}
    result = {"contacts": [{"name": "Jane Doe", "emails": ["jane@x.com"], "phones": []}]}
    out = format_google_result(intent, result)
    assert "Jane Doe" in out
    assert "jane@x.com" in out
