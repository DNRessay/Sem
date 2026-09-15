import pytest

from pipeline.guide_intent import (
    detect_guide_intent,
    format_guide_result,
    guide_status_label,
    run_guide_intent,
)


def test_detect_guide_intent_finds_self_knowledge_phrasings():
    for msg in ["what can you do", "What are you capable of?", "what is semblance",
                "how does semblance work", "how do you work", "tell me about yourself",
                "what agents do you have", "what tools do you have",
                "what is your architecture", "who are you"]:
        assert detect_guide_intent(msg) is not None, msg


def test_detect_guide_intent_returns_the_full_query():
    q = "what can you do"
    assert detect_guide_intent(q) == q


def test_detect_guide_intent_returns_none_for_ordinary_chat():
    assert detect_guide_intent("hey, how's it going?") is None
    assert detect_guide_intent("what's the weather like") is None


def test_guide_status_label():
    assert guide_status_label() == "Looking up SEMBLANCE's own docs…"


def test_format_guide_result_passes_through_answer():
    assert format_guide_result("some answer") == "some answer"


def test_format_guide_result_handles_empty_answer():
    assert "couldn't find" in format_guide_result("").lower()


@pytest.mark.asyncio
async def test_run_guide_intent_routes_through_cables_man(monkeypatch):
    calls = []

    class FakeCablesMan:
        async def route(self, task):
            calls.append(task)
            return {"query": "what can you do", "answer": "I can plan, search, remember."}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    answer = await run_guide_intent("what can you do", "sess1")
    assert answer == "I can plan, search, remember."
    assert calls == [{"query": "what can you do", "agent": "guide", "session_id": "sess1"}]


@pytest.mark.asyncio
async def test_run_guide_intent_returns_empty_string_on_failure(monkeypatch):
    class FakeCablesMan:
        async def route(self, task):
            return {"error": "boom"}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    answer = await run_guide_intent("what can you do", "sess1")
    assert answer == ""
