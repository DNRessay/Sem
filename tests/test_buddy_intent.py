import pytest

from pipeline.buddy_intent import (
    buddy_status_label,
    detect_buddy_intent,
    format_buddy_result,
    run_buddy_intent,
)


def test_detect_buddy_intent_status_phrasings():
    for msg in ["buddy", "Buddy", "buddy status", "check my buddy", "show the buddy", "my buddy"]:
        assert detect_buddy_intent(msg) == {"action": "status"}, msg


def test_detect_buddy_intent_action_phrasings():
    assert detect_buddy_intent("pet my buddy") == {"action": "pet"}
    assert detect_buddy_intent("feed the buddy") == {"action": "feed"}
    assert detect_buddy_intent("train my buddy") == {"action": "train"}
    assert detect_buddy_intent("play with my buddy") == {"action": "play"}


def test_detect_buddy_intent_new_phrasings():
    for msg in ["hatch a buddy", "get a buddy", "hatch me a buddy", "create a new buddy", "start a buddy"]:
        assert detect_buddy_intent(msg) == {"action": "new"}, msg


def test_detect_buddy_intent_rename():
    assert detect_buddy_intent("rename my buddy to Spark") == {"action": "rename", "name": "Spark"}
    assert detect_buddy_intent("rename buddy to Ember") == {"action": "rename", "name": "Ember"}


def test_detect_buddy_intent_returns_none_for_unrelated_mentions():
    """"buddy" appearing inside an ordinary sentence must not misfire —
    same false-positive shape already fixed for bash_intent/continue_intent
    this session."""
    assert detect_buddy_intent("my buddy Dave said hi") is None
    assert detect_buddy_intent("hey, how's it going?") is None
    assert detect_buddy_intent("") is None


def test_buddy_status_label():
    assert buddy_status_label("pet") == "Petting your buddy…"
    assert buddy_status_label("unknown") == "Working with your buddy…"


def test_format_buddy_result_status():
    status = {
        "name": "Sparkcub_123", "species": "Sparkcub", "rarity": "Rare", "mood": "playful",
        "level": 2, "xp": 10, "xp_next": 150, "hp": 110,
        "stats": {"energy": 80, "happiness": 90, "focus": 70},
    }
    out = format_buddy_result("status", status)
    assert "Sparkcub_123" in out
    assert "Rare" in out
    assert "Level 2" in out


def test_format_buddy_result_status_with_no_buddy_yet():
    out = format_buddy_result("status", {})
    assert "no buddy yet" in out.lower()


def test_format_buddy_result_interact():
    result = {"message": "Sparkcub_123 purrs happily! 💛", "status": {"name": "Sparkcub_123", "species": "x",
              "rarity": "y", "mood": "z", "level": 1, "xp": 0, "xp_next": 100, "hp": 100,
              "stats": {"energy": 80, "happiness": 90, "focus": 70}}}
    out = format_buddy_result("pet", result)
    assert "purrs happily" in out
    assert "Sparkcub_123" in out


def test_format_buddy_result_error():
    out = format_buddy_result("pet", {"error": "Unknown buddy action: pet"})
    assert "couldn't reach your buddy" in out.lower()


@pytest.mark.asyncio
async def test_run_buddy_intent_routes_through_cables_man(monkeypatch):
    calls = []

    class FakeCablesMan:
        async def route(self, task):
            calls.append(task)
            return {"name": "x", "status": "ok"}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    result = await run_buddy_intent({"action": "status"}, "sess1")
    assert result == {"name": "x", "status": "ok"}
    assert calls == [{"agent": "buddy", "action": "status", "session_id": "sess1"}]


@pytest.mark.asyncio
async def test_run_buddy_intent_passes_name_for_rename(monkeypatch):
    calls = []

    class FakeCablesMan:
        async def route(self, task):
            calls.append(task)
            return {"message": "Renamed to Spark!"}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    await run_buddy_intent({"action": "rename", "name": "Spark"}, "sess1")
    assert calls == [{"agent": "buddy", "action": "rename", "session_id": "sess1", "name": "Spark"}]


@pytest.mark.asyncio
async def test_run_buddy_intent_returns_error_dict_on_unexpected_shape(monkeypatch):
    class FakeCablesMan:
        async def route(self, task):
            return "not a dict"

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    result = await run_buddy_intent({"action": "status"}, "sess1")
    assert result == {"error": "buddy agent returned an unexpected result"}
