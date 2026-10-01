"""Claude (paid option in the model picker) through the official Anthropic SDK.

The rest of SEMBLANCE speaks OpenAI-style chat messages, so this module
translates at the boundary: OpenAI-format messages/tools in, an
OpenAI-format assistant message out. Claude's own response content (thinking
and fallback blocks included) rides along on the returned message under
RAW_KEY and is sent back verbatim on the next turn — Claude's thinking blocks
are tied to the conversation, so history is only ever appended to, never
rebuilt from the text.
"""
import json

import anthropic

from config import settings

RAW_KEY = "_anthropic_content"
_MAX_TOKENS = 16000


def _tools(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools or []:
        fn = t.get("function") or {}
        out.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _user_content(content):
    if not isinstance(content, list):
        return content or ""
    blocks = []
    for part in content:
        if part.get("type") == "text":
            blocks.append({"type": "text", "text": part["text"]})
        elif part.get("type") == "image_url":
            url = part["image_url"]["url"]
            if url.startswith("data:"):
                media_type, data = url[5:].split(";base64,", 1)
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
            else:
                blocks.append({"type": "image", "source": {"type": "url", "url": url}})
    return blocks


def to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts, out, pending_results = [], [], []

    def flush_results():
        if pending_results:
            out.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for m in messages:
        role = m.get("role")
        if role == "system":
            system_parts.append(_text(m.get("content")))
        elif role == "tool":
            pending_results.append({
                "type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m.get("content") or "",
            })
        elif role == "assistant":
            flush_results()
            if m.get(RAW_KEY):
                out.append({"role": "assistant", "content": m[RAW_KEY]})
                continue
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            for call in m.get("tool_calls") or []:
                fn = call["function"]
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                blocks.append({"type": "tool_use", "id": call["id"], "name": fn["name"], "input": args})
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        else:
            flush_results()
            out.append({"role": "user", "content": _user_content(m.get("content"))})
    flush_results()
    return "\n\n".join(p for p in system_parts if p), out


def from_anthropic(response) -> dict:
    if response.stop_reason == "refusal":
        return {"error": "Claude declined this request (refusal) — try another model."}
    text, calls = [], []
    for block in response.content:
        if block.type == "text":
            text.append(block.text)
        elif block.type == "tool_use":
            calls.append({"id": block.id, "type": "function",
                          "function": {"name": block.name, "arguments": json.dumps(block.input)}})
    message = {"role": "assistant", "content": "\n".join(text), RAW_KEY: [b.to_dict() for b in response.content]}
    if calls:
        message["tool_calls"] = calls
    if response.stop_reason == "max_tokens" and not calls:
        message["content"] += "\n\n*(cut off — hit the reply length limit)*"
    return message


async def complete(messages: list[dict], tools: list[dict] | None = None, max_tokens: int = _MAX_TOKENS) -> dict:
    system, converted = to_anthropic(messages)
    kwargs = {
        "model": settings.ANTHROPIC_MODEL,
        "max_tokens": max(max_tokens, 4096),
        "messages": converted,
        "output_config": {"effort": "high"},
        # Server-side fallback: a classifier decline is retried on the model
        # Anthropic recommends for that refusal category instead of failing.
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = _tools(tools)
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        response = await client.beta.messages.create(**kwargs)
    except anthropic.RateLimitError:
        return {"error": "Claude rate limit hit", "rate_limited": True}
    except anthropic.APIStatusError as e:
        return {"error": f"Claude API error {e.status_code}: {str(e.message)[:300]}"}
    except anthropic.APIConnectionError as e:
        return {"error": f"Claude unreachable: {e}"}
    return from_anthropic(response)
