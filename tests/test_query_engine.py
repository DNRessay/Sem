import json

import pytest
import respx
from httpx import Response

from pipeline.query_engine import QueryEngine, _retry_after_seconds

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def test_retry_after_seconds_prefers_the_header():
    resp = Response(429, headers={"retry-after": "4.5"}, content=b"try again in 99s")
    assert _retry_after_seconds(resp, resp.content) == 4.5


def test_retry_after_seconds_falls_back_to_parsing_the_message():
    resp = Response(429)
    assert _retry_after_seconds(resp, b"Rate limit reached. Please try again in 7.25s") == 7.25


def test_retry_after_seconds_defaults_when_nothing_is_parseable():
    resp = Response(429)
    assert _retry_after_seconds(resp, b"no timing info here") == 5.0


def test_retry_after_seconds_is_capped():
    resp = Response(429, headers={"retry-after": "9999"})
    assert _retry_after_seconds(resp) == 20.0


def _groq_response(content: str):
    return Response(200, json={
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}]
    })


@pytest.mark.asyncio
async def test_call_llm_returns_content_and_hits_groq_on_first_call(moto_cache_table):
    engine = QueryEngine()
    with respx.mock:
        route = respx.post(GROQ_URL).mock(return_value=_groq_response("hello there"))
        result = await engine.call_llm([{"role": "user", "content": "hi"}], session_id="s1")

    assert result["content"] == "hello there"
    assert result["cached"] is False
    assert route.called


@pytest.mark.asyncio
async def test_call_llm_serves_second_identical_call_from_cache(moto_cache_table):
    engine = QueryEngine()
    messages = [{"role": "user", "content": "hi"}]
    with respx.mock:
        route = respx.post(GROQ_URL).mock(return_value=_groq_response("first"))
        first = await engine.call_llm(messages, session_id="s1")
        second = await engine.call_llm(messages, session_id="s1")

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["content"] == "first"
    assert route.call_count == 1  # second call served from DynamoDB cache, not Groq


@pytest.mark.asyncio
async def test_call_llm_does_not_reuse_cache_for_a_different_followup_query(moto_cache_table):
    # Regression test: the cache key used to be hashed from messages[:2]
    # (system + the *first* history entry), which is identical for every
    # turn after the first one in a session — so a second, unrelated
    # question was silently served the first turn's cached reply instead
    # of ever reaching Groq. Same system prompt and same first history
    # entry here, but a genuinely different final user query, must produce
    # two different Groq calls and two different answers.
    engine = QueryEngine()
    system = {"role": "system", "content": "ctx"}
    first_turn_user = {"role": "user", "content": "hello world"}
    first_turn_assistant = {"role": "assistant", "content": "hi there"}
    with respx.mock:
        route = respx.post(GROQ_URL).mock(side_effect=[
            _groq_response("hi there"),
            _groq_response("the sky is blue because of Rayleigh scattering"),
        ])
        first = await engine.call_llm([system, first_turn_user], session_id="s1")
        second = await engine.call_llm(
            [system, first_turn_user, first_turn_assistant, {"role": "user", "content": "why is the sky blue"}],
            session_id="s1",
        )

    assert first["content"] == "hi there"
    assert second["content"] == "the sky is blue because of Rayleigh scattering"
    assert second["cached"] is False
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_call_llm_raises_clear_error_when_groq_returns_no_choices(moto_cache_table):
    # e.g. an auth failure, unknown model, or rate limit — Groq's error shape
    # has no "choices" key, and the failure reason must survive into the
    # exception message rather than surfacing as a bare KeyError.
    engine = QueryEngine()
    with respx.mock:
        respx.post(GROQ_URL).mock(
            return_value=Response(401, json={"error": {"message": "Invalid API Key"}})
        )
        with pytest.raises(RuntimeError, match="Invalid API Key"):
            await engine.call_llm([{"role": "user", "content": "hi"}], session_id="s1")


@pytest.mark.asyncio
async def test_call_llm_retries_once_after_a_429_and_returns_the_retry_s_content(moto_cache_table, monkeypatch):
    """Groq's ITPM quota is a rolling per-account window, not a per-request
    cap — a 429 mid-burst usually clears itself within the wait Groq names
    ("Please try again in 13.86s"). One retry after that wait turns it into
    a normal reply instead of a raw error shown to the user."""
    engine = QueryEngine()
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("pipeline.query_engine.asyncio.sleep", fake_sleep)

    with respx.mock:
        route = respx.post(GROQ_URL).mock(side_effect=[
            Response(429, json={"error": {"message": "Rate limit reached... Please try again in 2.5s"}}),
            _groq_response("worked on retry"),
        ])
        result = await engine.call_llm([{"role": "user", "content": "hi"}], session_id="s1")

    assert result["content"] == "worked on retry"
    assert route.call_count == 2
    assert sleeps == [2.5]


@pytest.mark.asyncio
async def test_call_llm_raises_if_the_retry_also_429s(moto_cache_table, monkeypatch):
    engine = QueryEngine()

    async def fake_sleep(s):
        pass

    monkeypatch.setattr("pipeline.query_engine.asyncio.sleep", fake_sleep)

    with respx.mock:
        respx.post(GROQ_URL).mock(
            return_value=Response(429, json={"error": {"message": "Please try again in 1s"}})
        )
        with pytest.raises(RuntimeError, match="429"):
            await engine.call_llm([{"role": "user", "content": "hi"}], session_id="s1")


def _groq_sse_response(pieces: list[str], finish_reason: str = "stop"):
    body = "".join(
        f'data: {json.dumps({"choices": [{"delta": {"content": p}}]})}\n\n'
        for p in pieces
    )
    # Real Groq/OpenAI-shaped streams send finish_reason on its own trailing
    # chunk with no content, after the last piece of text.
    body += f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": finish_reason}]})}\n\n'
    body += "data: [DONE]\n\n"
    return Response(200, headers={"content-type": "text/event-stream"}, content=body)


@pytest.mark.asyncio
async def test_stream_llm_yields_each_piece_as_groq_sends_it(moto_cache_table):
    engine = QueryEngine()
    with respx.mock:
        route = respx.post(GROQ_URL).mock(return_value=_groq_sse_response(["hel", "lo ", "there"]))
        pieces = [p async for p in engine.stream_llm([{"role": "user", "content": "hi"}], session_id="s1")]

    assert pieces == ["hel", "lo ", "there"]
    assert route.called


@pytest.mark.asyncio
async def test_stream_llm_serves_second_identical_call_from_cache_in_one_piece(moto_cache_table):
    engine = QueryEngine()
    messages = [{"role": "user", "content": "hi"}]
    with respx.mock:
        route = respx.post(GROQ_URL).mock(return_value=_groq_sse_response(["first"]))
        first = [p async for p in engine.stream_llm(messages, session_id="s1")]
        second = [p async for p in engine.stream_llm(messages, session_id="s1")]

    assert "".join(first) == "first"
    assert second == ["first"]  # served whole from DynamoDB cache, not re-streamed
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_stream_llm_does_not_reuse_cache_for_a_different_followup_query(moto_cache_table):
    engine = QueryEngine()
    system = {"role": "system", "content": "ctx"}
    first_turn_user = {"role": "user", "content": "hello world"}
    first_turn_assistant = {"role": "assistant", "content": "hi there"}
    with respx.mock:
        route = respx.post(GROQ_URL).mock(side_effect=[
            _groq_sse_response(["hi there"]),
            _groq_sse_response(["the sky is blue"]),
        ])
        first = [p async for p in engine.stream_llm([system, first_turn_user], session_id="s1")]
        second = [p async for p in engine.stream_llm(
            [system, first_turn_user, first_turn_assistant, {"role": "user", "content": "why is the sky blue"}],
            session_id="s1",
        )]

    assert "".join(first) == "hi there"
    assert "".join(second) == "the sky is blue"
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_stream_llm_appends_a_visible_note_when_cut_off_by_max_tokens(moto_cache_table):
    """finish_reason "length" means Groq stopped because the reply hit
    max_tokens, not because the model was done — a silent cutoff mid-
    sentence reads as broken, so this must say so instead."""
    engine = QueryEngine()
    with respx.mock:
        respx.post(GROQ_URL).mock(
            return_value=_groq_sse_response(["this got cut", " off mid-sen"], finish_reason="length")
        )
        pieces = [p async for p in engine.stream_llm([{"role": "user", "content": "hi"}], session_id="s1")]

    full = "".join(pieces)
    assert full.startswith("this got cut off mid-sen")
    assert "cut off" in full.lower()
    assert "reply length limit" in full


@pytest.mark.asyncio
async def test_stream_llm_adds_no_note_when_finish_reason_is_stop(moto_cache_table):
    engine = QueryEngine()
    with respx.mock:
        respx.post(GROQ_URL).mock(return_value=_groq_sse_response(["a complete reply"], finish_reason="stop"))
        pieces = [p async for p in engine.stream_llm([{"role": "user", "content": "hi"}], session_id="s1")]

    assert "".join(pieces) == "a complete reply"


@pytest.mark.asyncio
async def test_stream_llm_raises_clear_error_when_groq_returns_no_choices(moto_cache_table):
    engine = QueryEngine()
    with respx.mock:
        respx.post(GROQ_URL).mock(
            return_value=Response(401, json={"error": {"message": "Invalid API Key"}})
        )
        with pytest.raises(RuntimeError, match="Invalid API Key"):
            async for _ in engine.stream_llm([{"role": "user", "content": "hi"}], session_id="s1"):
                pass


@pytest.mark.asyncio
async def test_stream_llm_retries_once_after_a_429_and_streams_the_retry(moto_cache_table, monkeypatch):
    engine = QueryEngine()
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("pipeline.query_engine.asyncio.sleep", fake_sleep)

    with respx.mock:
        route = respx.post(GROQ_URL).mock(side_effect=[
            Response(429, content=b"Please try again in 3.1s"),
            _groq_sse_response(["worked on retry"]),
        ])
        pieces = [p async for p in engine.stream_llm([{"role": "user", "content": "hi"}], session_id="s1")]

    assert "".join(pieces) == "worked on retry"
    assert route.call_count == 2
    assert sleeps == [3.1]


@pytest.mark.asyncio
async def test_stream_llm_raises_if_the_retry_also_429s(moto_cache_table, monkeypatch):
    engine = QueryEngine()

    async def fake_sleep(s):
        pass

    monkeypatch.setattr("pipeline.query_engine.asyncio.sleep", fake_sleep)

    with respx.mock:
        respx.post(GROQ_URL).mock(return_value=Response(429, content=b"Please try again in 1s"))
        with pytest.raises(RuntimeError, match="429"):
            async for _ in engine.stream_llm([{"role": "user", "content": "hi"}], session_id="s1"):
                pass


def test_fire_break_invalidates_known_vector_only(moto_cache_table):
    engine = QueryEngine()
    engine.cache_ctrl.write("k", "v")
    engine.fire_break("not_a_vector")
    assert engine.cache_ctrl.read("k") == "v"
    engine.fire_break("model_switch")
    assert engine.cache_ctrl.check_break() is True
