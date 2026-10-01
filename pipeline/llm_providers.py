"""Model picker: every LLM SEMBLANCE can use, behind one OpenAI-style call.

Free options come first and "auto" walks them in order, moving on when one
is rate-limited or down: self-hosted Bonsai -> Gemini free tier -> Groq.
Paid options (Claude, GPT, Qwen, DeepSeek, Kimi, and any Hugging Face model
via "hf:owner/model") are only used when picked explicitly. A provider appears in the picker once its key/URL is set.
"""
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


def available() -> list[dict]:
    """What the picker shows: "auto" plus every configured provider."""
    items = [{"id": "auto", "label": "Auto (free models)", "free": True, "model": ""}]
    for p in PROVIDERS.values():
        if p.configured:
            items.append({"id": p.id, "label": p.label, "free": p.free, "model": p.model})
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


def _clean(messages: list[dict]) -> list[dict]:
    # Private keys (Claude's raw blocks, "_provider") mean nothing to other APIs, which reject unknown fields.
    return [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]


async def _complete_openai(p: Provider, client: httpx.AsyncClient, messages: list[dict],
                           tools: list[dict] | None, max_tokens: int, deadline: float, model: str = "") -> dict:
    if p.id == "bonsai":
        from pipeline.query_engine import wait_for_local_llm
        if not await wait_for_local_llm(client, min(deadline, time.monotonic() + 110)):
            return {"error": "the self-hosted model didn't come up in time", "unavailable": True}
    body = {"model": model or p.model, "messages": _clean(messages), "max_tokens": min(max_tokens, p.max_tokens)}
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
                "unavailable": r.status_code >= 500}
    message = data["choices"][0]["message"]
    message.pop("reasoning_content", None)
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
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=180.0))
    last = {"error": "no provider answered"}
    try:
        for p in chain:
            try:
                if p.id == "anthropic":
                    result = await anthropic_provider.complete(messages, tools, max_tokens)
                else:
                    result = await _complete_openai(p, client, messages, tools, max_tokens, deadline, model_override)
            except httpx.HTTPError as e:
                result = {"error": f"{p.label} unreachable: {e}", "unavailable": True}
            if "error" not in result:
                result["_provider"] = p.id
                return result
            last = result
            if not (result.get("rate_limited") or result.get("unavailable")):
                break
    finally:
        if owns_client:
            await client.aclose()
    return last
