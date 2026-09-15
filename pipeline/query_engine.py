import asyncio
import json
import re

import httpx

from cache.cache_ctrl import CacheController
from cache.sys_cache import ConvCache, SysCache
from config import settings
from memory.working_mem import WorkingMem

CACHE_BREAK_VECTORS = [
    "tool_change", "model_switch", "image_added", "system_prompt_edit",
    "user_model_update", "trust_level_change", "new_agent_spawned",
    "memory_consolidation", "ctx_length_exceeded", "tool_error",
    "session_restart", "provider_switch", "mcp_server_change", "manual_flush",
]

assert len(CACHE_BREAK_VECTORS) == 14

# Groq has rejected live requests at max_tokens=1024 with "Request too large
# ... on output tokens per minute (OTPM): Limit 1000, Requested 1024" for
# qwen/qwen3.8-27b — that request alone exceeded the account's per-minute
# output-token budget on this tier, independent of any other traffic that
# minute. 800 leaves real headroom under a 1000 OTPM cap; if Groq's limit for
# this model/tier is raised, this can go back up.
_DEFAULT_MAX_TOKENS = 800

# Groq's ITPM (input tokens/minute) quota is a *rolling* per-account window
# shared across every request that minute, not a per-request cap — a short
# burst of ordinary back-to-back turns can exhaust it even when each
# individual request is well within budget on its own, and the 429 it
# returns names exactly how long until the window clears ("Please try again
# in 13.86s"). Retrying once after that wait turns a burst-timing hiccup
# into a normal (if slightly slower) reply instead of a raw error dumped
# into the chat. Capped well under Lambda's own timeout — a wait this
# function decided not to honor is worse than just failing fast.
_MAX_RETRY_WAIT_SECONDS = 20.0
# A longer-scale quota (TPD — tokens per day) reports its wait with a
# minutes component too: "Please try again in 10m55.776s", not just
# "55.776s". The old pattern (seconds-only) still technically matched that
# string — regex engines don't require matching from the start — silently
# capturing just the "55.776" tail and treating an ~11 minute wait as ~1
# minute. The minutes group is optional so a plain "13.86s" (the common
# per-minute case) still matches exactly as before.
_RETRY_AFTER_RE = re.compile(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", re.I)


def _parse_retry_seconds(response: httpx.Response, body: bytes = b"") -> float | None:
    """The wait Groq actually asked for, uncapped — None if nothing
    parseable was found. Separate from _retry_after_seconds (which is
    capped, for deciding how long this process should actually sleep) so a
    caller can also tell the user an accurate "back in ~11 minutes" for a
    wait too long to be worth sleeping through."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    m = _RETRY_AFTER_RE.search(body.decode(errors="replace"))
    if m:
        minutes = float(m.group(1)) if m.group(1) else 0.0
        return minutes * 60 + float(m.group(2))
    return None


def _retry_after_seconds(response: httpx.Response, body: bytes = b"") -> float:
    parsed = _parse_retry_seconds(response, body)
    if parsed is None:
        return 5.0  # Groq didn't say — a sane default rather than not retrying at all
    return min(parsed, _MAX_RETRY_WAIT_SECONDS)


class RateLimitError(RuntimeError):
    """A Groq 429 that either named a wait too long to be worth sleeping
    through here (a daily/hour-scale quota, not the per-minute window the
    one built-in retry is for) or came back 429 again on that retry. Same
    message shape as the plain RuntimeError every other Groq failure
    raises (so generic error handling/tests keep working unchanged), but
    carries the actual, uncapped wait Groq asked for — `retry_after` is
    None when nothing parseable was in the response — so a caller can
    surface a real "back in ~11 minutes" instead of this raw text."""

    def __init__(self, status_code: int, model: str, body: str, retry_after: float | None):
        self.retry_after = retry_after
        super().__init__(f"Groq API error (status {status_code}) for model '{model}': {body}")


class QueryEngine:
    def __init__(self):
        self.sys_cache = SysCache()
        self.conv_cache = ConvCache()
        self.cache_ctrl = CacheController()
        self.working_mem = WorkingMem()

    async def call_llm(
        self,
        messages: list,
        model: str = settings.GROQ_MODEL,
        session_id: str = "default",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = 0.5,
        response_format: dict | None = None,
    ) -> dict:
        # Hash the whole conversation, not just the first two messages —
        # messages[:2] is system + the *first* history entry, which never
        # changes for the rest of a session once there's any history, so
        # every later turn was hitting the very first turn's cached reply
        # regardless of the actual new query.
        prefix_hash = self.cache_ctrl.compute_prefix_hash(str(messages))
        cached = self.cache_ctrl.read(prefix_hash)
        if cached and self.cache_ctrl.is_cache_valid(prefix_hash):
            return {"content": cached, "cached": True}

        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload, headers=headers,
            )
            if r.status_code == 429:
                await asyncio.sleep(_retry_after_seconds(r, r.content))
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload, headers=headers,
                )
            data = r.json()
            if "choices" not in data:
                # Surface whatever Groq actually said (bad API key, unknown
                # model, rate limit, etc.) instead of a bare KeyError that
                # hides the real reason in the traceback.
                raise RuntimeError(
                    f"Groq API error (status {r.status_code}) for model '{model}': {data}"
                )
            content = data["choices"][0]["message"]["content"]
            finish = data["choices"][0].get("finish_reason", "stop")

        self.cache_ctrl.write(prefix_hash, content)
        self.conv_cache.append(session_id, {"role": "assistant", "content": content})
        return {"content": content, "done": finish == "stop", "cached": False}

    async def stream_llm(
        self,
        messages: list,
        model: str = settings.GROQ_MODEL,
        session_id: str = "default",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = 0.5,
    ):
        """
        Same request/cache/Groq target as call_llm, but actually streams
        Groq's own token-by-token SSE output instead of waiting for the
        full completion and returning it as one piece — call_llm's single
        blocking request was why replies always "popped in" all at once
        right after the thinking indicator, regardless of the transport
        already being SSE end-to-end.
        """
        # See call_llm — hash the whole conversation, not just messages[:2].
        prefix_hash = self.cache_ctrl.compute_prefix_hash(str(messages))
        cached = self.cache_ctrl.read(prefix_hash)
        if cached and self.cache_ctrl.is_cache_valid(prefix_hash):
            yield cached
            return

        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        full_parts = []
        finish_reason = None
        async with httpx.AsyncClient(timeout=60) as client:
            retried = False
            while True:
                async with client.stream(
                    "POST", "https://api.groq.com/openai/v1/chat/completions",
                    json=payload, headers=headers,
                ) as r:
                    if r.status_code == 429:
                        body = await r.aread()
                        wait = _parse_retry_seconds(r, body)
                        # Worth one silent retry only the first time, and only
                        # when the wait is short enough that sleeping through
                        # it here is reasonable — a wait this long is a
                        # daily/hour-scale quota, not the per-minute window
                        # this retry is for, and a second call right now
                        # would just fail again immediately.
                        effective_wait = wait if wait is not None else 5.0
                        if not retried and effective_wait <= _MAX_RETRY_WAIT_SECONDS:
                            retried = True
                            await asyncio.sleep(effective_wait)
                            continue
                        raise RateLimitError(429, model, body.decode(errors="replace"), wait)
                    if r.status_code != 200:
                        body = await r.aread()
                        raise RuntimeError(
                            f"Groq API error (status {r.status_code}) for model '{model}': {body.decode(errors='replace')}"
                        )
                    async for line in r.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[len("data: "):]
                        if data_str == "[DONE]":
                            break
                        chunk = json.loads(data_str)
                        choice = chunk["choices"][0]
                        delta = choice["delta"].get("content")
                        if delta:
                            full_parts.append(delta)
                            yield delta
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                break

        if finish_reason == "length":
            # _DEFAULT_MAX_TOKENS is set low enough to stay under this
            # account's Groq rate limit (see its own comment) — real
            # replies do sometimes need more than that budget, and a
            # silent cutoff mid-sentence reads as broken, not as "the
            # answer was long." Say so instead of leaving it unexplained.
            note = "\n\n*(cut off — hit the reply length limit; ask me to continue for the rest)*"
            full_parts.append(note)
            yield note

        content = "".join(full_parts)
        self.cache_ctrl.write(prefix_hash, content)
        self.conv_cache.append(session_id, {"role": "assistant", "content": content})

    def connector_text_buffer(self, reasoning: str, session_id: str) -> str:
        import hashlib
        self.working_mem.append(session_id, reasoning)
        sig = hashlib.sha256(reasoning.encode()).hexdigest()[:8]
        return f"[CONNECTOR:{sig}] {reasoning[:200]}"

    def fire_break(self, reason: str):
        if reason in CACHE_BREAK_VECTORS:
            self.cache_ctrl.invalidate(reason)