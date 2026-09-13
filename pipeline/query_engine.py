import json

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
        max_tokens: int = 1024,
        temperature: float = 0.5,
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
        async with httpx.AsyncClient(timeout=60) as client:
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
        max_tokens: int = 1024,
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
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST", "https://api.groq.com/openai/v1/chat/completions",
                json=payload, headers=headers,
            ) as r:
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
                    delta = chunk["choices"][0]["delta"].get("content")
                    if delta:
                        full_parts.append(delta)
                        yield delta

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