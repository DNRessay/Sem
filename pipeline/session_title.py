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
        "Write a short chat title for this exchange: 3-6 words, no quotes, "
        "no trailing punctuation, no preamble — reply with just the title "
        "itself. Name the actual specific thing being discussed (a real "
        "feature, file, bug, tool, or decision mentioned below) — never a "
        "generic category like 'coding help', 'general chat', or "
        "'question about app'. If the assistant's reply reports a concrete "
        "outcome (fixed/failed/broken/working/deployed), reflect that "
        "outcome in the title so it's distinguishable from a chat that's "
        "still in progress on the same topic.\n\n"
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
