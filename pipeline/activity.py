"""Per-chat activity log for the Code / Co-work / Finance / Design tabs: what
the header's activity icon shows for the chat you're in. Stored as
agent_events under session "<tab>:<chat id>" (the main chat uses its own id)."""
import json
import re
import time

from storage.neon_store import get_store

_CHAT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def session_for(tab: str, body: dict) -> str | None:
    chat_id = str(body.get("chat_id") or "")
    return f"{tab}:{chat_id}" if _CHAT_ID.fullmatch(chat_id) else None


async def log(session: str | None, agent: str, action: str) -> None:
    if not session:
        return
    try:
        db = await get_store()
        await db.save_agent_event(session, agent, action[:500])
    except Exception:
        pass  # the log must never break a run


def _args(args: dict) -> str:
    shown = {k: ("••••" if k in ("value", "token", "auth", "content") else v) for k, v in (args or {}).items()}
    return json.dumps(shown, default=str)[:160]


class RunLog:
    """Feed a tool-loop agent's events through record(); writes a readable log line per step."""

    def __init__(self, session: str | None, tab: str):
        self.session, self.tab, self.started = session, tab, time.monotonic()

    def _who(self, name: str) -> str:
        return f"mcp:{name.split('__')[1]}" if name.startswith("mcp__") and name.count("__") >= 2 else self.tab

    async def start(self, message: str, model: str, mode: str = "") -> None:
        await log(self.session, self.tab, f"ok:run · {model or 'auto'}{f' · {mode}' if mode else ''} · {message[:120]}")

    async def record(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "tool":
            await log(self.session, self._who(ev.get("name", "")), f"ok:→ {ev.get('name')} {_args(ev.get('args'))}")
        elif t == "result":
            mark = "ok" if ev.get("ok") else "blocked"
            await log(self.session, self._who(ev.get("name", "")), f"{mark}:← {ev.get('name')}: {str(ev.get('output', ''))[:200]}")
        elif t == "approval":
            await log(self.session, self.tab, f"ok:waiting for your approval — {ev.get('summary', '')}")
        elif t == "handoff":
            await log(self.session, self.tab, f"ok:handoff → {ev.get('tab')}: {ev.get('task', '')[:120]}")
        elif t == "error":
            await log(self.session, self.tab, f"blocked:{ev.get('text', '')}")
        elif t == "done":
            secs = round(time.monotonic() - self.started)
            await log(self.session, self.tab, f"ok:done · {ev.get('steps')} step(s) · {secs}s · answered by {ev.get('model') or '?'}")
