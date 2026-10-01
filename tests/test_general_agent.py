import pytest

from agents import general_agent
from agents.general_agent import GeneralAgent


def _replies(*msgs):
    queue = list(msgs)

    async def fake_complete(choice, messages, tools=None, **kw):
        fake_complete.calls.append((choice, messages, [t["function"]["name"] for t in tools or []]))
        return queue.pop(0)

    fake_complete.calls = []
    return fake_complete


@pytest.mark.asyncio
async def test_delegated_task_can_search_then_answer_on_the_free_chain(monkeypatch):
    fake = _replies(
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "web_search", "arguments": '{"query": "load shedding today"}'}}]},
        {"role": "assistant", "content": "Stage 2 from 16:00 (source: eskom.co.za)", "_provider": "gemini"},
    )

    async def fake_search(q):
        return {"ok": True, "results": [{"title": "Eskom", "url": "https://eskom.co.za"}]}

    monkeypatch.setattr("agents.tool_loop.llm_providers.complete", fake)
    monkeypatch.setattr(general_agent, "web_search", fake_search)
    result = await GeneralAgent(session_id="s1").run({"query": "is there load shedding today?", "context": "Owner is in Joburg"})
    assert result == {"status": "complete", "result": "Stage 2 from 16:00 (source: eskom.co.za)", "iterations": 1}
    choice, messages, tools = fake.calls[0]
    assert choice == "auto" and "web_search" in tools and "Owner is in Joburg" in messages[0]["content"]


@pytest.mark.asyncio
async def test_empty_query_and_model_failure(monkeypatch):
    assert await GeneralAgent(session_id="s1").run({"query": ""}) == {"error": "No query provided"}
    monkeypatch.setattr("agents.tool_loop.llm_providers.complete", _replies({"error": "No free model answered"}))
    result = await GeneralAgent(session_id="s1").run({"query": "hi"})
    assert result["status"] == "error" and "No free model answered" in result["result"]
