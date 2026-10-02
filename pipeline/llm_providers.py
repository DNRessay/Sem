"""Model picker: every LLM SEMBLANCE can use, behind one OpenAI-style call.

Free options come first and "auto" walks them in order, moving on when one
is rate-limited, down or misconfigured: self-hosted Bonsai -> Gemini free tier -> Groq.
Paid options (Claude, GPT, Qwen, DeepSeek, Kimi, and any Hugging Face model
via "hf:owner/model") are only used when picked explicitly. A provider appears in the picker once its key/URL is set.
"""
import asyncio
import time
from dataclasses import dataclass

import httpx

from config import settings
from pipeline import anthropic_provider


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    free: bool
    base_url: str
    key_setting: str
    model_setting: str
    max_tokens: int = 4096

    @property
    def key(self) -> str:
        return getattr(settings, self.key_setting, "")

    @property
    def model(self) -> str:
        return getattr(settings, self.model_setting, "")

    @property
    def configured(self) -> bool:
        if self.id == "bonsai":
            return bool(settings.LOCAL_LLM_URL)
        return bool(self.key)

    def url(self) -> str:
        base = settings.LOCAL_LLM_URL if self.id == "bonsai" else self.base_url
        if self.id == "qwen":
            base = settings.QWEN_BASE_URL
        return base.rstrip("/") + ("/v1/chat/completions" if self.id == "bonsai" else "/chat/completions")


PROVIDERS = {p.id: p for p in [
    Provider("bonsai", "Bonsai 27B (self-hosted)", True, "", "LOCAL_LLM_API_KEY", "LOCAL_LLM_MODEL"),
    Provider("gemini", "Gemini Flash (free tier)", True,
             "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "GEMINI_MODEL", 8192),
    # Groq's per-minute output cap on this account — see query_engine's _DEFAULT_MAX_TOKENS.
    Provider("groq", "Qwen 27B on Groq", True, "https://api.groq.com/openai/v1", "GROQ_API_KEY", "GROQ_MODEL", 800),
    Provider("anthropic", "Claude", False, "", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", 16000),
    Provider("openai", "GPT", False, "https://api.openai.com/v1", "OPENAI_API_KEY", "OPENAI_MODEL", 8192),
    Provider("qwen", "Qwen (Alibaba Cloud)", False, "", "QWEN_API_KEY", "QWEN_MODEL", 8192),
    Provider("deepseek", "DeepSeek", False, "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", 8192),
    Provider("kimi", "Kimi (Moonshot)", False, "https://api.moonshot.ai/v1", "KIMI_API_KEY", "KIMI_MODEL", 8192),
    Provider("huggingface", "Hugging Face", False, "https://router.huggingface.co/v1", "HF_TOKEN", "HF_MODEL", 8192),
]}
HF_PREFIX = "hf:"
FREE_ORDER = ("bonsai", "gemini", "groq")
# Cheapest first — offered (never switched to silently) when every free model is out.
PAID_ORDER = ("qwen", "deepseek", "kimi", "openai", "anthropic")


def cheapest_paid() -> dict | None:
    for pid in PAID_ORDER:
        p = PROVIDERS[pid]
        if p.configured:
            return {"id": p.id, "label": p.label}
    return None


# Context window (tokens) per provider — what the chat's context ring measures against.
CONTEXT = {"bonsai": 65536, "gemini": 1_000_000, "groq": 131072, "anthropic": 200000, "openai": 400000,
           "qwen": 131072, "deepseek": 128000, "kimi": 256000, "huggingface": 32768}


def available() -> list[dict]:
    """What the picker shows: "auto" plus every configured provider."""
    free = [p for p in FREE_ORDER if PROVIDERS[p].configured]
    # Auto can land on any free model, so it's measured against the smallest of them.
    auto_ctx = min((CONTEXT[p] for p in free), default=CONTEXT["bonsai"])
    items = [{"id": "auto", "label": "Auto (free models)", "free": True, "model": "", "context": auto_ctx}]
    for p in PROVIDERS.values():
        if p.configured:
            items.append({"id": p.id, "label": p.label, "free": p.free, "model": p.model, "context": CONTEXT.get(p.id, 32768)})
    return items


def _split(choice: str) -> tuple[str, str]:
    """"hf:owner/model" picks any model on Hugging Face's router."""
    if choice.startswith(HF_PREFIX) and len(choice) > len(HF_PREFIX):
        return "huggingface", choice[len(HF_PREFIX):]
    return choice, ""


def _chain(choice: str) -> list[Provider]:
    choice, _ = _split(choice)
    if choice in PROVIDERS and PROVIDERS[choice].configured:
        return [PROVIDERS[choice]]
    return [PROVIDERS[i] for i in FREE_ORDER if PROVIDERS[i].configured]


def estimate_tokens(messages: list[dict], reply: dict) -> int:
    chars = sum(len(str(m.get("content") or "")) for m in messages) + len(str(reply.get("content") or ""))
    return chars // 4


def _clean(messages: list[dict]) -> list[dict]:
    # Private keys (Claude's raw blocks, "_provider") mean nothing to other APIs, which reject unknown fields.
    return [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]


_SKIP_SIG = "skip_thought_signature_validator"  # Gemini's documented placeholder for calls it didn't sign


def _for_provider(p: Provider, messages: list[dict]) -> list[dict]:
    """Gemini signs each tool call it makes (tool_calls[].extra_content.google.thought_signature) and rejects
    a replayed call without one. Calls made by Bonsai/Groq earlier in the same loop have none, so give them the
    placeholder; every other provider rejects the extra_content field, so strip it."""
    out = []
    for m in _clean(messages):
        calls = m.get("tool_calls")
        if m.get("role") == "assistant" and calls:
            fixed = []
            for c in calls:
                c = dict(c)
                if p.id == "gemini":
                    extra = dict(c.get("extra_content") or {})
                    google = dict(extra.get("google") or {})
                    google.setdefault("thought_signature", _SKIP_SIG)
                    c["extra_content"] = {**extra, "google": google}
                else:
                    c.pop("extra_content", None)
                fixed.append(c)
            m = {**m, "tool_calls": fixed}
        out.append(m)
    return out


async def _complete_openai(p: Provider, client: httpx.AsyncClient, messages: list[dict],
                           tools: list[dict] | None, max_tokens: int, deadline: float, model: str = "") -> dict:
    if p.id == "bonsai":
        from pipeline.query_engine import wait_for_local_llm
        if not await wait_for_local_llm(client, min(deadline, time.monotonic() + 110)):
            return {"error": "the self-hosted model didn't come up in time", "unavailable": True}
    body = {"model": model or p.model, "messages": _for_provider(p, messages), "max_tokens": min(max_tokens, p.max_tokens)}
    if tools:
        body["tools"] = tools
    r = await client.post(p.url(), json=body,
                          headers={"Authorization": f"Bearer {p.key}", "Content-Type": "application/json"})
    if r.status_code == 429:
        return {"error": f"{p.label} rate limit hit", "rate_limited": True}
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200 or "choices" not in data:
        return {"error": f"{p.label} error {r.status_code}: {str(data or r.text)[:300]}",
                "unavailable": r.status_code not in (400, 422)}  # a bad key or outage: try the next model
    message = data["choices"][0]["message"]
    message.pop("reasoning_content", None)
    usage = data.get("usage") or {}
    message["_tokens"] = usage.get("total_tokens") or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
    return message


async def complete(choice: str, messages: list[dict], tools: list[dict] | None = None,
                   max_tokens: int = 4096, deadline: float | None = None,
                   client: httpx.AsyncClient | None = None) -> dict:
    """One assistant turn from the chosen provider (or the free chain for
    "auto"). Returns an OpenAI-style message dict, or {"error": ...}. The
    message carries "_provider" so callers can show who answered."""
    deadline = deadline or time.monotonic() + 300
    chain = _chain(choice)
    _, model_override = _split(choice)
    if not chain:
        return {"error": "No model is configured — set GROQ_API_KEY, GEMINI_API_KEY or LOCAL_LLM_URL."}
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=180.0), follow_redirects=True)
    last, errors = {"error": "no provider answered"}, []
    try:
        for p in chain:
            for attempt in range(2):
                try:
                    if p.id == "anthropic":
                        result = await anthropic_provider.complete(messages, tools, max_tokens)
                    else:
                        result = await _complete_openai(p, client, messages, tools, max_tokens, deadline, model_override)
                except httpx.HTTPError as e:
                    result = {"error": f"{p.label} unreachable: {e}", "unavailable": True}
                if "error" not in result:
                    result["_provider"] = p.id
                    if not result.get("_tokens"):  # provider didn't report usage: ~4 characters a token
                        result["_tokens"] = estimate_tokens(messages, result)
                    return result
                # A model picked on its own gets one retry on a brief overload; in "auto" the next model is the retry.
                transient = result.get("rate_limited") or result.get("unavailable")
                if attempt or not transient or len(chain) > 1 or time.monotonic() + 10 > deadline:
                    break
                await asyncio.sleep(4)
            last = result
            errors.append(result["error"][:200])
            if not (result.get("rate_limited") or result.get("unavailable")):
                break  # the request itself is bad; another model would reject it too
    finally:
        if owns_client:
            await client.aclose()
    if choice == "auto" and (last.get("rate_limited") or last.get("unavailable")):
        # The free chain is exhausted for now; the UI asks before using a paid model.
        last = {**last, "suggest": cheapest_paid()}
    if len(errors) > 1:
        return {**last, "error": "No free model answered — " + " · ".join(errors)}
    return last
