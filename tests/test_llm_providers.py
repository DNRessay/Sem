import json
from types import SimpleNamespace

import pytest
import respx
from httpx import Response

from pipeline import anthropic_provider, llm_providers

GROQ = "https://api.groq.com/openai/v1/chat/completions"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
QWEN = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"


@pytest.fixture
def keys(monkeypatch):
    from config import settings
    for name, value in {"LOCAL_LLM_URL": "", "GEMINI_API_KEY": "g", "GROQ_API_KEY": "q", "ANTHROPIC_API_KEY": "",
                        "OPENAI_API_KEY": "", "QWEN_API_KEY": "w", "DEEPSEEK_API_KEY": "", "KIMI_API_KEY": "", "HF_TOKEN": "h"}.items():
        monkeypatch.setattr(settings, name, value)


def _ok(text):
    return Response(200, json={"choices": [{"message": {"role": "assistant", "content": text, "reasoning_content": "x"}}]})


def test_available_lists_auto_then_configured_providers(keys):
    ids = [p["id"] for p in llm_providers.available()]
    assert ids == ["auto", "gemini", "groq", "qwen", "huggingface"]
    assert {p["id"]: p["free"] for p in llm_providers.available()}["qwen"] is False


@pytest.mark.asyncio
async def test_auto_moves_to_the_next_free_model_on_a_rate_limit(keys):
    with respx.mock:
        respx.post(GEMINI).mock(return_value=Response(429, json={"error": "quota"}))
        respx.post(GROQ).mock(return_value=_ok("from groq"))
        msg = await llm_providers.complete("auto", [{"role": "user", "content": "hi"}])
    assert msg["content"] == "from groq" and msg["_provider"] == "groq"
    assert "reasoning_content" not in msg


@pytest.mark.asyncio
async def test_a_bad_request_does_not_fall_through(keys):
    with respx.mock:
        respx.post(GEMINI).mock(return_value=Response(400, json={"error": "bad tool schema"}))
        groq = respx.post(GROQ).mock(return_value=_ok("x"))
        msg = await llm_providers.complete("auto", [{"role": "user", "content": "hi"}])
    assert "error" in msg and groq.call_count == 0


@pytest.mark.asyncio
async def test_paid_provider_only_when_picked_and_private_keys_are_stripped(keys):
    history = [{"role": "user", "content": "hi"},
               {"role": "assistant", "content": "a", "_provider": "anthropic", "_anthropic_content": [{"type": "text"}]}]
    with respx.mock:
        route = respx.post(QWEN).mock(return_value=_ok("from qwen"))
        msg = await llm_providers.complete("qwen", history)
    assert msg["_provider"] == "qwen"
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "qwen-max"
    assert all(not k.startswith("_") for m in sent["messages"] for k in m)


def test_openai_messages_translate_to_claude_shape():
    messages = [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "fix it"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "bash", "arguments": '{"command": "ls"}'}},
            {"id": "t2", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a"}'}},
        ]},
        {"role": "tool", "tool_call_id": "t1", "content": "a.py"},
        {"role": "tool", "tool_call_id": "t2", "content": "x"},
    ]
    system, out = anthropic_provider.to_anthropic(messages)
    assert system == "be brief"
    assert out[1]["content"][0] == {"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "ls"}}
    # Both tool results travel back together in one user turn.
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["t1", "t2"]


def test_claude_raw_content_is_replayed_verbatim():
    raw = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "done"}]
    _, out = anthropic_provider.to_anthropic([
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "done", "_anthropic_content": raw},
    ])
    assert out[1]["content"] is raw


def test_claude_response_becomes_an_openai_message():
    def block(**kw):
        return SimpleNamespace(**kw, to_dict=lambda: kw)

    response = SimpleNamespace(stop_reason="tool_use", content=[
        block(type="text", text="Running tests."),
        block(type="tool_use", id="t1", name="bash", input={"command": "pytest"}),
    ])
    msg = anthropic_provider.from_anthropic(response)
    assert msg["content"] == "Running tests."
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"command": "pytest"}
    assert msg["_anthropic_content"][1]["name"] == "bash"


def test_claude_refusal_is_an_error():
    assert "declined" in anthropic_provider.from_anthropic(SimpleNamespace(stop_reason="refusal", content=[]))["error"]


@pytest.mark.asyncio
async def test_any_hugging_face_model_by_repo_id(keys):
    with respx.mock:
        route = respx.post("https://router.huggingface.co/v1/chat/completions").mock(return_value=_ok("hi from hf"))
        msg = await llm_providers.complete("hf:Qwen/Qwen3-Coder-480B-A35B-Instruct", [{"role": "user", "content": "hi"}])
    assert msg["_provider"] == "huggingface"
    assert json.loads(route.calls[0].request.content)["model"] == "Qwen/Qwen3-Coder-480B-A35B-Instruct"
    assert route.calls[0].request.headers["authorization"] == "Bearer h"


@pytest.mark.asyncio
async def test_a_rejected_key_falls_through_to_the_next_free_model(keys):
    with respx.mock:
        respx.post(GEMINI).mock(return_value=Response(401, json={"error": "Invalid API Key"}))
        respx.post(GROQ).mock(return_value=_ok("from groq"))
        msg = await llm_providers.complete("auto", [{"role": "user", "content": "hi"}])
    assert msg["_provider"] == "groq"


@pytest.mark.asyncio
async def test_a_picked_model_retries_once_on_overload(keys, monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr(llm_providers.asyncio, "sleep", no_sleep)
    with respx.mock:
        route = respx.post(GEMINI).mock(side_effect=[Response(503, json={"error": "high demand"}), _ok("ok")])
        msg = await llm_providers.complete("gemini", [{"role": "user", "content": "hi"}])
    assert msg["_provider"] == "gemini" and route.call_count == 2


@pytest.mark.asyncio
async def test_auto_suggests_the_cheapest_paid_model_when_free_ones_are_out(keys):
    with respx.mock:
        respx.post(GEMINI).mock(return_value=Response(429))
        respx.post(GROQ).mock(return_value=Response(429))
        msg = await llm_providers.complete("auto", [{"role": "user", "content": "hi"}])
    assert "error" in msg and msg["suggest"]["id"] == "qwen"
