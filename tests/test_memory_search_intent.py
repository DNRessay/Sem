import time

import pytest

from pipeline.memory_search_intent import (
    detect_memory_search_intent,
    format_memory_search_result,
    memory_search_status_label,
    run_memory_search_intent,
)


def test_detect_when_did_i_ask_variants():
    """The captured term preserves the user's original capitalization
    (Mandela, not mandela) — friendlier to echo back in a reply; DB
    search itself is case-insensitive (ILIKE) regardless."""
    assert detect_memory_search_intent("When did I ask u about Mandela") == {
        "mode": "when", "term": "Mandela", "window": None,
    }
    assert detect_memory_search_intent("when did I say memento mori") == {
        "mode": "when", "term": "memento mori", "window": None,
    }
    assert detect_memory_search_intent("When did I talk about the WhatsApp bot") == {
        "mode": "when", "term": "the WhatsApp bot", "window": None,
    }


def test_detect_how_many_times_variants():
    assert detect_memory_search_intent("how many times have I mentioned memento mori") == {
        "mode": "count", "term": "memento mori", "window": None,
    }
    assert detect_memory_search_intent("How many times did I ask about buddy agent") == {
        "mode": "count", "term": "buddy agent", "window": None,
    }


def test_detect_strips_trailing_time_window():
    assert detect_memory_search_intent("how many times have I said memento mori this month") == {
        "mode": "count", "term": "memento mori", "window": 30 * 86400,
    }
    assert detect_memory_search_intent("when did I mention buddy today") == {
        "mode": "when", "term": "buddy", "window": 86400,
    }


def test_detect_returns_none_for_ordinary_chat():
    assert detect_memory_search_intent("hey, how's it going?") is None
    assert detect_memory_search_intent("what's the weather like") is None


def test_detect_returns_none_when_no_term_remains():
    assert detect_memory_search_intent("when did I ask") is None


def test_status_label():
    assert "mandela" in memory_search_status_label("mandela").lower()


class _FakeStore:
    def __init__(self, matches):
        self.matches = matches
        self.calls = []

    async def search_conversations(self, term, window_seconds=None, limit=30):
        self.calls.append((term, window_seconds, limit))
        return self.matches


@pytest.mark.asyncio
async def test_run_memory_search_intent_calls_the_store(monkeypatch):
    store = _FakeStore(matches=[])

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    result = await run_memory_search_intent({"mode": "when", "term": "mandela", "window": None}, "sess1")

    assert result == {"term": "mandela", "mode": "when", "matches": []}
    assert store.calls == [("mandela", None, 30)]


def test_format_memory_search_result_no_matches():
    out = format_memory_search_result({"term": "mandela", "mode": "when", "matches": []})
    assert "couldn't find" in out.lower()
    assert "mandela" in out


def test_format_memory_search_result_when_mode_shows_real_session_and_time():
    now = time.time()
    matches = [
        {"session_id": "session_abc", "role": "user", "content": "Who is Nelson Mandela",
         "created_at": now - 17 * 3600, "title": "Who is Nelson Mandela"},
    ]
    out = format_memory_search_result({"term": "mandela", "mode": "when", "matches": matches})
    assert "Who is Nelson Mandela" in out
    assert "17h ago" in out
    assert "You:" in out


def test_format_memory_search_result_count_mode_shows_the_tally():
    now = time.time()
    matches = [
        {"session_id": "s1", "role": "user", "content": "memento mori", "created_at": now, "title": None},
        {"session_id": "s2", "role": "user", "content": "memento mori again", "created_at": now - 3600, "title": None},
    ]
    out = format_memory_search_result({"term": "memento mori", "mode": "count", "matches": matches})
    assert "**2**" in out


def test_format_memory_search_result_falls_back_to_session_id_when_no_title():
    now = time.time()
    matches = [{"session_id": "session_xyz", "role": "assistant", "content": "reply", "created_at": now, "title": None}]
    out = format_memory_search_result({"term": "x", "mode": "when", "matches": matches})
    assert "session_xyz" in out
