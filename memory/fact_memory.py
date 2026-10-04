"""Fact memory, after VoiceMem (NTU/NUS/Tsinghua/CUHK): instead of searching whole old messages, Sem keeps short
statements about the user in two stores, facts ("lives in Soweto", "runs Vicinic") and persona ("likes short,
direct answers", "gets stressed about deadlines"), and every turn gets the few that matter (about five lines).

Learning happens off the conversation's path: the 15-minute tick reads the messages since it last looked and a
small model pulls the facts out (learn_recent). Recall runs alongside the other prep for a turn, so it doesn't
add to the wait — which matters most in voice mode, where every second of silence is heard."""
import asyncio
import json
import logging
import re

from cache import ddb_backend
from pipeline import llm_providers
from storage.embeddings import embed_text_or_none
from storage.neon_store import get_store

_log = logging.getLogger("semblance.facts")
KINDS = ("fact", "persona")
CURSOR = ("fact_memory", "cursor")
BATCH = 15
MODELS = ("gemini", "groq")

_PROMPT = """Below are messages a user sent to their personal assistant. Pull out short, durable statements about the
user that would help the assistant in future conversations.

- "fact": who they are and their world: names (family, staff, clients), places, their business and projects,
  tools they use, plans, dates, health or diet, things they own.
- "persona": how they feel and like to be treated: preferences, likes and dislikes, communication style, moods
  and what stresses or excites them, values.

Rules: third person, one short sentence each ("Lives in Soweto, Johannesburg.", "Prefers short, direct answers.").
Only what the user actually said or clearly implied about themselves; nothing about the assistant; no one-off
requests ("wants a poem now"), no secrets (passwords, ID or card numbers). If there's nothing worth keeping,
return [].

Messages:
{messages}

Reply with JSON only: [{{"kind": "fact" | "persona", "text": "..."}}]"""

_SECRET = re.compile(r"\b(password|passcode|pin|otp|cvv|card number|id number|api key|token)\b", re.I)


def parse_facts(text: str) -> list[dict]:
    text = re.sub(r"<think>.*?(</think>|$)", "", text or "", flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    i, j = text.find("["), text.rfind("]")
    if i == -1 or j <= i:
        return []
    try:
        items = json.loads(re.sub(r",\s*([\]}])", r"\1", text[i:j + 1]))
    except json.JSONDecodeError:
        return []
    out, seen = [], set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "").lower().strip()
        fact = re.sub(r"\s+", " ", str(it.get("text") or "")).strip()
        if kind not in KINDS or not 3 <= len(fact) <= 200 or _SECRET.search(fact) or fact.lower() in seen:
            continue
        seen.add(fact.lower())
        out.append({"kind": kind, "text": fact})
    return out[:12]


async def extract(messages: list[str]) -> list[dict] | None:
    """The facts in these messages ([] if none), or None when no model answered (so they get read again later)."""
    listed = "\n".join(f"- {m.strip()[:600]}" for m in messages if m.strip())
    if not listed:
        return []
    prompt = [{"role": "user", "content": _PROMPT.format(messages=listed)}]
    for model in MODELS:
        if not llm_providers.PROVIDERS[model].configured:
            continue
        result = await llm_providers.complete_within(model, prompt, seconds=30, max_tokens=700)
        if "error" not in result:
            return parse_facts(result.get("content") or "")
    return None


async def learn_recent(max_batches: int = 3) -> dict:
    """The tick's job: facts from the user's messages since last time. Keeps a cursor so each message is read once."""
    store = await get_store()
    after = int(ddb_backend.get(*CURSOR, fresh=True) or 0)
    turns = await store.user_turns_after(after, limit=BATCH * max_batches)
    saved = 0
    for start in range(0, len(turns), BATCH):
        batch = [t for t in turns[start:start + BATCH] if len(t["content"].split()) >= 3]
        found = await extract([t["content"] for t in batch])
        if found is None:
            break  # no model answered: try these again next tick
        for fact in found:
            await store.upsert_fact(fact["kind"], fact["text"], await embed_text_or_none(fact["text"]),
                                    session_id=batch[-1]["session_id"] if batch else "")
            saved += 1
        ddb_backend.set(*CURSOR, str(turns[min(start + BATCH, len(turns)) - 1]["id"]), ttl=365 * 86400)
    return {"read": len(turns), "saved": saved}


async def recall(query: str, facts: int = 3, persona: int = 2) -> str:
    """The few facts and preferences that matter for this message, as a short block for the system prompt."""
    try:
        store = await get_store()
        embedding = await embed_text_or_none(query)
        if embedding is None:  # embeddings down: the latest ones are better than nothing
            found = await asyncio.gather(store.recent_facts("fact", facts), store.recent_facts("persona", persona))
        else:
            found = await asyncio.gather(store.search_facts(embedding, "fact", facts),
                                         store.search_facts(embedding, "persona", persona))
    except Exception:
        _log.warning("fact recall failed", exc_info=True)
        return ""
    known, prefs = ([r["content"] for r in rows] for rows in found)
    if not known and not prefs:
        return ""
    lines = ["<about_user note=\"What you know about the user from past conversations. Use it naturally; don't recite it.\">"]
    lines += [f"  - {f}" for f in known]
    if prefs:
        lines.append("  How they like things:")
        lines += [f"  - {p}" for p in prefs]
    lines.append("</about_user>")
    return "\n".join(lines)
