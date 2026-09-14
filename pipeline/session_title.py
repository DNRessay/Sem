from pipeline.query_engine import QueryEngine

_engine = QueryEngine()


async def generate_title(user_msg: str, reply: str) -> str:
    """A short (3-6 word) title for a session's sidebar/header entry,
    generated once from its first exchange — real summarized content
    instead of the raw first message or a bare session ID. Deliberately
    tiny max_tokens: this account's Groq rate limit is tight enough that
    even a title generation call needs to stay cheap. Returns "" on any
    failure so a title-generation hiccup never breaks the actual reply."""
    prompt = (
        "Summarize this exchange as a short chat title: 3-6 words, no "
        "quotes, no trailing punctuation, no preamble — reply with just "
        "the title itself.\n\n"
        f"User: {user_msg[:300]}\nAssistant: {reply[:300]}"
    )
    try:
        result = await _engine.call_llm(
            [{"role": "user", "content": prompt}], max_tokens=20, temperature=0.3,
        )
        title = (result.get("content") or "").strip().strip('"').strip("'").strip()
        return title[:80]
    except Exception:
        return ""
