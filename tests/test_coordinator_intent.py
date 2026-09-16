import pytest

from pipeline.coordinator_intent import (
    coordinator_status_label,
    detect_coordinator_intent,
    format_coordinator_result,
    run_coordinator_intent,
)


def test_detect_coordinator_intent_splits_a_comma_separated_list():
    assert detect_coordinator_intent("run these in parallel: write the report, check the numbers") == \
        ["write the report", "check the numbers"]


def test_detect_coordinator_intent_finds_coordinate_phrasing():
    assert detect_coordinator_intent("coordinate: task a, task b, task c") == ["task a", "task b", "task c"]


def test_detect_coordinator_intent_splits_on_and():
    assert detect_coordinator_intent("do this in parallel: fetch the page and summarize it") == \
        ["fetch the page", "summarize it"]


def test_detect_coordinator_intent_requires_at_least_two_subtasks():
    """A single item isn't worth fanning out through CoordinatorAgent —
    just answering directly is simpler and no slower."""
    assert detect_coordinator_intent("run in parallel: just one thing") is None


def test_detect_coordinator_intent_returns_none_for_ordinary_chat():
    assert detect_coordinator_intent("hey, how's it going?") is None
    assert detect_coordinator_intent("what's the weather like") is None


def test_status_label_shows_the_count():
    assert "2" in coordinator_status_label(["a", "b"])


@pytest.mark.asyncio
async def test_run_coordinator_intent_builds_xml_and_routes_through_cables_man(monkeypatch):
    captured = {}

    class FakeCablesMan:
        async def route(self, task):
            captured["task"] = task
            return {"task_id": "x", "results": {"worker_0": {"status": "processed"}, "worker_1": {"status": "processed"}}}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    result = await run_coordinator_intent(["write the report", "check the numbers"], "sess1")

    assert result["task_id"] == "x"
    task = captured["task"]
    assert task["agent"] == "coordinator"
    assert task["session_id"] == "sess1"
    assert '<query>write the report</query>' in task["xml"]
    assert '<query>check the numbers</query>' in task["xml"]
    assert 'type="general"' in task["xml"]


@pytest.mark.asyncio
async def test_run_coordinator_intent_marks_urls_as_fetch_type(monkeypatch):
    captured = {}

    class FakeCablesMan:
        async def route(self, task):
            captured["xml"] = task["xml"]
            return {"results": {}}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    await run_coordinator_intent(["https://example.com", "summarize it"], "sess1")

    assert '<task id="t0" type="fetch">' in captured["xml"]
    assert '<task id="t1" type="general">' in captured["xml"]


@pytest.mark.asyncio
async def test_run_coordinator_intent_returns_empty_dict_on_error(monkeypatch):
    class FakeCablesMan:
        async def route(self, task):
            return {"error": "boom"}

    monkeypatch.setattr("core.cables_man.CablesMan", FakeCablesMan)
    result = await run_coordinator_intent(["a", "b"], "sess1")
    assert result == {}


def test_format_coordinator_result_renders_each_subtask():
    subtasks = ["write the report", "fetch https://example.com"]
    result = {"results": {
        "worker_0": {"status": "processed", "query": "write the report", "type": "general"},
        "worker_1": {"content": "page text here", "url": "https://example.com"},
    }}
    out = format_coordinator_result(subtasks, result)
    assert "write the report" in out
    assert "page text here" in out


def test_format_coordinator_result_shows_worker_errors():
    subtasks = ["a", "b"]
    result = {"results": {
        "worker_0": {"error": "Lazy delegation rejected — task must have real content"},
        "worker_1": {"status": "processed"},
    }}
    out = format_coordinator_result(subtasks, result)
    assert "error" in out.lower()


def test_format_coordinator_result_empty_when_no_results():
    assert format_coordinator_result(["a", "b"], {}) == ""
